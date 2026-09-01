#!/usr/bin/env python3
"""Profile-aware, loopback-only CotS Host MCP controller.

This supersedes the ToolLab-only controller for V4. It exposes fixed project
operations only, validates the selected workspace profile, proves that the
Unreal MCP endpoint belongs to the intended project, and binds mutation leases
to a live supervisor process identity/generation.
"""
from __future__ import annotations

import ctypes
import http.client
import json
import logging
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

try:
    from CotSMutationLease import LeaseError, acquire as acquire_lease, current_owner, release as release_lease, require as require_lease, transfer as transfer_lease
    from CotSProcess import identity_matches, process_identity
    from CotSWorkspaceProfiles import WorkspaceBoundaryError, assert_expected_git_remote, load_profile, profile_summary
except ModuleNotFoundError:
    from Scripts.CotSMutationLease import LeaseError, acquire as acquire_lease, current_owner, release as release_lease, require as require_lease, transfer as transfer_lease
    from Scripts.CotSProcess import identity_matches, process_identity
    from Scripts.CotSWorkspaceProfiles import WorkspaceBoundaryError, assert_expected_git_remote, load_profile, profile_summary

TOOLS_REPO = Path(__file__).resolve().parent.parent
PROFILE = load_profile()
ENGINE = Path(os.environ.get("COTS_UE_ROOT", r"C:\Program Files\Epic Games\UE_5.8"))
EDITOR = ENGINE / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe"
EDITOR_CMD = ENGINE / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe"
STATE_DIR = TOOLS_REPO / ".cots"
STATE_FILE = STATE_DIR / f"host-state-{PROFILE.name}.local.json"
LOCK_FILE = STATE_DIR / "mutation-lock-v4.local.json"
HOST = "127.0.0.1"
PORT = int(os.environ.get("COTS_HOST_MCP_PORT", "8010"))
UNREAL_MCP_PORT = int(os.environ.get("COTS_UNREAL_MCP_PORT", "8000"))
STATE_GUARD = threading.RLock()
LOGGER = logging.getLogger(__name__)
PROCESS_FLAGS = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform.startswith("win") else 0


class LifecycleRefused(RuntimeError):
    pass


def read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else default.copy()
    except (OSError, json.JSONDecodeError):
        return default.copy()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for attempt in range(5):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


def result(data: dict[str, Any], *, success: bool = True, error: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "success": success,
        "operation_id": str(uuid.uuid4()),
        "profile": PROFILE.name,
        "data": data,
    }
    if error:
        payload["error"] = error
    return payload


def _state_default() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "profile": PROFILE.name,
        "editor_process": None,
        "editor_started_at": None,
    }


def load_state() -> dict[str, Any]:
    state = read_json(STATE_FILE, _state_default())
    if state.get("profile") != PROFILE.name:
        return _state_default()
    return state


def exact_owned_editor_live(state: dict[str, Any]) -> bool:
    owner = state.get("editor_process")
    return identity_matches(owner if isinstance(owner, dict) else None)


def port_open() -> bool:
    try:
        with socket.create_connection((HOST, UNREAL_MCP_PORT), timeout=0.5):
            return True
    except OSError:
        return False


def _decode_tool_return(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        text = payload["result"]["content"][0]["text"]
        outer = json.loads(text)
        returned = outer.get("returnValue", outer)
        if isinstance(returned, str):
            returned = json.loads(returned)
        if not isinstance(returned, dict):
            raise TypeError("tool return is not an object")
        return returned
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"unreal_mcp_response_invalid:{error}") from error


def unreal_mcp_call(toolset_name: str, tool_name: str, arguments: dict[str, Any] | None = None, timeout: float = 12) -> dict[str, Any]:
    connection = http.client.HTTPConnection(HOST, UNREAL_MCP_PORT, timeout=timeout)
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    try:
        initialize = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "CotS Host Controller V4", "version": "4.0"},
            },
        }
        connection.request("POST", "/mcp", body=json.dumps(initialize), headers=headers)
        response = connection.getresponse()
        raw = response.read().decode("utf-8", errors="replace")
        session_id = response.getheader("Mcp-Session-Id")
        if response.status != 200 or not session_id:
            raise RuntimeError(f"unreal_mcp_initialize_failed:{response.status}:{raw[-400:]}")
        payload = json.loads(raw)
        protocol_version = payload.get("result", {}).get("protocolVersion", "2025-11-25")
        session_headers = {**headers, "Mcp-Session-Id": session_id, "Mcp-Protocol-Version": protocol_version}
        connection.request(
            "POST",
            "/mcp",
            body=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}),
            headers=session_headers,
        )
        initialized_response = connection.getresponse()
        initialized_response.read()
        if initialized_response.status not in (200, 202):
            raise RuntimeError("unreal_mcp_initialized_notification_failed")
        request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "call_tool",
                "arguments": {
                    "toolset_name": toolset_name,
                    "tool_name": tool_name,
                    "arguments": arguments or {},
                },
            },
        }
        connection.request("POST", "/mcp", body=json.dumps(request), headers=session_headers)
        response = connection.getresponse()
        raw = response.read().decode("utf-8", errors="replace")
        if response.status != 200:
            raise RuntimeError(f"unreal_mcp_tool_http_failed:{response.status}:{raw[-500:]}")
        payload = json.loads(raw)
        if "error" in payload:
            raise RuntimeError(f"unreal_mcp_tool_failed:{payload['error']}")
        return _decode_tool_return(payload)
    finally:
        connection.close()


def normalize_windows_path(value: str) -> str:
    return os.path.normcase(os.path.normpath(value.strip().replace("/", os.sep)))


def project_identity() -> dict[str, Any]:
    if not port_open():
        raise RuntimeError("unreal_mcp_port_not_open")
    inspected = unreal_mcp_call(
        "CotSDeveloperTools.CotSInspectionToolset",
        "GetProjectStatus",
    )
    data = inspected.get("data") if isinstance(inspected.get("data"), dict) else {}
    observed = str(data.get("project_path") or "")
    expected = str(PROFILE.project_path)
    if not observed or normalize_windows_path(observed) != normalize_windows_path(expected):
        raise RuntimeError(f"wrong_unreal_project: expected={expected!r} observed={observed!r}")
    if data.get("cots_module_loaded") is not True:
        raise RuntimeError("cots_developer_tools_module_not_loaded")
    return data


def unreal_mcp_ready() -> tuple[bool, dict[str, Any] | None, str | None]:
    try:
        identity = project_identity()
        return True, identity, None
    except Exception as error:
        return False, None, str(error)


def _lock_agent(arguments: dict[str, Any]) -> str:
    agent_id = arguments.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id.strip():
        raise ValueError("agent_id is required")
    require_lease(LOCK_FILE, agent_id=agent_id, workspace_profile=PROFILE.name)
    return agent_id


def get_status(_arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    with STATE_GUARD:
        state = load_state()
        editor_running = exact_owned_editor_live(state)
        if not editor_running and state.get("editor_process"):
            state = _state_default()
            atomic_json(STATE_FILE, state)
        ready, identity, identity_error = unreal_mcp_ready() if editor_running else (False, None, None)
        try:
            remote = assert_expected_git_remote(PROFILE) if PROFILE.workspace_root.exists() else None
            repo_ok = remote is not None
            repo_error = None
        except WorkspaceBoundaryError as error:
            repo_ok = False
            repo_error = str(error)
        lease = current_owner(LOCK_FILE)
        return result({
            **profile_summary(PROFILE),
            "engine_available": EDITOR.is_file() and EDITOR_CMD.is_file(),
            "project_exists": PROFILE.project_path.is_file(),
            "repository_valid": repo_ok,
            "repository_error": repo_error,
            "editor_running": editor_running,
            "editor_process": state.get("editor_process") if editor_running else None,
            "unreal_mcp_port_open": port_open(),
            "unreal_mcp_ready": ready,
            "unreal_identity": identity,
            "unreal_identity_error": identity_error,
            "mutation_lock": lease or None,
        })


def acquire(arguments: dict[str, Any]) -> dict[str, Any]:
    agent_id = arguments.get("agent_id")
    owner_pid = arguments.get("owner_pid")
    generation = arguments.get("generation")
    if not isinstance(agent_id, str) or not agent_id.strip():
        raise ValueError("agent_id is required")
    if not isinstance(owner_pid, int) or isinstance(owner_pid, bool) or owner_pid <= 0:
        raise ValueError("owner_pid must be a live positive integer")
    if not isinstance(generation, str) or not generation.strip():
        raise ValueError("generation is required")
    try:
        lease = acquire_lease(
            LOCK_FILE,
            agent_id=agent_id,
            owner_pid=owner_pid,
            generation=generation,
            workspace_profile=PROFILE.name,
        )
        return result({"acquired": True, "lease": lease})
    except LeaseError as error:
        owner = current_owner(LOCK_FILE)
        return result({"acquired": False, "owner": owner or None}, success=False, error=str(error))


def release(arguments: dict[str, Any]) -> dict[str, Any]:
    agent_id = arguments.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id.strip():
        raise ValueError("agent_id is required")
    try:
        release_lease(LOCK_FILE, agent_id=agent_id)
    except LeaseError as error:
        return result({}, success=False, error=str(error))
    return result({"released": True, "owner": agent_id})


def transfer(arguments: dict[str, Any]) -> dict[str, Any]:
    agent_id = arguments.get("agent_id")
    target = arguments.get("target_agent_id")
    if not isinstance(agent_id, str) or not agent_id.strip():
        raise ValueError("agent_id is required")
    if not isinstance(target, str) or not re.fullmatch(r"supervisor-task-[a-z0-9-]+", target):
        raise ValueError("target_agent_id must be a provider-neutral supervisor-task-* identity")
    try:
        lease = transfer_lease(LOCK_FILE, agent_id=agent_id, target_agent_id=target)
    except LeaseError as error:
        return result({}, success=False, error=str(error))
    return result({"transferred": True, "previous_owner": agent_id, "lease": lease})


def open_project(arguments: dict[str, Any]) -> dict[str, Any]:
    _lock_agent(arguments)
    with STATE_GUARD:
        state = load_state()
        if exact_owned_editor_live(state):
            ready, identity, identity_error = unreal_mcp_ready()
            return result({
                "changed": False,
                "editor_process": state.get("editor_process"),
                "unreal_mcp_ready": ready,
                "unreal_identity": identity,
                "unreal_identity_error": identity_error,
            })
        if not EDITOR.is_file() or not PROFILE.project_path.is_file():
            return result({}, success=False, error="project_or_engine_prerequisite_missing")
        process = subprocess.Popen(
            [str(EDITOR), str(PROFILE.project_path)],
            cwd=PROFILE.workspace_root,
            creationflags=PROCESS_FLAGS,
        )
        identity = process_identity(process.pid)
        if identity is None:
            return result({}, success=False, error="editor_process_identity_unavailable")
        state = {
            "schema_version": 2,
            "profile": PROFILE.name,
            "editor_process": identity.to_json(),
            "editor_started_at": time.time(),
        }
        atomic_json(STATE_FILE, state)
        return result({
            "changed": True,
            "editor_process": identity.to_json(),
            "mcp_url": f"http://{HOST}:{UNREAL_MCP_PORT}/mcp",
        })


def _post_close_to_exact_pid(pid: int) -> bool:
    if os.name != "nt":
        return False
    user32 = ctypes.windll.user32
    sent: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def close_window(hwnd: int, _lparam: int) -> bool:
        owner_pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
        if owner_pid.value == pid:
            user32.PostMessageW(hwnd, 0x0010, 0, 0)
            sent.append(int(hwnd))
        return True

    user32.EnumWindows(callback_type(close_window), 0)
    return bool(sent)


def close_project(arguments: dict[str, Any]) -> dict[str, Any]:
    _lock_agent(arguments)
    timeout = arguments.get("timeout_seconds", 60)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1 or timeout > 180:
        raise ValueError("timeout_seconds must be an integer between 1 and 180")
    with STATE_GUARD:
        state = load_state()
        owner = state.get("editor_process") if exact_owned_editor_live(state) else None
        if not owner:
            atomic_json(STATE_FILE, _state_default())
            return result({"changed": False, "editor_running": False})
        pid = int(owner["pid"])
        ready, identity, identity_error = unreal_mcp_ready()
        shutdown_method: str | None = None
        acknowledgement: dict[str, Any] | None = None
        if ready:
            try:
                acknowledgement = unreal_mcp_call(
                    "CotSDeveloperTools.CotSLifecycleToolset",
                    "RequestProjectShutdown",
                )
            except Exception as error:
                return result(
                    {"editor_process": owner, "unreal_identity": identity},
                    success=False,
                    error=f"unreal_mcp_shutdown_call_failed:{error}",
                )
            if acknowledgement.get("success") is not True:
                details = acknowledgement.get("error_details") or []
                code = details[0].get("code") if details and isinstance(details[0], dict) else "shutdown_refused"
                return result(
                    {"editor_process": owner, "lifecycle_acknowledgement": acknowledgement},
                    success=False,
                    error=str(code),
                )
            shutdown_method = "unreal_mcp"
        else:
            # Only an editor launched by this Host is eligible for the exact-PID
            # WM_CLOSE fallback. This is mainly a startup-failure escape hatch;
            # a healthy production editor should close through the guarded UE tool.
            if not _post_close_to_exact_pid(pid):
                return result(
                    {"editor_process": owner, "identity_error": identity_error},
                    success=False,
                    error="safe_close_unavailable",
                )
            shutdown_method = "wm_close_exact_owned_pid"

    started = time.monotonic()
    deadline = started + timeout
    while time.monotonic() < deadline:
        if not identity_matches(owner):
            with STATE_GUARD:
                atomic_json(STATE_FILE, _state_default())
            return result({
                "changed": True,
                "editor_running": False,
                "editor_process": owner,
                "shutdown_method": shutdown_method,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "lifecycle_acknowledgement": acknowledgement,
            })
        time.sleep(0.5)
    return result(
        {"editor_process": owner, "shutdown_method": shutdown_method},
        success=False,
        error="graceful_close_timeout",
    )


def wait_for_unreal_mcp(arguments: dict[str, Any]) -> dict[str, Any]:
    _lock_agent(arguments)
    timeout = arguments.get("timeout_seconds", 120)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1 or timeout > 300:
        raise ValueError("timeout_seconds must be an integer between 1 and 300")
    deadline = time.monotonic() + timeout
    last_error = "not_ready"
    while time.monotonic() < deadline:
        ready, identity, identity_error = unreal_mcp_ready()
        if ready:
            return result({"ready": True, "identity": identity, "mcp_url": f"http://{HOST}:{UNREAL_MCP_PORT}/mcp"})
        last_error = identity_error or last_error
        time.sleep(0.5)
    return result({"ready": False, "last_error": last_error}, success=False, error="unreal_mcp_timeout")


def bounded_timeout(arguments: dict[str, Any], default: int = 1800) -> int:
    timeout = arguments.get("timeout_seconds", default)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1 or timeout > 7200:
        raise ValueError("timeout_seconds must be an integer between 1 and 7200")
    return timeout


def run_fixed(arguments: dict[str, Any], command: list[str], name: str, *, require_editor_closed: bool = True) -> dict[str, Any]:
    _lock_agent(arguments)
    if require_editor_closed and exact_owned_editor_live(load_state()):
        return result({}, success=False, error="editor_must_be_closed")
    completed = subprocess.run(
        command,
        cwd=PROFILE.workspace_root,
        capture_output=True,
        text=True,
        timeout=bounded_timeout(arguments),
        creationflags=PROCESS_FLAGS,
        check=False,
    )
    output = ((completed.stdout or "") + (completed.stderr or ""))[-16000:]
    return result(
        {"name": name, "exit_code": completed.returncode, "output_tail": output},
        success=completed.returncode == 0,
        error=None if completed.returncode == 0 else f"{name}_failed",
    )


def build_project(arguments: dict[str, Any]) -> dict[str, Any]:
    if not PROFILE.build_script.is_file():
        return result({"build_script": str(PROFILE.build_script)}, success=False, error="build_script_missing")
    return run_fixed(arguments, [str(PROFILE.build_script)], f"build_{PROFILE.name}")


def run_automation(arguments: dict[str, Any]) -> dict[str, Any]:
    if not EDITOR_CMD.is_file() or not PROFILE.project_path.is_file():
        return result({}, success=False, error="project_or_engine_prerequisite_missing")
    command = [
        str(EDITOR_CMD),
        str(PROFILE.project_path),
        "-unattended",
        "-nop4",
        "-nosplash",
        "-NullRHI",
        "-NoSound",
        "-DDC-ForceMemoryCache",
        f"-ExecCmds=Automation RunTests {PROFILE.automation_filter};Quit",
        "-TestExit=Automation Test Queue Empty",
    ]
    return run_fixed(arguments, command, f"automation_{PROFILE.name}")


ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


def schema(properties: dict[str, dict[str, Any]], required: list[str] | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        value["required"] = required
    return value


AGENT = {"type": "string", "minLength": 1}
TIMEOUT = {"type": "integer", "minimum": 1, "maximum": 7200}

TOOLS: dict[str, tuple[str, dict[str, Any], ToolHandler]] = {
    "GetWorkspaceStatus": (
        "Read selected profile, repository, editor, Unreal MCP identity, and lease status.",
        schema({}),
        get_status,
    ),
    "AcquireMutationLock": (
        "Acquire the process/generation-bound single-mutator lease.",
        schema({"agent_id": AGENT, "owner_pid": {"type": "integer", "minimum": 1}, "generation": AGENT}, ["agent_id", "owner_pid", "generation"]),
        acquire,
    ),
    "ReleaseMutationLock": (
        "Release the caller's live mutation lease.",
        schema({"agent_id": AGENT}, ["agent_id"]),
        release,
    ),
    "TransferMutationLock": (
        "Transfer a live lease to a provider-neutral supervisor-task identity.",
        schema({"agent_id": AGENT, "target_agent_id": {"type": "string", "pattern": "^supervisor-task-[a-z0-9-]+$"}}, ["agent_id", "target_agent_id"]),
        transfer,
    ),
    "OpenProject": (
        "Launch only the fixed Unreal project selected by the startup profile.",
        schema({"agent_id": AGENT}, ["agent_id"]),
        open_project,
    ),
    "CloseProject": (
        "Request guarded normal shutdown of the exact Host-owned editor process.",
        schema({"agent_id": AGENT, "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 180}}, ["agent_id"]),
        close_project,
    ),
    "WaitForUnrealMcp": (
        "Wait until native Unreal MCP identifies the expected project and CotS plugin.",
        schema({"agent_id": AGENT, "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 300}}, ["agent_id"]),
        wait_for_unreal_mcp,
    ),
    "BuildProject": (
        "Run only the canonical build script for the selected profile.",
        schema({"agent_id": AGENT, "timeout_seconds": TIMEOUT}, ["agent_id"]),
        build_project,
    ),
    "RunCotSAutomation": (
        "Run the fixed CotS automation filter against the selected project.",
        schema({"agent_id": AGENT, "timeout_seconds": TIMEOUT}, ["agent_id"]),
        run_automation,
    ),
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args: object) -> None:
        pass

    def reply(self, code: int, payload: dict[str, Any], extra_headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload).encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            for name, value in (extra_headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionResetError, BrokenPipeError):
            LOGGER.debug("loopback MCP client disconnected")

    def do_POST(self) -> None:
        if self.path != "/mcp":
            self.reply(404, {"error": "not_found"})
            return
        request_id: object = None
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 2_000_000:
                raise ValueError("invalid_content_length")
            request = json.loads(self.rfile.read(length))
            if not isinstance(request, dict):
                raise ValueError("request_must_be_object")
            method = request.get("method")
            request_id = request.get("id")
            extra_headers: dict[str, str] = {}
            if method == "initialize":
                extra_headers["Mcp-Session-Id"] = str(uuid.uuid4())
                response: dict[str, Any] = {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "CotS Host Controller", "version": "4.0"},
                }
            elif method == "notifications/initialized":
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            elif method == "tools/list":
                response = {
                    "tools": [
                        {"name": name, "description": description, "inputSchema": input_schema}
                        for name, (description, input_schema, _handler) in TOOLS.items()
                    ]
                }
            elif method == "tools/call":
                params = request.get("params") or {}
                name = params.get("name")
                arguments = params.get("arguments") or {}
                if name not in TOOLS:
                    raise ValueError("unknown_fixed_tool")
                if not isinstance(arguments, dict):
                    raise ValueError("tool arguments must be an object")
                response = {"content": [{"type": "text", "text": json.dumps(TOOLS[name][2](arguments))}]}
            else:
                raise ValueError("method_not_found")
            self.reply(200, {"jsonrpc": "2.0", "id": request_id, "result": response}, extra_headers)
        except Exception as error:
            self.reply(400, {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": str(error)}})


def main() -> int:
    print(
        f"CotS Host MCP V4 profile={PROFILE.name} listening only on http://{HOST}:{PORT}/mcp",
        flush=True,
    )
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
