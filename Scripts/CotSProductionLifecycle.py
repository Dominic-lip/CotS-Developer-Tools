#!/usr/bin/env python3
"""Fixed, auditable lifecycle bridge for the production CotS UE project.

This is intentionally *not* an arbitrary shell/filesystem endpoint.  Every
operation targets the fixed production project at ``C:\\Dev\\CotS`` and accepts
only bounded task/file inputs.  TASK-015 may bootstrap the production project;
TASK-100..TASK-115 may later use the same bridge within their explicit task
scope.  Shardlands is never writable through this adapter.
"""
from __future__ import annotations

import argparse
import ctypes
import http.client
import json
import os
import re
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
COTS_STATE = REPO / ".cots"
MANIFEST_DIR = COTS_STATE / "production-manifests"
STATE_FILE = COTS_STATE / "production-lifecycle.local.json"
PRODUCTION = Path(r"C:\Dev\CotS")
PROJECT = PRODUCTION / "CotS.uproject"
ENGINE = Path(os.environ.get("COTS_UE_ROOT", r"C:\Program Files\Epic Games\UE_5.8"))
EDITOR = ENGINE / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe"
EDITOR_CMD = ENGINE / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe"
BUILD_BAT = ENGINE / "Engine" / "Build" / "BatchFiles" / "Build.bat"
MCP_HOST, MCP_PORT = "127.0.0.1", 8000
NETWORKED_AUTOMATION_TEST = "CotS.Runtime.NetworkProbe.TwoParticipantLifecycle"
MAX_MANIFEST_FILES = 100
MAX_TEXT_BYTES = 2 * 1024 * 1024
ALLOWED_TASKS = {"TASK-015", *(f"TASK-{n}" for n in range(100, 116))}
ALLOWED_TEXT_SUFFIXES = {
    ".h", ".hpp", ".cpp", ".c", ".cs", ".ini", ".json", ".md", ".txt",
    ".uproject", ".uplugin", ".xml", ".yml", ".yaml", ".toml", ".cfg",
    ".bat", ".cmd", ".ps1", ".py", ".gitignore",
}
ENTRY_MAP_SCRIPT_PATH = "Content/Python/TASK_015_create_entry_map.py"
ENTRY_MAP_SCRIPT = (
    "import unreal\n\n"
    "ENTRY_MAP = '/Game/Maps/CotS_Entry'\n"
    "level_editor = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)\n"
    "if not unreal.EditorAssetLibrary.does_asset_exist(ENTRY_MAP):\n"
    "    if not level_editor.new_level(ENTRY_MAP):\n"
    "        raise RuntimeError(f'Unable to create {ENTRY_MAP}')\n"
    "if not unreal.EditorAssetLibrary.does_asset_exist(ENTRY_MAP):\n"
    "    raise RuntimeError(f'{ENTRY_MAP} was not saved')\n"
    "unreal.log(f'TASK-015 entry map ready: {ENTRY_MAP}')\n"
)
ENTRY_MAP_SMOKE_SCRIPT_PATH = "Content/Python/TASK_015_smoke_entry_map.py"
ENTRY_MAP_SMOKE_SCRIPT = (
    "import unreal\n\n"
    "ENTRY_MAP = '/Game/Maps/CotS_Entry'\n"
    "if not unreal.EditorAssetLibrary.does_asset_exist(ENTRY_MAP):\n"
    "    raise RuntimeError(f'Missing {ENTRY_MAP}')\n"
    "level_editor = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)\n"
    "if not level_editor.load_level(ENTRY_MAP):\n"
    "    raise RuntimeError(f'Unable to load {ENTRY_MAP}')\n"
    "unreal.log(f'TASK-015 smoke loaded: {ENTRY_MAP}')\n"
)
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0


class Refused(RuntimeError):
    pass


def _read_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else dict(default or {})
    except (OSError, json.JSONDecodeError, TypeError):
        return dict(default or {})


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _write_state(**fields: Any) -> None:
    value = _read_json(STATE_FILE, {})
    value.update(fields)
    value["updated_at"] = time.time()
    _atomic_json(STATE_FILE, value)


def _pid_live(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _mcp_ready() -> bool:
    try:
        with socket.create_connection((MCP_HOST, MCP_PORT), timeout=0.5):
            return True
    except OSError:
        return False


def _safe_relpath(value: str) -> Path:
    raw = str(value or "").replace("\\", "/").strip()
    if not raw or raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise Refused("production path must be a non-empty relative path")
    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise Refused("production path traversal is forbidden")
    if any(part.lower() == ".git" for part in parts):
        raise Refused("direct .git writes are forbidden")
    candidate = (PRODUCTION / Path(*parts)).resolve()
    root = PRODUCTION.resolve()
    if candidate == root or root not in candidate.parents:
        raise Refused("production path escaped the fixed root")
    suffix = candidate.suffix.lower() or (".gitignore" if candidate.name == ".gitignore" else "")
    if suffix not in ALLOWED_TEXT_SUFFIXES:
        raise Refused(f"unsupported production text file type: {candidate.name}")
    return candidate


def _safe_completion_path(value: str) -> Path:
    """Permit the one binary asset created by TASK-015's fixed map operation."""
    normalized = str(value or "").replace("\\", "/")
    if normalized == "Content/Maps/CotS_Entry.umap":
        return (PRODUCTION / normalized).resolve()
    return _safe_relpath(value)


def _run(command: list[str], *, cwd: Path, timeout: int = 900, creationflags: int = 0) -> dict[str, Any]:
    started = time.monotonic()
    completed = subprocess.run(
        command, cwd=cwd, text=True, capture_output=True, timeout=timeout,
        check=False, creationflags=creationflags,
    )
    output = (completed.stdout + completed.stderr)[-20000:]
    return {
        "exit_code": completed.returncode,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "output_tail": output,
    }


def _git(*args: str, timeout: int = 60) -> dict[str, Any]:
    return _run(["git", *args], cwd=PRODUCTION, timeout=timeout, creationflags=CREATE_NO_WINDOW)


def _bootstrap_files() -> dict[str, str]:
    return {
        "CotS.uproject": json.dumps({
            "FileVersion": 3,
            "EngineAssociation": "5.8",
            "Category": "Games",
            "Description": "Chronicles of the Sigilarium production project",
            "Modules": [{"Name": "CotS", "Type": "Runtime", "LoadingPhase": "Default"}],
            "Plugins": [
                {"Name": "ModelContextProtocol", "Enabled": True},
                {"Name": "AllToolsets", "Enabled": True},
            ],
        }, indent=2) + "\n",
        ".gitignore": "Binaries/\nDerivedDataCache/\nIntermediate/\nSaved/\n.vs/\n*.sln\n*.VC.db\n",
        "README.md": "# Chronicles of the Sigilarium\n\nProduction Unreal Engine 5.8 project.\n",
        "AGENTS.md": (
            "# CotS Production Project Rules\n\n"
            "This is the production Chronicles of the Sigilarium Unreal project.\n"
            "Only the currently scheduled TASK-015 or TASK-100..TASK-115 may mutate this tree, and only within that task's explicit scope.\n"
            "C:\\Dev\\Shardlands is donor/reference and read-only.\n"
            "Use the fixed DeveloperTools production lifecycle adapter for host lifecycle/build/Git operations.\n"
            "Do not use destructive Git operations, force-push, broad clean/reset, or arbitrary process control.\n"
            "Inspect before mutation, validate after mutation, and record durable acceptance evidence.\n"
        ),
        "Config/DefaultEngine.ini": (
            "[/Script/EngineSettings.GameMapsSettings]\n"
            "GameDefaultMap=/Game/Maps/CotS_Entry\n"
            "EditorStartupMap=/Game/Maps/CotS_Entry\n\n"
            "[/Script/Engine.Engine]\n"
            "+ActiveGameNameRedirects=(OldGameName=\"TP_Blank\",NewGameName=\"/Script/CotS\")\n"
        ),
        "Config/DefaultGame.ini": (
            "[/Script/EngineSettings.GeneralProjectSettings]\n"
            "ProjectID=EAD69DA34A6B4D57A7E49C6C8B99C015\n"
            "ProjectName=Chronicles of the Sigilarium\n"
            "Description=Chronicles of the Sigilarium\n"
        ),
        "Config/DefaultEditorPerProjectUserSettings.ini": (
            "[/Script/ModelContextProtocolEngine.ModelContextProtocolSettings]\n"
            "ServerUrlPath=/mcp\n"
            "bAutoStartServer=True\n"
        ),
        "Source/CotS.Target.cs": (
            "using UnrealBuildTool;\n\n"
            "public class CotSTarget : TargetRules\n"
            "{\n"
            "    public CotSTarget(TargetInfo Target) : base(Target)\n"
            "    {\n"
            "        Type = TargetType.Game;\n"
            "        DefaultBuildSettings = BuildSettingsVersion.V7;\n"
            "        IncludeOrderVersion = EngineIncludeOrderVersion.Latest;\n"
            "        ExtraModuleNames.Add(\"CotS\");\n"
            "    }\n"
            "}\n"
        ),
        "Source/CotSEditor.Target.cs": (
            "using UnrealBuildTool;\n\n"
            "public class CotSEditorTarget : TargetRules\n"
            "{\n"
            "    public CotSEditorTarget(TargetInfo Target) : base(Target)\n"
            "    {\n"
            "        Type = TargetType.Editor;\n"
            "        DefaultBuildSettings = BuildSettingsVersion.V7;\n"
            "        IncludeOrderVersion = EngineIncludeOrderVersion.Latest;\n"
            "        ExtraModuleNames.Add(\"CotS\");\n"
            "    }\n"
            "}\n"
        ),
        "Source/CotSServer.Target.cs": (
            "using UnrealBuildTool;\n\n"
            "public class CotSServerTarget : TargetRules\n"
            "{\n"
            "    public CotSServerTarget(TargetInfo Target) : base(Target)\n"
            "    {\n"
            "        Type = TargetType.Server;\n"
            "        DefaultBuildSettings = BuildSettingsVersion.V7;\n"
            "        IncludeOrderVersion = EngineIncludeOrderVersion.Latest;\n"
            "        ExtraModuleNames.Add(\"CotS\");\n"
            "    }\n"
            "}\n"
        ),
        "Source/CotS/CotS.Build.cs": (
            "using UnrealBuildTool;\n\n"
            "public class CotS : ModuleRules\n"
            "{\n"
            "    public CotS(ReadOnlyTargetRules Target) : base(Target)\n"
            "    {\n"
            "        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;\n"
            "        PublicDependencyModuleNames.AddRange(new string[] { \"Core\", \"CoreUObject\", \"Engine\", \"InputCore\" });\n"
            "    }\n"
            "}\n"
        ),
        "Source/CotS/CotS.h": "#pragma once\n\n#include \"CoreMinimal.h\"\n",
        "Source/CotS/CotS.cpp": (
            "#include \"CotS.h\"\n"
            "#include \"Modules/ModuleManager.h\"\n\n"
            "IMPLEMENT_PRIMARY_GAME_MODULE(FDefaultGameModuleImpl, CotS, \"CotS\");\n"
        ),
    }


def bootstrap(*, initialize_git: bool = True) -> dict[str, Any]:
    PRODUCTION.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    existing: list[str] = []
    conflicts: list[str] = []
    for relative, content in _bootstrap_files().items():
        target = _safe_relpath(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            try:
                current = target.read_text(encoding="utf-8")
            except OSError:
                conflicts.append(relative)
                continue
            if current == content:
                existing.append(relative)
            else:
                conflicts.append(relative)
            continue
        target.write_text(content, encoding="utf-8", newline="\n")
        created.append(relative)
    git_result: dict[str, Any] | None = None
    if initialize_git and not (PRODUCTION / ".git").exists():
        git_result = _run(["git", "init", "-b", "main"], cwd=PRODUCTION, timeout=60, creationflags=CREATE_NO_WINDOW)
        if git_result["exit_code"] != 0:
            fallback = _run(["git", "init"], cwd=PRODUCTION, timeout=60, creationflags=CREATE_NO_WINDOW)
            if fallback["exit_code"] == 0:
                _git("branch", "-M", "main")
            git_result = fallback
    success = not conflicts and (git_result is None or git_result.get("exit_code") == 0)
    _write_state(last_operation="bootstrap", bootstrap_success=success, created=created, conflicts=conflicts)
    return {"success": success, "created": created, "existing": existing, "conflicts": conflicts, "git": git_result}


def _manifest_path(name: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}\.json", str(name or "")):
        raise Refused("manifest must be a simple .json filename")
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    return MANIFEST_DIR / name


def apply_manifest(name: str) -> dict[str, Any]:
    path = _manifest_path(name)
    value = _read_json(path)
    task = str(value.get("task") or "")
    files = value.get("files")
    if task not in ALLOWED_TASKS:
        raise Refused("manifest task is not authorized for production mutation")
    if not isinstance(files, list) or not files or len(files) > MAX_MANIFEST_FILES:
        raise Refused("manifest must contain 1..100 text files")
    planned: list[tuple[Path, str | None, str, str]] = []
    total = 0
    for entry in files:
        if not isinstance(entry, dict):
            raise Refused("manifest file entry must be an object")
        relative = str(entry.get("path") or "")
        content = entry.get("content")
        mode = str(entry.get("mode") or "upsert")
        if mode not in {"create", "upsert", "normalize_eof"}:
            raise Refused("manifest supports create, upsert, or normalize_eof only")
        target = _safe_relpath(relative)
        if mode == "normalize_eof":
            if content is not None or not target.exists():
                raise Refused("normalize_eof requires an existing file and no content")
            planned.append((target, None, relative, mode))
            continue
        if not isinstance(content, str):
            raise Refused("create/upsert manifest entries require text content")
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_TEXT_BYTES:
            raise Refused(f"manifest file too large: {relative}")
        total += len(encoded)
        if total > MAX_TEXT_BYTES * 4:
            raise Refused("manifest total text payload is too large")
        if mode == "create" and target.exists():
            raise Refused(f"create target already exists: {relative}")
        planned.append((target, content, relative, mode))
    changed: list[str] = []
    unchanged: list[str] = []
    for target, content, relative, mode in planned:
        target.parent.mkdir(parents=True, exist_ok=True)
        current = target.read_text(encoding="utf-8") if target.exists() else None
        if mode == "normalize_eof":
            content = (current or "").rstrip("\r\n") + "\n"
        if current == content:
            unchanged.append(relative)
            continue
        target.write_text(content, encoding="utf-8", newline="\n")
        changed.append(relative)
    _write_state(last_operation="apply-manifest", task=task, manifest=name, changed=changed)
    return {"success": True, "task": task, "manifest": name, "changed": changed, "unchanged": unchanged}


def status() -> dict[str, Any]:
    state = _read_json(STATE_FILE, {})
    pid = state.get("editor_pid")
    editor_running = _pid_live(pid)
    if not editor_running and pid:
        state["editor_pid"] = None
        state["editor_started_at"] = None
        _atomic_json(STATE_FILE, state)
    git = _git("status", "--porcelain=v1") if (PRODUCTION / ".git").exists() else None
    head = _git("rev-parse", "HEAD") if (PRODUCTION / ".git").exists() else None
    git_lines = [line for line in (git or {}).get("output_tail", "").splitlines() if line.strip()]
    return {
        "production_root": str(PRODUCTION),
        "project": str(PROJECT),
        "project_exists": PROJECT.is_file(),
        "git_initialized": (PRODUCTION / ".git").exists(),
        "git_clean": bool(git is not None and git.get("exit_code") == 0 and not git_lines),
        "git_dirty_paths": [line[3:] if len(line) > 3 else line for line in git_lines],
        "git_head": (head or {}).get("output_tail", "").strip() if head else None,
        "engine_available": EDITOR.is_file() and EDITOR_CMD.is_file() and BUILD_BAT.is_file(),
        "editor_running": editor_running,
        "editor_pid": pid if editor_running else None,
        "mcp_ready": _mcp_ready() if editor_running else False,
        "state": state,
    }


def mcp_diagnostics() -> dict[str, Any]:
    descriptor = _read_json(PROJECT, {}) if PROJECT.is_file() else {}
    plugins = descriptor.get("Plugins") if isinstance(descriptor.get("Plugins"), list) else []
    enabled_plugins = sorted(
        str(plugin.get("Name")) for plugin in plugins
        if isinstance(plugin, dict) and plugin.get("Enabled")
    )
    settings = PRODUCTION / "Config" / "DefaultEditorPerProjectUserSettings.ini"
    settings_text = settings.read_text(encoding="utf-8", errors="replace") if settings.is_file() else ""
    log_path = PRODUCTION / "Saved" / "Logs" / "CotS.log"
    relevant_log_lines: list[str] = []
    if log_path.is_file():
        try:
            relevant_log_lines = [
                line for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                if "mcp" in line.lower() or "modelcontext" in line.lower()
            ][-80:]
        except OSError:
            relevant_log_lines = ["<unable to read production log>"]
    return {
        "success": True,
        "project_exists": PROJECT.is_file(),
        "mcp_ready": _mcp_ready(),
        "enabled_plugins": enabled_plugins,
        "settings_exists": settings.is_file(),
        "server_url_path": next((line.split("=", 1)[1] for line in settings_text.splitlines() if line.startswith("ServerUrlPath=")), None),
        "auto_start_server": "bAutoStartServer=True" in settings_text.splitlines(),
        "log_path": str(log_path),
        "relevant_log_lines": relevant_log_lines,
    }


def mcp_toolset_diagnostics() -> dict[str, Any]:
    """Read the fixed native MCP registry; this never dispatches a project mutation."""
    if not _mcp_ready():
        return {"success": False, "error": "production_unreal_mcp_not_ready"}
    connection = http.client.HTTPConnection(MCP_HOST, MCP_PORT, timeout=8)
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    try:
        initialize = {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "CotS Production Lifecycle", "version": "1.0"}},
        }
        connection.request("POST", "/mcp", body=json.dumps(initialize), headers=headers)
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        session_id = response.getheader("Mcp-Session-Id")
        if response.status != 200 or not session_id:
            return {"success": False, "error": "production_unreal_mcp_initialize_failed"}
        protocol_version = payload.get("result", {}).get("protocolVersion", "2025-11-25")
        session_headers = {**headers, "Mcp-Session-Id": session_id, "Mcp-Protocol-Version": protocol_version}
        connection.request("POST", "/mcp", body=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}), headers=session_headers)
        initialized = connection.getresponse()
        initialized.read()
        if initialized.status not in (200, 202):
            return {"success": False, "error": "production_unreal_mcp_initialized_notification_failed"}
        request = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "list_toolsets", "arguments": {}}}
        connection.request("POST", "/mcp", body=json.dumps(request), headers=session_headers)
        response = connection.getresponse()
        tool_payload = json.loads(response.read().decode("utf-8"))
        if response.status != 200 or "error" in tool_payload:
            return {"success": False, "error": "production_unreal_mcp_list_toolsets_failed", "transport": tool_payload}
        content = tool_payload.get("result", {}).get("content", [])
        text = content[0].get("text", "") if content and isinstance(content[0], dict) else ""
        return {"success": True, "toolsets": text[:20000]}
    finally:
        connection.close()


def mcp_meta_tools() -> dict[str, Any]:
    """Return only the fixed endpoint's MCP tool schemas for native-tool discovery."""
    if not _mcp_ready():
        return {"success": False, "error": "production_unreal_mcp_not_ready"}
    connection = http.client.HTTPConnection(MCP_HOST, MCP_PORT, timeout=8)
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    try:
        initialize = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "CotS Production Lifecycle", "version": "1.0"}}}
        connection.request("POST", "/mcp", body=json.dumps(initialize), headers=headers)
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        session_id = response.getheader("Mcp-Session-Id")
        if response.status != 200 or not session_id:
            return {"success": False, "error": "production_unreal_mcp_initialize_failed"}
        protocol_version = payload.get("result", {}).get("protocolVersion", "2025-11-25")
        session_headers = {**headers, "Mcp-Session-Id": session_id, "Mcp-Protocol-Version": protocol_version}
        connection.request("POST", "/mcp", body=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}), headers=session_headers)
        initialized = connection.getresponse()
        initialized.read()
        if initialized.status not in (200, 202):
            return {"success": False, "error": "production_unreal_mcp_initialized_notification_failed"}
        connection.request("POST", "/mcp", body=json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}), headers=session_headers)
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        if response.status != 200 or "error" in payload:
            return {"success": False, "error": "production_unreal_mcp_tools_list_failed", "transport": payload}
        return {"success": True, "tools": payload.get("result", {}).get("tools", [])}
    finally:
        connection.close()


def mcp_map_tool_diagnostics() -> dict[str, Any]:
    """Describe only the native SceneTools and AssetTools needed for TASK-015 map evidence."""
    if not _mcp_ready():
        return {"success": False, "error": "production_unreal_mcp_not_ready"}
    connection = http.client.HTTPConnection(MCP_HOST, MCP_PORT, timeout=8)
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    try:
        initialize = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "CotS Production Lifecycle", "version": "1.0"}}}
        connection.request("POST", "/mcp", body=json.dumps(initialize), headers=headers)
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        session_id = response.getheader("Mcp-Session-Id")
        if response.status != 200 or not session_id:
            return {"success": False, "error": "production_unreal_mcp_initialize_failed"}
        protocol_version = payload.get("result", {}).get("protocolVersion", "2025-11-25")
        session_headers = {**headers, "Mcp-Session-Id": session_id, "Mcp-Protocol-Version": protocol_version}
        connection.request("POST", "/mcp", body=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}), headers=session_headers)
        initialized = connection.getresponse()
        initialized.read()
        if initialized.status not in (200, 202):
            return {"success": False, "error": "production_unreal_mcp_initialized_notification_failed"}
        toolsets: dict[str, list[dict[str, Any]]] = {}
        requested_toolsets = (
            ("EditorToolset.EditorAppToolset", ("level", "save", "new", "map", "console")),
            ("editor_toolset.toolsets.scene.SceneTools", ("level", "save")),
            ("editor_toolset.toolsets.asset.AssetTools", ("save", "create_folder", "exists")),
            ("editor_toolset.toolsets.programmatic.ProgrammaticToolset", ("execute", "environment")),
            ("SlateInspectorToolset.SlateInspectorToolset", ("observe", "snapshot", "click", "type", "key", "text")),
        )
        for request_id, (toolset_name, keywords) in enumerate(requested_toolsets, start=2):
            request = {"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": {"name": "describe_toolset", "arguments": {"toolset_name": toolset_name}}}
            connection.request("POST", "/mcp", body=json.dumps(request), headers=session_headers)
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
            if response.status != 200 or "error" in payload:
                return {"success": False, "error": "production_unreal_mcp_describe_toolset_failed", "toolset": toolset_name, "transport": payload}
            content = payload.get("result", {}).get("content", [])
            text = content[0].get("text", "") if content and isinstance(content[0], dict) else ""
            try:
                detail = json.loads(text)
                matching_tools = [
                    tool for tool in detail.get("tools", [])
                    if any(keyword in (str(tool.get("name", "")) + " " + str(tool.get("description", ""))).lower() for keyword in keywords)
                ]
                toolsets[toolset_name] = (
                    [{"name": tool.get("name", ""), "description": tool.get("description", "")} for tool in matching_tools]
                    if toolset_name == "EditorToolset.EditorAppToolset"
                    else matching_tools
                )
            except json.JSONDecodeError:
                toolsets[toolset_name] = []
        environment_request = {
            "jsonrpc": "2.0", "id": 10, "method": "tools/call",
            "params": {"name": "call_tool", "arguments": {
                "toolset_name": "editor_toolset.toolsets.programmatic.ProgrammaticToolset",
                "tool_name": "get_execution_environment", "arguments": {},
            }},
        }
        connection.request("POST", "/mcp", body=json.dumps(environment_request), headers=session_headers)
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        if response.status != 200 or "error" in payload:
            return {"success": False, "error": "production_unreal_mcp_programmatic_environment_failed", "transport": payload}
        content = payload.get("result", {}).get("content", [])
        environment = content[0].get("text", "") if content and isinstance(content[0], dict) else ""
        return {"success": True, "toolsets": toolsets, "programmatic_environment": environment[:20000]}
    finally:
        connection.close()


def mcp_slate_snapshot() -> dict[str, Any]:
    """Return the live production editor's native Slate accessibility snapshot."""
    if not _mcp_ready():
        return {"success": False, "error": "production_unreal_mcp_not_ready"}
    connection = http.client.HTTPConnection(MCP_HOST, MCP_PORT, timeout=8)
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    try:
        initialize = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "CotS Production Lifecycle", "version": "1.0"}}}
        connection.request("POST", "/mcp", body=json.dumps(initialize), headers=headers)
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        session_id = response.getheader("Mcp-Session-Id")
        if response.status != 200 or not session_id:
            return {"success": False, "error": "production_unreal_mcp_initialize_failed"}
        protocol_version = payload.get("result", {}).get("protocolVersion", "2025-11-25")
        session_headers = {**headers, "Mcp-Session-Id": session_id, "Mcp-Protocol-Version": protocol_version}
        connection.request("POST", "/mcp", body=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}), headers=session_headers)
        initialized = connection.getresponse()
        initialized.read()
        if initialized.status not in (200, 202):
            return {"success": False, "error": "production_unreal_mcp_initialized_notification_failed"}
        request = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "call_tool", "arguments": {"toolset_name": "SlateInspectorToolset.SlateInspectorToolset", "tool_name": "Snapshot", "arguments": {"ref": "", "maxDepth": 8}}}}
        connection.request("POST", "/mcp", body=json.dumps(request), headers=session_headers)
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        if response.status != 200 or "error" in payload:
            return {"success": False, "error": "production_unreal_mcp_slate_snapshot_failed", "transport": payload}
        content = payload.get("result", {}).get("content", [])
        snapshot = content[0].get("text", "") if content and isinstance(content[0], dict) else ""
        return {"success": True, "snapshot": snapshot[:30000]}
    finally:
        connection.close()


def mcp_slate_observe_main() -> dict[str, Any]:
    """Observe and snapshot the main production editor window for UI discovery."""
    if not _mcp_ready():
        return {"success": False, "error": "production_unreal_mcp_not_ready"}
    connection = http.client.HTTPConnection(MCP_HOST, MCP_PORT, timeout=8)
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    try:
        initialize = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "CotS Production Lifecycle", "version": "1.0"}}}
        connection.request("POST", "/mcp", body=json.dumps(initialize), headers=headers)
        response = connection.getresponse(); payload = json.loads(response.read().decode("utf-8")); session_id = response.getheader("Mcp-Session-Id")
        if response.status != 200 or not session_id:
            return {"success": False, "error": "production_unreal_mcp_initialize_failed"}
        session_headers = {**headers, "Mcp-Session-Id": session_id, "Mcp-Protocol-Version": payload.get("result", {}).get("protocolVersion", "2025-11-25")}
        connection.request("POST", "/mcp", body=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}), headers=session_headers)
        initialized = connection.getresponse(); initialized.read()
        if initialized.status not in (200, 202):
            return {"success": False, "error": "production_unreal_mcp_initialized_notification_failed"}
        for request_id, tool_name, arguments in ((2, "Observe", {"ref": "w1", "maxDepth": 20}), (3, "Snapshot", {"ref": "w1", "maxDepth": 20})):
            request = {"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": {"name": "call_tool", "arguments": {"toolset_name": "SlateInspectorToolset.SlateInspectorToolset", "tool_name": tool_name, "arguments": arguments}}}
            connection.request("POST", "/mcp", body=json.dumps(request), headers=session_headers)
            response = connection.getresponse(); payload = json.loads(response.read().decode("utf-8"))
            if response.status != 200 or "error" in payload:
                return {"success": False, "error": "production_unreal_mcp_slate_observe_main_failed", "tool": tool_name, "transport": payload}
            content = payload.get("result", {}).get("content", [])
            if tool_name == "Snapshot":
                snapshot = content[0].get("text", "") if content and isinstance(content[0], dict) else ""
        return {"success": True, "snapshot": snapshot[:50000]}
    finally:
        connection.close()


def mcp_slate_open_file_menu() -> dict[str, Any]:
    """Open the observed main editor File menu and return its native snapshot."""
    if not _mcp_ready():
        return {"success": False, "error": "production_unreal_mcp_not_ready"}
    connection = http.client.HTTPConnection(MCP_HOST, MCP_PORT, timeout=8)
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    try:
        initialize = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "CotS Production Lifecycle", "version": "1.0"}}}
        connection.request("POST", "/mcp", body=json.dumps(initialize), headers=headers)
        response = connection.getresponse(); payload = json.loads(response.read().decode("utf-8")); session_id = response.getheader("Mcp-Session-Id")
        if response.status != 200 or not session_id:
            return {"success": False, "error": "production_unreal_mcp_initialize_failed"}
        session_headers = {**headers, "Mcp-Session-Id": session_id, "Mcp-Protocol-Version": payload.get("result", {}).get("protocolVersion", "2025-11-25")}
        connection.request("POST", "/mcp", body=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}), headers=session_headers)
        initialized = connection.getresponse(); initialized.read()
        if initialized.status not in (200, 202):
            return {"success": False, "error": "production_unreal_mcp_initialized_notification_failed"}
        for request_id, tool_name, arguments in ((2, "Click", {"ref": "m1"}), (3, "Snapshot", {"ref": "", "maxDepth": 12})):
            request = {"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": {"name": "call_tool", "arguments": {"toolset_name": "SlateInspectorToolset.SlateInspectorToolset", "tool_name": tool_name, "arguments": arguments}}}
            connection.request("POST", "/mcp", body=json.dumps(request), headers=session_headers)
            response = connection.getresponse(); payload = json.loads(response.read().decode("utf-8"))
            if response.status != 200 or "error" in payload:
                return {"success": False, "error": "production_unreal_mcp_file_menu_failed", "tool": tool_name, "transport": payload}
            content = payload.get("result", {}).get("content", [])
            if tool_name == "Snapshot":
                snapshot = content[0].get("text", "") if content and isinstance(content[0], dict) else ""
        return {"success": True, "snapshot": snapshot[:30000]}
    finally:
        connection.close()


def mcp_slate_inspect_file_menu() -> dict[str, Any]:
    """Observe the already-open native File menu and return its actionable entries."""
    if not _mcp_ready():
        return {"success": False, "error": "production_unreal_mcp_not_ready"}
    connection = http.client.HTTPConnection(MCP_HOST, MCP_PORT, timeout=8)
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    try:
        initialize = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "CotS Production Lifecycle", "version": "1.0"}}}
        connection.request("POST", "/mcp", body=json.dumps(initialize), headers=headers)
        response = connection.getresponse(); payload = json.loads(response.read().decode("utf-8")); session_id = response.getheader("Mcp-Session-Id")
        if response.status != 200 or not session_id:
            return {"success": False, "error": "production_unreal_mcp_initialize_failed"}
        session_headers = {**headers, "Mcp-Session-Id": session_id, "Mcp-Protocol-Version": payload.get("result", {}).get("protocolVersion", "2025-11-25")}
        connection.request("POST", "/mcp", body=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}), headers=session_headers)
        initialized = connection.getresponse(); initialized.read()
        if initialized.status not in (200, 202):
            return {"success": False, "error": "production_unreal_mcp_initialized_notification_failed"}
        for request_id, tool_name, arguments in ((2, "Observe", {"ref": "w4", "maxDepth": 20}), (3, "Snapshot", {"ref": "w4", "maxDepth": 20})):
            request = {"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": {"name": "call_tool", "arguments": {"toolset_name": "SlateInspectorToolset.SlateInspectorToolset", "tool_name": tool_name, "arguments": arguments}}}
            connection.request("POST", "/mcp", body=json.dumps(request), headers=session_headers)
            response = connection.getresponse(); payload = json.loads(response.read().decode("utf-8"))
            if response.status != 200 or "error" in payload:
                return {"success": False, "error": "production_unreal_mcp_file_menu_inspection_failed", "tool": tool_name, "transport": payload}
            content = payload.get("result", {}).get("content", [])
            if tool_name == "Snapshot":
                snapshot = content[0].get("text", "") if content and isinstance(content[0], dict) else ""
        return {"success": True, "snapshot": snapshot[:30000]}
    finally:
        connection.close()


def mcp_slate_open_new_level_dialog() -> dict[str, Any]:
    """Open the native New Level dialog from the observed File menu."""
    if not _mcp_ready():
        return {"success": False, "error": "production_unreal_mcp_not_ready"}
    connection = http.client.HTTPConnection(MCP_HOST, MCP_PORT, timeout=8)
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    try:
        initialize = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "CotS Production Lifecycle", "version": "1.0"}}}
        connection.request("POST", "/mcp", body=json.dumps(initialize), headers=headers)
        response = connection.getresponse(); payload = json.loads(response.read().decode("utf-8")); session_id = response.getheader("Mcp-Session-Id")
        if response.status != 200 or not session_id:
            return {"success": False, "error": "production_unreal_mcp_initialize_failed"}
        session_headers = {**headers, "Mcp-Session-Id": session_id, "Mcp-Protocol-Version": payload.get("result", {}).get("protocolVersion", "2025-11-25")}
        connection.request("POST", "/mcp", body=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}), headers=session_headers)
        initialized = connection.getresponse(); initialized.read()
        if initialized.status not in (200, 202):
            return {"success": False, "error": "production_unreal_mcp_initialized_notification_failed"}
        for request_id, tool_name, arguments in ((2, "Click", {"ref": "g4"}), (3, "Snapshot", {"ref": "", "maxDepth": 12})):
            request = {"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": {"name": "call_tool", "arguments": {"toolset_name": "SlateInspectorToolset.SlateInspectorToolset", "tool_name": tool_name, "arguments": arguments}}}
            connection.request("POST", "/mcp", body=json.dumps(request), headers=session_headers)
            response = connection.getresponse(); payload = json.loads(response.read().decode("utf-8"))
            if response.status != 200 or "error" in payload:
                return {"success": False, "error": "production_unreal_mcp_new_level_dialog_failed", "tool": tool_name, "transport": payload}
            content = payload.get("result", {}).get("content", [])
            if tool_name == "Snapshot":
                snapshot = content[0].get("text", "") if content and isinstance(content[0], dict) else ""
        return {"success": True, "snapshot": snapshot[:30000]}
    finally:
        connection.close()


def mcp_inspect_entry_map() -> dict[str, Any]:
    """Inspect and load only TASK-015's canonical entry map through native MCP."""
    if not _mcp_ready():
        return {"success": False, "error": "production_unreal_mcp_not_ready"}
    connection = http.client.HTTPConnection(MCP_HOST, MCP_PORT, timeout=8)
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    try:
        initialize = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "CotS Production Lifecycle", "version": "1.0"}}}
        connection.request("POST", "/mcp", body=json.dumps(initialize), headers=headers)
        response = connection.getresponse(); payload = json.loads(response.read().decode("utf-8")); session_id = response.getheader("Mcp-Session-Id")
        if response.status != 200 or not session_id:
            return {"success": False, "error": "production_unreal_mcp_initialize_failed"}
        session_headers = {**headers, "Mcp-Session-Id": session_id, "Mcp-Protocol-Version": payload.get("result", {}).get("protocolVersion", "2025-11-25")}
        connection.request("POST", "/mcp", body=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}), headers=session_headers)
        initialized = connection.getresponse(); initialized.read()
        if initialized.status not in (200, 202):
            return {"success": False, "error": "production_unreal_mcp_initialized_notification_failed"}
        calls = (
            ("editor_toolset.toolsets.asset.AssetTools", "exists", {"path": "/Game/Maps/CotS_Entry"}),
            ("editor_toolset.toolsets.scene.SceneTools", "load_level", {"level_path": "/Game/Maps/CotS_Entry"}),
            ("editor_toolset.toolsets.scene.SceneTools", "get_current_level", {}),
        )
        results: list[str] = []
        for request_id, (toolset_name, tool_name, arguments) in enumerate(calls, start=2):
            request = {"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": {"name": "call_tool", "arguments": {"toolset_name": toolset_name, "tool_name": tool_name, "arguments": arguments}}}
            connection.request("POST", "/mcp", body=json.dumps(request), headers=session_headers)
            response = connection.getresponse(); payload = json.loads(response.read().decode("utf-8"))
            if response.status != 200 or "error" in payload:
                return {"success": False, "error": "production_unreal_mcp_entry_map_inspection_failed", "tool": tool_name, "transport": payload}
            content = payload.get("result", {}).get("content", [])
            results.append(content[0].get("text", "") if content and isinstance(content[0], dict) else "")
        return {"success": results[0] == '{"returnValue":true}' and "/Game/Maps/CotS_Entry" in results[2], "entry_map_exists": results[0], "loaded_level": results[2]}
    finally:
        connection.close()


def open_editor() -> dict[str, Any]:
    info = status()
    if info["editor_running"]:
        return {"success": True, "changed": False, **info}
    if not PROJECT.is_file() or not EDITOR.is_file():
        raise Refused("production project or UE 5.8 editor is missing")
    process = subprocess.Popen([str(EDITOR), str(PROJECT)], cwd=PRODUCTION, creationflags=NEW_PROCESS_GROUP)
    _write_state(editor_pid=process.pid, editor_started_at=time.time(), last_operation="open")
    return {"success": True, "changed": True, "editor_pid": process.pid, "mcp_url": f"http://{MCP_HOST}:{MCP_PORT}/mcp"}


def close_editor(timeout_seconds: int = 45) -> dict[str, Any]:
    info = status()
    pid = info.get("editor_pid")
    if not pid:
        return {"success": True, "changed": False, "editor_running": False}
    if os.name != "nt":
        raise Refused("production editor close is currently implemented only for Windows")
    user32 = ctypes.windll.user32
    sent: list[int] = []
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
        raise Refused("no top-level production editor window is available for graceful close")
    deadline = time.monotonic() + max(1, min(120, int(timeout_seconds)))
    while time.monotonic() < deadline:
        if not _pid_live(pid):
            _write_state(editor_pid=None, editor_started_at=None, last_operation="close")
            return {"success": True, "changed": True, "editor_running": False, "editor_pid": pid}
        time.sleep(0.5)
    raise Refused("production editor graceful close timed out")


def wait_mcp(timeout_seconds: int = 90) -> dict[str, Any]:
    deadline = time.monotonic() + max(1, min(180, int(timeout_seconds)))
    while time.monotonic() < deadline:
        if _mcp_ready():
            return {"success": True, "ready": True, "mcp_url": f"http://{MCP_HOST}:{MCP_PORT}/mcp"}
        time.sleep(0.5)
    return {"success": False, "ready": False, "error": "production_unreal_mcp_timeout"}


def build(target: str = "editor", timeout_seconds: int = 1800) -> dict[str, Any]:
    if target not in {"editor", "game", "server"}:
        raise Refused("build target must be editor, game, or server")
    info = status()
    if info.get("editor_running"):
        raise Refused("close the production editor before building")
    if not PROJECT.is_file() or not BUILD_BAT.is_file():
        raise Refused("production project or UE 5.8 Build.bat is missing")
    target_name = {"editor": "CotSEditor", "game": "CotS", "server": "CotSServer"}[target]
    result = _run(
        [
            str(BUILD_BAT), target_name, "Win64", "Development",
            f"-Project={PROJECT}", "-WaitMutex", "-NoHotReloadFromIDE",
        ],
        cwd=PRODUCTION,
        timeout=max(60, min(7200, int(timeout_seconds))),
        creationflags=CREATE_NO_WINDOW,
    )
    _write_state(last_operation="build", build_target=target, build_exit_code=result["exit_code"])
    return {"success": result["exit_code"] == 0, "target": target, **result}


def smoke(timeout_seconds: int = 300) -> dict[str, Any]:
    script = _safe_relpath(ENTRY_MAP_SMOKE_SCRIPT_PATH)
    if not PROJECT.is_file() or not EDITOR_CMD.is_file() or not script.is_file():
        raise Refused("production project, UnrealEditor-Cmd, or fixed smoke script is missing")
    if script.read_text(encoding="utf-8") != ENTRY_MAP_SMOKE_SCRIPT:
        raise Refused("fixed smoke script content does not match the audited TASK-015 operation")
    command = [
        str(EDITOR_CMD), str(PROJECT), "-run=PythonScriptCommandlet", f"-Script={script}",
        "-ini:EditorPerProjectUserSettings:[/Script/ModelContextProtocolEngine.ModelContextProtocolSettings]:bAutoStartServer=False",
        "-unattended", "-nop4", "-nosplash", "-NullRHI", "-NoSound",
    ]
    result = _run(command, cwd=PRODUCTION, timeout=max(30, min(1200, int(timeout_seconds))), creationflags=NEW_PROCESS_GROUP)
    _write_state(last_operation="smoke", smoke_exit_code=result["exit_code"])
    return {"success": result["exit_code"] == 0, **result}


def networked_automation(timeout_seconds: int = 300) -> dict[str, Any]:
    """Run TASK-101's exact two-worker UE network-automation test.

    The worker and controller command lines are deliberately fixed. This is
    not a general process launcher: it accepts no project, executable, test,
    address, or command-line input from the caller.
    """
    if status().get("editor_running"):
        raise Refused("close the production editor before running networked automation")
    if not PROJECT.is_file() or not EDITOR.is_file() or not EDITOR_CMD.is_file():
        raise Refused("production project or UE 5.8 editor executable is missing")

    session_id = str(uuid.uuid4())
    session_arg = f"-SessionId={session_id}"
    session_name_arg = "-SessionName=CotS-TASK101"

    mcp_override = "-ini:EditorPerProjectUserSettings:[/Script/ModelContextProtocolEngine.ModelContextProtocolSettings]:bAutoStartServer=False"
    worker_command = [
        str(EDITOR), str(PROJECT), "-game", "-messaging", "-Multiprocess",
        session_arg, session_name_arg, mcp_override,
        "-unattended", "-nop4", "-nosplash", "-NullRHI", "-NoSound",
    ]
    workers = [
        subprocess.Popen(worker_command, cwd=PRODUCTION, creationflags=NEW_PROCESS_GROUP),
        subprocess.Popen(worker_command, cwd=PRODUCTION, creationflags=NEW_PROCESS_GROUP),
    ]
    _write_state(
        last_operation="networked-automation-starting",
        networked_automation_worker_pids=[worker.pid for worker in workers],
    )
    try:
        time.sleep(5)
        controller_command = [
            str(EDITOR_CMD), str(PROJECT), "-messaging", "-Multiprocess",
            session_arg, session_name_arg, mcp_override,
            f"-ExecCmds=Automation RunTests {NETWORKED_AUTOMATION_TEST};Quit",
            "-unattended", "-nop4", "-nosplash", "-NullRHI", "-NoSound",
        ]
        result = _run(
            controller_command,
            cwd=PRODUCTION,
            timeout=max(60, min(1200, int(timeout_seconds))),
            creationflags=NEW_PROCESS_GROUP,
        )
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.terminate()
        for worker in workers:
            try:
                worker.wait(timeout=30)
            except subprocess.TimeoutExpired:
                pass

    workers_cleaned = all(worker.poll() is not None for worker in workers)
    successful = workers_cleaned and result["exit_code"] == 0 and "Automation Test Failed" not in result["output_tail"]
    _write_state(
        last_operation="networked-automation",
        networked_automation_exit_code=result["exit_code"],
        networked_automation_test=NETWORKED_AUTOMATION_TEST,
        networked_automation_worker_pids=[] if workers_cleaned else [worker.pid for worker in workers if worker.poll() is None],
    )
    return {
        "success": successful,
        "test": NETWORKED_AUTOMATION_TEST,
        "worker_count": 2,
        "workers_cleaned": workers_cleaned,
        **result,
    }


def create_entry_map(timeout_seconds: int = 300) -> dict[str, Any]:
    """Create only TASK-015's canonical entry map through UE's Python commandlet."""
    info = status()
    if info.get("editor_running"):
        raise Refused("close the production editor before creating the entry map")
    script = _safe_relpath(ENTRY_MAP_SCRIPT_PATH)
    if not PROJECT.is_file() or not EDITOR_CMD.is_file() or not script.is_file():
        raise Refused("production project, UnrealEditor-Cmd, or fixed entry-map script is missing")
    if script.read_text(encoding="utf-8") != ENTRY_MAP_SCRIPT:
        raise Refused("fixed entry-map script content does not match the audited TASK-015 operation")
    result = _run(
        [str(EDITOR_CMD), str(PROJECT), "-run=PythonScriptCommandlet", f"-Script={script}", "-unattended", "-nop4", "-nosplash", "-NullRHI", "-NoSound"],
        cwd=PRODUCTION,
        timeout=max(30, min(1200, int(timeout_seconds))),
        creationflags=NEW_PROCESS_GROUP,
    )
    entry_map = PRODUCTION / "Content" / "Maps" / "CotS_Entry.umap"
    verified = result["exit_code"] == 0 and entry_map.is_file()
    _write_state(last_operation="create-entry-map", entry_map_exists=entry_map.is_file(), entry_map_exit_code=result["exit_code"])
    return {"success": verified, "entry_map": "/Game/Maps/CotS_Entry", "entry_map_exists": entry_map.is_file(), **result}


def git_complete(message: str, files: list[str], *, push: bool = False) -> dict[str, Any]:
    if not (PRODUCTION / ".git").exists():
        raise Refused("production Git repository is not initialized")
    message = " ".join(str(message or "").split())
    if not message or len(message) > 180:
        raise Refused("commit message must be 1..180 characters")
    requested: list[str] = []
    for value in files:
        target = _safe_completion_path(value)
        if not target.exists():
            raise Refused(f"cannot stage missing file: {value}")
        requested.append(target.relative_to(PRODUCTION.resolve()).as_posix())
    if not requested:
        raise Refused("at least one exact production file is required")
    staged = _git("diff", "--cached", "--name-only")
    existing = sorted(line.strip() for line in staged.get("output_tail", "").splitlines() if line.strip())
    expected = sorted(set(requested))
    if existing and existing != expected:
        raise Refused("pre-existing staged production files differ from requested completion set")
    added = _git("add", "--", *expected)
    if added["exit_code"] != 0:
        return {"success": False, "step": "add", **added}
    check = _git("diff", "--cached", "--check")
    if check["exit_code"] != 0:
        return {"success": False, "step": "diff-check", **check}
    quiet = _git("diff", "--cached", "--quiet")
    if quiet["exit_code"] == 0:
        return {"success": False, "step": "commit", "error": "no staged changes"}
    committed = _git("commit", "-m", message, timeout=120)
    if committed["exit_code"] != 0:
        return {"success": False, "step": "commit", **committed}
    result: dict[str, Any] = {"success": True, "files": expected, "commit": committed}
    if push:
        remotes = _git("remote")
        if "origin" not in remotes.get("output_tail", "").split():
            return {**result, "success": False, "step": "push", "error": "production repository has no origin remote"}
        pushed = _git("push", "origin", "HEAD:main", timeout=180)
        result["push"] = pushed
        result["success"] = pushed["exit_code"] == 0
    _write_state(last_operation="git-complete", last_commit_message=message)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    sub.add_parser("status")
    sub.add_parser("mcp-diagnostics")
    sub.add_parser("mcp-toolset-diagnostics")
    sub.add_parser("mcp-meta-tools")
    sub.add_parser("mcp-map-tool-diagnostics")
    sub.add_parser("mcp-slate-snapshot")
    sub.add_parser("mcp-slate-observe-main")
    sub.add_parser("mcp-slate-open-file-menu")
    sub.add_parser("mcp-slate-inspect-file-menu")
    sub.add_parser("mcp-slate-open-new-level-dialog")
    sub.add_parser("mcp-inspect-entry-map")
    sub.add_parser("bootstrap")
    manifest = sub.add_parser("apply-manifest"); manifest.add_argument("manifest")
    build_parser = sub.add_parser("build"); build_parser.add_argument("--target", choices=("editor", "game", "server"), default="editor"); build_parser.add_argument("--timeout", type=int, default=1800)
    smoke_parser = sub.add_parser("smoke"); smoke_parser.add_argument("--timeout", type=int, default=300)
    network_parser = sub.add_parser("networked-automation"); network_parser.add_argument("--timeout", type=int, default=300)
    map_parser = sub.add_parser("create-entry-map"); map_parser.add_argument("--timeout", type=int, default=300)
    sub.add_parser("open")
    close_parser = sub.add_parser("close"); close_parser.add_argument("--timeout", type=int, default=45)
    wait_parser = sub.add_parser("wait-mcp"); wait_parser.add_argument("--timeout", type=int, default=90)
    complete = sub.add_parser("git-complete"); complete.add_argument("--message", required=True); complete.add_argument("--push", action="store_true"); complete.add_argument("files", nargs="+")
    args = parser.parse_args()
    try:
        if args.operation == "status": value = status()
        elif args.operation == "mcp-diagnostics": value = mcp_diagnostics()
        elif args.operation == "mcp-toolset-diagnostics": value = mcp_toolset_diagnostics()
        elif args.operation == "mcp-meta-tools": value = mcp_meta_tools()
        elif args.operation == "mcp-map-tool-diagnostics": value = mcp_map_tool_diagnostics()
        elif args.operation == "mcp-slate-snapshot": value = mcp_slate_snapshot()
        elif args.operation == "mcp-slate-observe-main": value = mcp_slate_observe_main()
        elif args.operation == "mcp-slate-open-file-menu": value = mcp_slate_open_file_menu()
        elif args.operation == "mcp-slate-inspect-file-menu": value = mcp_slate_inspect_file_menu()
        elif args.operation == "mcp-slate-open-new-level-dialog": value = mcp_slate_open_new_level_dialog()
        elif args.operation == "mcp-inspect-entry-map": value = mcp_inspect_entry_map()
        elif args.operation == "bootstrap": value = bootstrap()
        elif args.operation == "apply-manifest": value = apply_manifest(args.manifest)
        elif args.operation == "build": value = build(args.target, args.timeout)
        elif args.operation == "smoke": value = smoke(args.timeout)
        elif args.operation == "networked-automation": value = networked_automation(args.timeout)
        elif args.operation == "create-entry-map": value = create_entry_map(args.timeout)
        elif args.operation == "open": value = open_editor()
        elif args.operation == "close": value = close_editor(args.timeout)
        elif args.operation == "wait-mcp": value = wait_mcp(args.timeout)
        else: value = git_complete(args.message, args.files, push=args.push)
    except (Refused, OSError, subprocess.SubprocessError) as error:
        value = {"success": False, "error": str(error), "operation": args.operation}
        print(json.dumps(value, indent=2, default=str))
        return 2
    print(json.dumps(value, indent=2, default=str))
    return 0 if value.get("success", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
