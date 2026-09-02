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
import json
import os
import re
import socket
import subprocess
import sys
import time
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
MAX_MANIFEST_FILES = 100
MAX_TEXT_BYTES = 2 * 1024 * 1024
ALLOWED_TASKS = {"TASK-015", *(f"TASK-{n}" for n in range(100, 116))}
ALLOWED_TEXT_SUFFIXES = {
    ".h", ".hpp", ".cpp", ".c", ".cs", ".ini", ".json", ".md", ".txt",
    ".uproject", ".uplugin", ".xml", ".yml", ".yaml", ".toml", ".cfg",
    ".bat", ".cmd", ".ps1", ".gitignore",
}
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
    planned: list[tuple[Path, str, str]] = []
    total = 0
    for entry in files:
        if not isinstance(entry, dict):
            raise Refused("manifest file entry must be an object")
        relative = str(entry.get("path") or "")
        content = entry.get("content")
        mode = str(entry.get("mode") or "upsert")
        if mode not in {"create", "upsert"} or not isinstance(content, str):
            raise Refused("manifest supports text create/upsert only")
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_TEXT_BYTES:
            raise Refused(f"manifest file too large: {relative}")
        total += len(encoded)
        if total > MAX_TEXT_BYTES * 4:
            raise Refused("manifest total text payload is too large")
        target = _safe_relpath(relative)
        if mode == "create" and target.exists():
            raise Refused(f"create target already exists: {relative}")
        planned.append((target, content, relative))
    changed: list[str] = []
    unchanged: list[str] = []
    for target, content, relative in planned:
        target.parent.mkdir(parents=True, exist_ok=True)
        current = target.read_text(encoding="utf-8") if target.exists() else None
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
    return {
        "production_root": str(PRODUCTION),
        "project": str(PROJECT),
        "project_exists": PROJECT.is_file(),
        "git_initialized": (PRODUCTION / ".git").exists(),
        "git_clean": bool(git is not None and git.get("exit_code") == 0 and not git.get("output_tail", "").strip()),
        "git_head": (head or {}).get("output_tail", "").strip() if head else None,
        "engine_available": EDITOR.is_file() and EDITOR_CMD.is_file() and BUILD_BAT.is_file(),
        "editor_running": editor_running,
        "editor_pid": pid if editor_running else None,
        "mcp_ready": _mcp_ready() if editor_running else False,
        "state": state,
    }


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
    if not PROJECT.is_file() or not EDITOR_CMD.is_file():
        raise Refused("production project or UnrealEditor-Cmd is missing")
    command = [
        str(EDITOR_CMD), str(PROJECT), "-unattended", "-nop4", "-nosplash",
        "-NullRHI", "-NoSound", "-ExecCmds=Quit",
    ]
    result = _run(command, cwd=PRODUCTION, timeout=max(30, min(1200, int(timeout_seconds))), creationflags=NEW_PROCESS_GROUP)
    _write_state(last_operation="smoke", smoke_exit_code=result["exit_code"])
    return {"success": result["exit_code"] == 0, **result}


def git_complete(message: str, files: list[str], *, push: bool = False) -> dict[str, Any]:
    if not (PRODUCTION / ".git").exists():
        raise Refused("production Git repository is not initialized")
    message = " ".join(str(message or "").split())
    if not message or len(message) > 180:
        raise Refused("commit message must be 1..180 characters")
    requested: list[str] = []
    for value in files:
        target = _safe_relpath(value)
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
    sub.add_parser("bootstrap")
    manifest = sub.add_parser("apply-manifest"); manifest.add_argument("manifest")
    build_parser = sub.add_parser("build"); build_parser.add_argument("--target", choices=("editor", "game", "server"), default="editor"); build_parser.add_argument("--timeout", type=int, default=1800)
    smoke_parser = sub.add_parser("smoke"); smoke_parser.add_argument("--timeout", type=int, default=300)
    sub.add_parser("open")
    close_parser = sub.add_parser("close"); close_parser.add_argument("--timeout", type=int, default=45)
    wait_parser = sub.add_parser("wait-mcp"); wait_parser.add_argument("--timeout", type=int, default=90)
    complete = sub.add_parser("git-complete"); complete.add_argument("--message", required=True); complete.add_argument("--push", action="store_true"); complete.add_argument("files", nargs="+")
    args = parser.parse_args()
    try:
        if args.operation == "status": value = status()
        elif args.operation == "bootstrap": value = bootstrap()
        elif args.operation == "apply-manifest": value = apply_manifest(args.manifest)
        elif args.operation == "build": value = build(args.target, args.timeout)
        elif args.operation == "smoke": value = smoke(args.timeout)
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
