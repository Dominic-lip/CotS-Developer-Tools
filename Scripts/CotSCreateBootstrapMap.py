#!/usr/bin/env python3
"""Create the fixed TASK-015 production bootstrap map without UI automation.

This helper is intentionally narrow: it targets only
``C:\\Dev\\CotS\\Content\\Maps\\CotS_Entry.umap`` in the fixed UE 5.8 production
project.  It does not accept arbitrary paths, Unreal commands, executables or
shell text.  Its purpose is to avoid retrying a native Slate "New Level..."
action when the production MCP registry has no direct map-creation tool.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PRODUCTION = Path(r"C:\Dev\CotS")
PROJECT = PRODUCTION / "CotS.uproject"
MAP_FILE = PRODUCTION / "Content" / "Maps" / "CotS_Entry.umap"
ENGINE = Path(os.environ.get("COTS_UE_ROOT", r"C:\Program Files\Epic Games\UE_5.8"))
EDITOR_CMD = ENGINE / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe"
STATE_FILE = Path(__file__).resolve().parent.parent / ".cots" / "production-map-bootstrap.local.json"
CREATE_FLAGS = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def build_command() -> list[str]:
    """Return the one reviewed Unreal command this helper may execute."""
    map_path = MAP_FILE.as_posix()
    exec_cmds = f'MAP NEW;MAP SAVE FILE="{map_path}";QUIT'
    return [
        str(EDITOR_CMD),
        str(PROJECT),
        "-unattended",
        "-nop4",
        "-nosplash",
        "-NullRHI",
        "-NoSound",
        f"-ExecCmds={exec_cmds}",
    ]


def create_bootstrap_map(timeout_seconds: int = 300) -> dict[str, Any]:
    """Create CotS_Entry once and verify the durable .umap exists."""
    if not PROJECT.is_file():
        return {"success": False, "error": "production_project_missing", "project": str(PROJECT)}
    if not EDITOR_CMD.is_file():
        return {"success": False, "error": "unreal_editor_cmd_missing", "editor_cmd": str(EDITOR_CMD)}
    if MAP_FILE.is_file():
        result = {"success": True, "changed": False, "map": str(MAP_FILE), "reason": "already_exists"}
        _atomic_json(STATE_FILE, {**result, "updated_at": time.time()})
        return result

    MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            build_command(),
            cwd=PRODUCTION,
            text=True,
            capture_output=True,
            timeout=max(30, min(1200, int(timeout_seconds))),
            check=False,
            creationflags=CREATE_FLAGS,
        )
    except subprocess.TimeoutExpired as error:
        result = {
            "success": False,
            "changed": MAP_FILE.is_file(),
            "error": "bootstrap_map_timeout",
            "map": str(MAP_FILE),
            "timeout_seconds": int(timeout_seconds),
            "stdout_tail": (error.stdout or "")[-6000:] if isinstance(error.stdout, str) else "",
            "stderr_tail": (error.stderr or "")[-6000:] if isinstance(error.stderr, str) else "",
        }
        _atomic_json(STATE_FILE, {**result, "updated_at": time.time()})
        return result

    output = (completed.stdout + completed.stderr)[-12000:]
    exists = MAP_FILE.is_file()
    result = {
        "success": completed.returncode == 0 and exists,
        "changed": exists,
        "map": str(MAP_FILE),
        "exit_code": completed.returncode,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "output_tail": output,
    }
    if not exists:
        result["error"] = "bootstrap_map_not_created"
    elif completed.returncode != 0:
        result["error"] = "unreal_editor_cmd_failed"
    _atomic_json(STATE_FILE, {**result, "updated_at": time.time()})
    return result


def main() -> int:
    timeout = 300
    if len(sys.argv) > 1:
        try:
            timeout = int(sys.argv[1])
        except ValueError:
            print(json.dumps({"success": False, "error": "timeout must be an integer"}, indent=2))
            return 2
    result = create_bootstrap_map(timeout)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
