#!/usr/bin/env python3
"""Read Codex account rate limits through the supported local App Server RPC.

This starts a short-lived ``codex app-server --stdio`` process, performs only
``initialize`` and ``account/rateLimits/read``, then exits.  It never starts a
thread or model turn, so it does not intentionally consume coding-model quota.
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent


def _reader(stream: Any, out: "queue.Queue[str]") -> None:
    try:
        for line in stream:
            out.put(line)
    except Exception:
        pass


def _wait_for_id(lines: "queue.Queue[str]", request_id: int, deadline: float) -> dict[str, Any] | None:
    while time.monotonic() < deadline:
        try: line = lines.get(timeout=max(0.05, min(0.5, deadline - time.monotonic())))
        except queue.Empty: continue
        try: message = json.loads(line)
        except json.JSONDecodeError: continue
        if isinstance(message, dict) and message.get("id") == request_id:
            return message
    return None


def probe_rate_limits(timeout: float = 12.0) -> dict[str, Any]:
    exe = shutil.which("codex")
    if not exe:
        return {"ok": False, "error": "codex CLI not found", "at": time.time()}
    process: subprocess.Popen[str] | None = None
    try:
        kwargs: dict[str, Any] = {}
        if os.name == "nt":
            # This probe runs once per minute under pythonw.exe.  Without
            # CREATE_NO_WINDOW a console-capable Codex executable can briefly
            # flash a terminal even though the probe itself is background-only.
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        process = subprocess.Popen(
            [exe, "app-server", "--stdio"],
            cwd=REPO,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            **kwargs,
        )
        assert process.stdin is not None and process.stdout is not None
        lines: queue.Queue[str] = queue.Queue(); threading.Thread(target=_reader, args=(process.stdout, lines), daemon=True).start()
        initialize = {"id":1,"method":"initialize","params":{"clientInfo":{"name":"CotS Quota Probe","version":"1.0"},"capabilities":{"experimentalApi":True}}}
        process.stdin.write(json.dumps(initialize,separators=(",",":"))+"\n"); process.stdin.flush()
        deadline = time.monotonic() + timeout
        init_response = _wait_for_id(lines, 1, deadline)
        if not init_response or init_response.get("error"):
            return {"ok": False, "error": f"initialize failed: {init_response}", "at": time.time()}
        process.stdin.write(json.dumps({"id":2,"method":"account/rateLimits/read"},separators=(",",":"))+"\n"); process.stdin.flush()
        response = _wait_for_id(lines, 2, deadline)
        if not response:
            return {"ok": False, "error": "account/rateLimits/read timed out", "at": time.time()}
        if response.get("error"):
            return {"ok": False, "error": str(response.get("error"))[:1200], "at": time.time()}
        result = response.get("result")
        return {"ok": isinstance(result, dict), "result": result if isinstance(result, dict) else {}, "at": time.time()}
    except Exception as error:
        return {"ok": False, "error": f"{type(error).__name__}: {error}", "at": time.time()}
    finally:
        if process is not None and process.poll() is None:
            try:
                process.terminate(); process.wait(timeout=2)
            except Exception:
                try: process.kill()
                except Exception: pass


if __name__ == "__main__": print(json.dumps(probe_rate_limits(), indent=2, default=str))
