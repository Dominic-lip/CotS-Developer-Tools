#!/usr/bin/env python3
"""Narrow, loopback-only MCP controller for the CotS ToolLab lifecycle.

This service intentionally exposes named project operations only.  It never
accepts command lines, paths, executable names, arbitrary PIDs, or filesystem
operations from an MCP client.
"""
from __future__ import annotations

import json
import logging
import os
import re
import socket
import subprocess
import sys
import threading
import time
import uuid
import ctypes
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
PROJECT = REPO / "ToolLab" / "CotSToolLab.uproject"
ENGINE = Path(os.environ.get("COTS_UE_ROOT", r"C:\Program Files\Epic Games\UE_5.8"))
EDITOR = ENGINE / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe"
EDITOR_CMD = ENGINE / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe"
BUILD = REPO / "Scripts" / "Build-ToolLab.cmd"
STATE_DIR = REPO / ".cots"
STATE_FILE = STATE_DIR / "host-state.local.json"
LOCK_FILE = STATE_DIR / "mutation-lock.local.json"
HOST, PORT, MCP_PORT = "127.0.0.1", 8010, 8000
STATE_GUARD = threading.RLock()
LOGGER = logging.getLogger(__name__)
# UnrealEditor/UBT/UBA manage their own worker-process pools and, on Windows,
# a console-control broadcast one of them sends to "its own" process group
# targets the entire console's process group by default -- including this
# Host controller and, transitively, the supervisor/factory-controller/CLI
# processes that share its console. CREATE_NEW_PROCESS_GROUP roots each
# spawned editor/build child in its own group so that broadcast can no
# longer reach back up and kill this server or its ancestors.
_EDITOR_PROCESS_CREATIONFLAGS = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform.startswith("win") else 0


class LifecycleRefused(RuntimeError):
    pass


def read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default.copy()


def write_json(path: Path, value: dict[str, Any]) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def load_state() -> dict[str, Any]:
    return read_json(STATE_FILE, {"editor_pid": None, "editor_started_at": None})


def pid_running(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def mcp_ready() -> bool:
    try:
        with socket.create_connection((HOST, MCP_PORT), timeout=0.5):
            return True
    except OSError:
        return False


def unreal_mcp_call_lifecycle_shutdown() -> dict[str, Any]:
    """Call the one fixed ToolLab shutdown tool using UE 5.8 HTTP MCP sessions."""
    connection = http.client.HTTPConnection(HOST, MCP_PORT, timeout=8)
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    try:
        initialize = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "CotS Host Controller", "version": "1.0"}}}
        connection.request("POST", "/mcp", body=json.dumps(initialize), headers=headers)
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        session_id = response.getheader("Mcp-Session-Id")
        if response.status != 200 or not session_id:
            raise RuntimeError("unreal_mcp_initialize_failed")
        protocol_version = payload.get("result", {}).get("protocolVersion", "2025-11-25")
        session_headers = {**headers, "Mcp-Session-Id": session_id, "Mcp-Protocol-Version": protocol_version}
        initialized = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        connection.request("POST", "/mcp", body=json.dumps(initialized), headers=session_headers)
        notification_response = connection.getresponse()
        notification_response.read()
        if notification_response.status not in (200, 202):
            raise RuntimeError("unreal_mcp_initialized_notification_failed")
        # UE 5.8 currently runs in tool-search mode: its single dispatcher is
        # still constrained here to this exact toolset/function pair.
        request = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "call_tool", "arguments": {"toolset_name": "CotSDeveloperTools.CotSLifecycleToolset", "tool_name": "RequestToolLabShutdown", "arguments": {}}}}
        connection.request("POST", "/mcp", body=json.dumps(request), headers=session_headers)
        response = connection.getresponse()
        tool_payload = json.loads(response.read().decode("utf-8"))
        if response.status != 200 or "error" in tool_payload:
            raise RuntimeError(f"unreal_mcp_lifecycle_tool_failed:{tool_payload}")
        try:
            returned = json.loads(tool_payload["result"]["content"][0]["text"])["returnValue"]
            lifecycle_result = json.loads(returned)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise RuntimeError(f"unreal_mcp_lifecycle_response_invalid:{error}") from error
        if not lifecycle_result.get("success", False):
            details = lifecycle_result.get("error_details", [])
            code = details[0].get("code", "shutdown_refused") if details else "shutdown_refused"
            raise LifecycleRefused(code)
        return {"transport": tool_payload, "lifecycle_result": lifecycle_result}
    finally:
        connection.close()


def lock_owner() -> str | None:
    return read_json(LOCK_FILE, {}).get("agent_id")


def require_owner(arguments: dict[str, Any]) -> str:
    agent_id = arguments.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id.strip():
        raise ValueError("agent_id is required for every mutating lifecycle operation")
    if lock_owner() != agent_id:
        raise ValueError("mutation_lock_not_owned: acquire the lifecycle lock before mutating ToolLab")
    return agent_id


def result(data: dict[str, Any], *, success: bool = True, error: str | None = None) -> dict[str, Any]:
    payload = {"success": success, "operation_id": str(uuid.uuid4()), "data": data}
    if error:
        payload["error"] = error
    return payload


def status(_arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    with STATE_GUARD:
        state = load_state()
        running = pid_running(state.get("editor_pid"))
        if not running and state.get("editor_pid") is not None:
            state["editor_pid"] = None
            state["editor_started_at"] = None
            write_json(STATE_FILE, state)
        return {
            "project": str(PROJECT),
            "editor_running": running,
            "editor_pid": state.get("editor_pid") if running else None,
            "mcp_ready": mcp_ready(),
            "mutation_lock_owner": lock_owner(),
            "engine_available": EDITOR.is_file() and EDITOR_CMD.is_file(),
        }


def acquire(arguments: dict[str, Any]) -> dict[str, Any]:
    agent_id = arguments.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id.strip():
        raise ValueError("agent_id is required")
    with STATE_GUARD:
        owner = lock_owner()
        if owner and owner != agent_id:
            return result({"owner": owner}, success=False, error="mutation_lock_held")
        write_json(LOCK_FILE, {"agent_id": agent_id, "acquired_at": time.time()})
    return result({"owner": agent_id, "acquired": True})


def release(arguments: dict[str, Any]) -> dict[str, Any]:
    agent_id = require_owner(arguments)
    with STATE_GUARD:
        try:
            LOCK_FILE.unlink()
        except FileNotFoundError:
            pass
    return result({"owner": agent_id, "released": True})


def transfer_lock(arguments: dict[str, Any]) -> dict[str, Any]:
    """Atomically replace the bearer owner token without ever releasing the
    single-writer lock. This is solely for a supervisor handoff from a legacy
    provider-scoped task id to its stable provider-neutral task id."""
    agent_id = require_owner(arguments)
    target = arguments.get("target_agent_id")
    if not isinstance(target, str) or not re.fullmatch(r"supervisor-task-[a-z0-9-]+", target):
        raise ValueError("target_agent_id must be a provider-neutral supervisor-task-* identity")
    with STATE_GUARD:
        write_json(LOCK_FILE, {"agent_id": target, "acquired_at": time.time(), "transferred_from": agent_id})
    return result({"owner": target, "transferred": True, "previous_owner": agent_id})


def open_editor(arguments: dict[str, Any]) -> dict[str, Any]:
    require_owner(arguments)
    with STATE_GUARD:
        current = status()
        if current["editor_running"]:
            return result({**current, "changed": False})
        if not EDITOR.is_file() or not PROJECT.is_file():
            return result(current, success=False, error="tool_lab_prerequisite_missing")
        process = subprocess.Popen([str(EDITOR), str(PROJECT)], cwd=REPO, creationflags=_EDITOR_PROCESS_CREATIONFLAGS)
        write_json(STATE_FILE, {"editor_pid": process.pid, "editor_started_at": time.time()})
    return result({"editor_pid": process.pid, "changed": True, "mcp_url": f"http://{HOST}:{MCP_PORT}/mcp"})


def close_editor(arguments: dict[str, Any]) -> dict[str, Any]:
    require_owner(arguments)
    timeout = arguments.get("timeout_seconds", 45)
    if not isinstance(timeout, int) or timeout < 1 or timeout > 120:
        raise ValueError("timeout_seconds must be an integer between 1 and 120")
    with STATE_GUARD:
        current = status()
        pid = current["editor_pid"]
        if not pid:
            return result({"changed": False, "editor_running": False})
        shutdown_method = None
        acknowledgement: dict[str, Any] | None = None
        warnings: list[str] = []
        if current["mcp_ready"]:
            try:
                acknowledgement = unreal_mcp_call_lifecycle_shutdown()
                shutdown_method = "unreal_mcp"
            except LifecycleRefused as error:
                return result({"editor_pid": pid, "shutdown_method": "unreal_mcp", "graceful": False, "warnings": [str(error)]}, success=False, error=str(error))
            except Exception as error:
                warnings.append(str(error))
        if shutdown_method is None:
            # Fallback only: a graceful request to a top-level window belonging to
            # the exact ToolLab PID this controller launched.
            user32 = ctypes.windll.user32
            sent = []
            callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            def close_window(hwnd: int, _lparam: int) -> bool:
                owner_pid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
                if owner_pid.value == pid:
                    user32.PostMessageW(hwnd, 0x0010, 0, 0)
                    sent.append(hwnd)
                return True
            user32.EnumWindows(callback_type(close_window), 0)
            if not sent:
                return result({"editor_pid": pid, "warnings": warnings}, success=False, error="graceful_close_unavailable")
            shutdown_method = "wm_close"
    started = time.monotonic()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_running(pid):
            with STATE_GUARD:
                write_json(STATE_FILE, {"editor_pid": None, "editor_started_at": None})
            mcp_gone = not mcp_ready()
            return result({"changed": True, "editor_running": False, "editor_pid": pid, "shutdown_method": shutdown_method, "graceful": True, "duration_ms": int((time.monotonic() - started) * 1000), "unreal_mcp_gone": mcp_gone, "lifecycle_acknowledgement": acknowledgement, "warnings": warnings})
        time.sleep(0.5)
    return result({"editor_pid": pid, "shutdown_method": shutdown_method, "warnings": warnings}, success=False, error="graceful_close_timeout")


def wait_for_mcp(arguments: dict[str, Any]) -> dict[str, Any]:
    require_owner(arguments)
    timeout = arguments.get("timeout_seconds", 90)
    if not isinstance(timeout, int) or timeout < 1 or timeout > 180:
        raise ValueError("timeout_seconds must be an integer between 1 and 180")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if mcp_ready():
            return result({"ready": True, "mcp_url": f"http://{HOST}:{MCP_PORT}/mcp"})
        time.sleep(0.5)
    return result({"ready": False}, success=False, error="unreal_mcp_timeout")


def run_fixed(arguments: dict[str, Any], command: list[str], name: str, require_editor_closed: bool = True) -> dict[str, Any]:
    require_owner(arguments)
    current = status()
    if require_editor_closed and current["editor_running"]:
        return result(current, success=False, error="editor_must_be_closed")
    completed = subprocess.run(command, cwd=REPO, capture_output=True, text=True, timeout=arguments.get("timeout_seconds", 900), creationflags=_EDITOR_PROCESS_CREATIONFLAGS)
    output = (completed.stdout + completed.stderr)[-12000:]
    return result({"name": name, "exit_code": completed.returncode, "output_tail": output}, success=completed.returncode == 0, error=None if completed.returncode == 0 else f"{name}_failed")


def build(arguments: dict[str, Any]) -> dict[str, Any]:
    return run_fixed(arguments, [str(BUILD)], "build_tool_lab")


def tests(arguments: dict[str, Any]) -> dict[str, Any]:
    command = [str(EDITOR_CMD), str(PROJECT), "-unattended", "-nop4", "-nosplash", "-NullRHI", "-NoSound", "-DDC-ForceMemoryCache", "-ExecCmds=Automation RunTests CotS;Quit", "-TestExit=Automation Test Queue Empty"]
    return run_fixed(arguments, command, "run_cots_automation")


TOOLS = {
    "GetToolLabStatus": ("Read current lifecycle readiness; does not require the lock.", status),
    "AcquireMutationLock": ("Claim the single mutating-agent lifecycle lock.", acquire),
    "ReleaseMutationLock": ("Release the caller's lifecycle lock.", release),
    "TransferMutationLock": ("Atomically transfer a legacy task lock to a provider-neutral supervisor task identity.", transfer_lock),
    "OpenToolLab": ("Launch the fixed ToolLab project.", open_editor),
    "CloseToolLab": ("Request a graceful close for the ToolLab process this controller launched.", close_editor),
    "WaitForUnrealMcp": ("Wait for the fixed loopback Unreal MCP endpoint.", wait_for_mcp),
    "BuildToolLab": ("Run the canonical Scripts\\Build-ToolLab.cmd command.", build),
    "RunCotSAutomation": ("Run the fixed CotS Automation suite with the DDC workaround.", tests),
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, _format: str, *_args: object) -> None: pass
    def loopback_disconnect(self, error: BaseException) -> bool:
        """A controlled local client shutdown is not a request failure."""
        host = self.client_address[0] if self.client_address else ""
        if host in {"127.0.0.1", "::1", "localhost"} and isinstance(error, (ConnectionResetError, BrokenPipeError)):
            LOGGER.debug("Loopback MCP client disconnected while receiving response: %s", type(error).__name__)
            return True
        return False
    def reply(self, code: int, payload: dict[str, Any], extra_headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload).encode("utf-8")
        try:
            self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body)))
            for header_name, header_value in (extra_headers or {}).items():
                self.send_header(header_name, header_value)
            self.end_headers(); self.wfile.write(body)
        except (ConnectionResetError, BrokenPipeError) as error:
            if not self.loopback_disconnect(error):
                raise
    def method_not_allowed(self) -> None:
        # Streamable HTTP MCP transport makes the server-push GET stream and
        # the DELETE session-termination endpoint optional; the spec requires
        # a server that does not implement them to answer 405, not silently
        # drop the connection. Python's BaseHTTPRequestHandler defaults an
        # unimplemented method to 501, which at least one real MCP client
        # (Codex's rmcp) treats as a fatal transport error and tears down the
        # whole server connection instead of just skipping the optional
        # capability -- so an explicit, spec-correct 405 is required here.
        body = b""
        self.send_response(405)
        self.send_header("Allow", "POST")
        self.send_header("Content-Length", "0")
        self.end_headers()
        if body:
            self.wfile.write(body)
    def do_GET(self) -> None:
        self.method_not_allowed()
    def do_DELETE(self) -> None:
        self.method_not_allowed()
    def do_POST(self) -> None:
        if self.path != "/mcp": self.reply(404, {"error": "not_found"}); return
        try:
            request = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            method, request_id = request.get("method"), request.get("id")
            extra_headers: dict[str, str] = {}
            if method == "initialize":
                # Streamable HTTP MCP transport requires a session id on the
                # initialize response; a compliant client otherwise has no
                # session to carry on subsequent requests and stalls/times out
                # instead of ever sending tools/list or tools/call.
                extra_headers["Mcp-Session-Id"] = str(uuid.uuid4())
                response = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}, "serverInfo": {"name": "CotS Host Controller", "version": "1.0"}}
            elif method == "notifications/initialized":
                # A JSON-RPC notification has no id and expects no JSON-RPC
                # result, but the client is still waiting on an HTTP response
                # to this POST; the spec's contract for a received
                # notification is an empty 202, not silence (silence just
                # hangs the client until its own transport timeout).
                self.send_response(202); self.send_header("Content-Length", "0"); self.end_headers()
                return
            elif method == "tools/list": response = {"tools": [{"name": name, "description": description, "inputSchema": {"type": "object", "properties": {"agent_id": {"type": "string"}, "timeout_seconds": {"type": "integer"}}}} for name, (description, _) in TOOLS.items()]}
            elif method == "tools/call":
                params = request.get("params", {}); name = params.get("name"); arguments = params.get("arguments", {})
                if name not in TOOLS: raise ValueError("unknown_fixed_tool")
                response = {"content": [{"type": "text", "text": json.dumps(TOOLS[name][1](arguments))}]}
            else: raise ValueError("method_not_found")
            self.reply(200, {"jsonrpc": "2.0", "id": request_id, "result": response}, extra_headers)
        except Exception as error:
            self.reply(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32602, "message": str(error)}})


if __name__ == "__main__":
    print(f"CotS Host MCP listening only on http://{HOST}:{PORT}/mcp", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
