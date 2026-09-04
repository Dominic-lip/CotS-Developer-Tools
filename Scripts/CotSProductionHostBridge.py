#!/usr/bin/env python3
"""Loopback-only host bridge for the fixed CotS production lifecycle.

The Codex App Server runs provider commands under a restricted Windows identity.
That sandbox is intentionally unable to mutate ``C:\\Dev\\CotS`` directly.  The
campaign still needs an auditable way to perform the already-reviewed fixed
production operations, so the persistent local watchdog owns this tiny bridge
under the operator's Windows account.

The bridge never accepts an executable, working directory or shell command.  It
accepts only argv intended for ``CotSProductionLifecycleCampaign.py`` and then
launches exactly that fixed script with a private direct-execution environment
flag.  The lifecycle script remains responsible for all task, manifest, path,
Git and Unreal operation validation.
"""
from __future__ import annotations

import hmac
import json
import os
import secrets
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "Scripts"
COTS = REPO / ".cots"
TOKEN_PATH = COTS / "production-host-token.local.txt"
CAMPAIGN_SCRIPT = SCRIPTS / "CotSProductionLifecycleCampaign.py"
HOST = "127.0.0.1"
PORT = 8011
DIRECT_ENV = "COTS_PRODUCTION_HOST_DIRECT"
MAX_REQUEST_BYTES = 64 * 1024
MAX_ARGC = 128
MAX_ARG_CHARS = 8192
MAX_OUTPUT_CHARS = 250_000
DEFAULT_TIMEOUT_SECONDS = 2 * 60 * 60 + 10 * 60
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def ensure_token() -> str:
    COTS.mkdir(parents=True, exist_ok=True)
    try:
        token = TOKEN_PATH.read_text(encoding="utf-8").strip()
        if len(token) >= 32:
            return token
    except OSError:
        pass
    token = secrets.token_urlsafe(36)
    TOKEN_PATH.write_text(token + "\n", encoding="utf-8")
    try:
        os.chmod(TOKEN_PATH, 0o600)
    except OSError:
        pass
    return token


def validate_argv(value: object) -> list[str]:
    """Validate transport shape; semantic operation/path checks stay in adapter."""
    if not isinstance(value, list) or not value or len(value) > MAX_ARGC:
        raise ValueError("argv must be a non-empty bounded list")
    argv: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item or len(item) > MAX_ARG_CHARS:
            raise ValueError("argv contains an invalid argument")
        if "\x00" in item or "\r" in item or "\n" in item:
            raise ValueError("argv contains a forbidden control character")
        argv.append(item)
    operation = argv[0]
    if not operation.replace("-", "").isalnum() or operation.startswith("-"):
        raise ValueError("invalid lifecycle operation name")
    return argv


def _bounded_timeout(argv: list[str]) -> int:
    """Honor only bounded integer --timeout hints without trusting arbitrary text."""
    timeout = DEFAULT_TIMEOUT_SECONDS
    for index, value in enumerate(argv[:-1]):
        if value == "--timeout":
            try:
                requested = int(argv[index + 1])
            except ValueError:
                break
            timeout = max(30, min(requested + 300, DEFAULT_TIMEOUT_SECONDS))
            break
    return timeout


def execute_fixed(argv: list[str]) -> dict[str, Any]:
    argv = validate_argv(argv)
    env = os.environ.copy()
    env[DIRECT_ENV] = "1"
    timeout = _bounded_timeout(argv)
    try:
        completed = subprocess.run(
            [sys.executable, str(CAMPAIGN_SCRIPT), *argv],
            cwd=REPO,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            creationflags=CREATE_NO_WINDOW,
        )
        return {
            "success": True,
            "exit_code": int(completed.returncode),
            "stdout": completed.stdout[-MAX_OUTPUT_CHARS:],
            "stderr": completed.stderr[-MAX_OUTPUT_CHARS:],
        }
    except subprocess.TimeoutExpired as error:
        return {
            "success": False,
            "exit_code": 124,
            "stdout": str(error.stdout or "")[-MAX_OUTPUT_CHARS:],
            "stderr": (str(error.stderr or "") + "\nproduction host bridge timeout")[-MAX_OUTPUT_CHARS:],
        }
    except OSError as error:
        return {"success": False, "exit_code": 125, "stdout": "", "stderr": str(error)}


class _Handler(BaseHTTPRequestHandler):
    server_version = "CotSProductionHost/1.0"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self._json(404, {"success": False, "error": "not_found"})
            return
        supplied = self.headers.get("X-CotS-Production-Token", "")
        if not hmac.compare_digest(supplied, self.server.token):  # type: ignore[attr-defined]
            self._json(403, {"success": False, "error": "forbidden"})
            return
        self._json(200, {"success": True, "service": "CotSProductionHostBridge", "direct_identity": os.environ.get("USERNAME")})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/run":
            self._json(404, {"success": False, "error": "not_found"})
            return
        supplied = self.headers.get("X-CotS-Production-Token", "")
        if not hmac.compare_digest(supplied, self.server.token):  # type: ignore[attr-defined]
            self._json(403, {"success": False, "error": "forbidden"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_REQUEST_BYTES:
            self._json(413, {"success": False, "error": "invalid_request_size"})
            return
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            argv = validate_argv(body.get("argv") if isinstance(body, dict) else None)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            self._json(400, {"success": False, "error": str(error)})
            return
        result = execute_fixed(argv)
        self._json(200, result)


class ProductionHostBridge:
    """Owned loopback server lifecycle for the persistent campaign watchdog."""

    def __init__(self, host: str = HOST, port: int = PORT) -> None:
        self.host = host
        self.port = int(port)
        self.token = ensure_token()
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.httpd is not None:
            return
        server = ThreadingHTTPServer((self.host, self.port), _Handler)
        server.daemon_threads = True
        server.token = self.token  # type: ignore[attr-defined]
        self.httpd = server
        self.thread = threading.Thread(target=server.serve_forever, name="CotSProductionHostBridge", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        server, thread = self.httpd, self.thread
        self.httpd = None
        self.thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=3)


if __name__ == "__main__":
    bridge = ProductionHostBridge()
    bridge.start()
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        bridge.stop()
