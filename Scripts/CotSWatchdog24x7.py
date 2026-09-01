#!/usr/bin/env python3
"""Persistent, zero-AI-cost outer watchdog for the CotS autonomous factory."""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from CotS24x7Common import (
    COTS, FACTORY_STATE, HEALTH_PATH, STOP_FILE, SUPERVISOR_STATE,
    DailyTelemetry, EventTailer, atomic_json, clean_text, consume_control,
    ensure_control_token, meaningful_progress, progress_signature, read_json,
    safe_nonnegative_int, snapshot_health, write_control,
)
from CotSRecovery import (
    HUMAN_REQUIRED_EXIT, clear_provider_activity, clear_provider_cancel,
    read_json as recovery_read_json, reclaim_orphaned_provider, request_provider_cancel,
)

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "Scripts"
FACTORY = SCRIPTS / "CotSFactoryController24x7.py"
FIXIT = SCRIPTS / "CotSAgentFixIt.py"
INCIDENTS = COTS / "incidents"
FIXIT_RESULT = COTS / "fixit-result.local.json"
OUTPUT_LOG = COTS / "factory-24x7-output.log"
LOCK_PATH = COTS / "watchdog-24x7.lock"
POLL_SECONDS = 1.0
HEALTH_WRITE_SECONDS = 5.0
NO_PROGRESS_WINDOW_SECONDS = 180.0
BACKOFF_STEPS = (5, 15, 60, 120, 300, 900, 1800)
FIXIT_TRIGGER_STREAK = 3
FIXIT_MIN_INTERVAL_SECONDS = 60 * 60
FIXIT_TIMEOUT_SECONDS = 2 * 60 * 60 + 5 * 60
TRUE_HUMAN_TERMS = (
    "mfa", "multi-factor", "two-factor", "2fa", "login required", "authentication required",
    "credential", "secret required", "subscription", "payment", "billing", "captcha",
    "physical confirmation", "manual destructive decision",
)


def _pid_live(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class SingleInstance:
    def __init__(self) -> None:
        COTS.mkdir(parents=True, exist_ok=True)
        LOCK_PATH.touch(exist_ok=True)
        if LOCK_PATH.stat().st_size == 0:
            LOCK_PATH.write_text(" ", encoding="utf-8")
        self.file = LOCK_PATH.open("r+", encoding="utf-8")
        try:
            if os.name == "nt":
                import msvcrt
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.file.close()
            raise RuntimeError("CotS 24x7 watchdog is already running") from error
        self.file.seek(0)
        self.file.truncate()
        self.file.write(json.dumps({"pid": os.getpid(), "started_at": time.time()}) + "\n")
        self.file.flush()

    def close(self) -> None:
        try:
            if not self.file.closed:
                if os.name == "nt":
                    import msvcrt
                    self.file.seek(0)
                    msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
                self.file.close()
        except OSError:
            pass


class Watchdog:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765, serve: bool = True) -> None:
        self.telemetry = DailyTelemetry()
        self.tailer = EventTailer(self.telemetry)
        self.host, self.port, self.serve = host, port, serve
        self.token = ensure_control_token()
        self.stop_event = threading.Event()
        self.factory: subprocess.Popen[str] | None = None
        self.httpd: ThreadingHTTPServer | None = None
        self.http_thread: threading.Thread | None = None
        self.started_at = time.time()
        self.generation = 0
        self.restart_count = 0
        self.no_progress_streak = 0
        self.last_progress_at = self.started_at
        self.last_exit: dict[str, Any] | None = None
        self.last_fixit_at = 0.0
        self.cooldown_until = 0.0
        self.state = "STARTING"
        self.current_action = "Initializing"
        self._last_health_write = 0.0
        self._last_state_summary: tuple[Any, ...] | None = None

    def health(self) -> dict[str, Any]:
        factory = read_json(FACTORY_STATE)
        supervisor = read_json(SUPERVISOR_STATE)
        return {
            "schema_version": 1, "pid": os.getpid(), "state": self.state,
            "current_action": self.current_action, "started_at": self.started_at,
            "uptime_seconds": max(0, time.time() - self.started_at),
            "generation": self.generation, "restart_count": self.restart_count,
            "no_progress_streak": self.no_progress_streak, "last_progress_at": self.last_progress_at,
            "cooldown_until": self.cooldown_until or None,
            "factory_pid": self.factory.pid if self.factory and self.factory.poll() is None else None,
            "factory_state": factory.get("factory") or factory.get("state"),
            "supervisor_state": supervisor.get("state"), "task": supervisor.get("task"),
            "phase": supervisor.get("phase"), "active_agent": supervisor.get("active_agent"),
            "last_successful_gate": supervisor.get("last_successful_gate"), "last_exit": self.last_exit,
            "telemetry_url": f"http://{self.host}:{self.port}/", "updated_at": time.time(),
        }

    def persist_health(self, force: bool = False) -> None:
        if not force and time.time() - self._last_health_write < HEALTH_WRITE_SECONDS:
            return
        atomic_json(HEALTH_PATH, self.health())
        self._last_health_write = time.time()

    def log_state_transition(self) -> None:
        sup = read_json(SUPERVISOR_STATE)
        fac = read_json(FACTORY_STATE)
        summary = (
            fac.get("factory") or fac.get("state"), sup.get("state"), sup.get("task"),
            sup.get("phase"), sup.get("active_agent"), sup.get("current_action"), sup.get("turn_count"),
        )
        if summary != self._last_state_summary:
            self._last_state_summary = summary
            self.telemetry.emit(
                "STATE",
                f"{summary[0] or 'factory?'} | {summary[1] or 'supervisor?'} | "
                f"{summary[2] or 'task?'} / {summary[3] or 'phase?'} | "
                f"agent={summary[4] or 'none'} | {clean_text(summary[5], 300)}",
                turn_count=safe_nonnegative_int(summary[6], 0),
            )

    def start_http(self) -> None:
        if not self.serve:
            return
        parent = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "CotS24x7/1.0"

            def log_message(self, fmt: str, *args: object) -> None:
                parent.telemetry.emit("HTTP", clean_text(fmt % args, 500))

            def _send(self, status: int, body: bytes, content_type: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)

            def _json(self, status: int, value: object) -> None:
                self._send(status, json.dumps(value, indent=2, default=str).encode("utf-8"),
                           "application/json; charset=utf-8")

            def _control_authorized(self) -> bool:
                return self.headers.get("Authorization", "") == f"Bearer {parent.token}"

            def do_GET(self) -> None:
                path = urlparse(self.path).path
                if path in ("/", "/index.html"):
                    days = parent.telemetry.list_days()
                    h = parent.health()
                    rows = "".join(f'<li><a href="/logs/{day}">{day}</a></li>' for day in days[:60])
                    pretty = json.dumps(h, indent=2, default=str).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    html = f'''<!doctype html><meta charset="utf-8"><title>CotS 24x7 Telemetry</title>
<style>body{{font:14px system-ui;background:#11161d;color:#dce6f1;max-width:1100px;margin:30px auto}}pre{{background:#0b0f14;padding:16px;overflow:auto}}a{{color:#8fc7ff}}button{{margin-right:8px}}</style>
<h1>CotS 24x7 Telemetry</h1><p>Local telemetry only — this page consumes no Codex/Claude usage.</p>
<pre>{pretty}</pre><h2>Daily logs</h2><ul>{rows or '<li>No logs yet</li>'}</ul>
<h2>Control</h2><input id="token" type="password" size="55" placeholder="bearer token"><br><br>
<button onclick="ctl('restart')">Restart stack</button><button onclick="ctl('stop')">Stop safely</button><button onclick="ctl('resume')">Resume</button><pre id="result"></pre>
<script>async function ctl(a){{let t=document.getElementById('token').value;let r=await fetch('/control/'+a,{{method:'POST',headers:{{Authorization:'Bearer '+t}}}});document.getElementById('result').textContent=await r.text();}}</script>
<p><a href="/health">JSON health</a> · <a href="/snapshot">full local snapshot</a></p>'''
                    self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
                    return
                if path == "/health": self._json(200, parent.health()); return
                if path == "/snapshot": self._json(200, snapshot_health({"runtime": parent.health()})); return
                if path == "/logs": self._json(200, {"days": parent.telemetry.list_days()}); return
                if path.startswith("/logs/"):
                    text = parent.telemetry.read_day(path.removeprefix("/logs/"))
                    self._send(200 if text else 404, (text or "log not found").encode("utf-8"), "text/plain; charset=utf-8")
                    return
                self._send(404, b"not found", "text/plain; charset=utf-8")

            def do_POST(self) -> None:
                if not self._control_authorized():
                    self._json(HTTPStatus.UNAUTHORIZED, {"error": "Bearer token required"}); return
                mapping = {"/control/restart": "restart", "/control/stop": "stop", "/control/resume": "resume"}
                action = mapping.get(urlparse(self.path).path)
                if action is None:
                    self._json(404, {"error": "unknown control route"}); return
                write_control(action, source="telemetry_http")
                parent.telemetry.emit("REMOTE_CONTROL", f"Requested {action}")
                self._json(202, {"accepted": action})

        self.httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self.http_thread = threading.Thread(target=self.httpd.serve_forever, name="cots-telemetry-http", daemon=True)
        self.http_thread.start()
        self.telemetry.emit("TELEMETRY", f"HTTP telemetry listening on {self.host}:{self.port}")

    def stop_http(self) -> None:
        if self.httpd: self.httpd.shutdown(); self.httpd.server_close()
        if self.http_thread: self.http_thread.join(timeout=3)

    @staticmethod
    def _latest_incident() -> Path | None:
        if not INCIDENTS.exists(): return None
        files = sorted(INCIDENTS.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        return files[0] if files else None

    @staticmethod
    def _human_reason() -> str:
        factory = read_json(FACTORY_STATE); recovery = factory.get("recovery") or {}
        supervisor = read_json(SUPERVISOR_STATE)
        return clean_text(recovery.get("reason") or supervisor.get("human_gate") or supervisor.get("failure") or "", 1600)

    @staticmethod
    def _is_true_human_gate(reason: str) -> bool:
        lower = reason.lower()
        return any(term in lower for term in TRUE_HUMAN_TERMS)

    def local_cleanup(self) -> None:
        clear_provider_cancel()
        checkpoint = recovery_read_json(SUPERVISOR_STATE)
        factory_state = read_json(FACTORY_STATE)
        recorded_supervisor_pid = factory_state.get("supervisor_pid")
        if _pid_live(recorded_supervisor_pid):
            self.telemetry.emit("LOCAL_RECOVERY", "Existing recorded supervisor is still alive; checkpoint untouched", supervisor_pid=recorded_supervisor_pid)
            return
        try:
            if checkpoint.get("orphaned_provider_ownership") or checkpoint.get("provider_ownership"):
                reclaimed = reclaim_orphaned_provider(checkpoint)
                self.telemetry.emit("LOCAL_RECOVERY", f"Orphan provider reclaim attempted: {reclaimed}")
        except Exception as error:
            self.telemetry.emit("LOCAL_RECOVERY", f"Orphan provider cleanup failed safely: {error}")
        try:
            if checkpoint:
                atomic_json(SUPERVISOR_STATE, clear_provider_activity(checkpoint))
        except Exception as error:
            self.telemetry.emit("LOCAL_RECOVERY", f"Checkpoint cleanup failed safely: {error}")

    def provider_available_for_fixit(self) -> bool:
        sup = read_json(SUPERVISOR_STATE)
        statuses = [(sup.get(name) or {}).get("status") for name in ("codex", "claude")]
        return any(status not in {"USAGE_EXHAUSTED", "NOT_INSTALLED"} for status in statuses)

    def maybe_run_fixit(self) -> None:
        if self.no_progress_streak < FIXIT_TRIGGER_STREAK: return
        if time.time() - self.last_fixit_at < FIXIT_MIN_INTERVAL_SECONDS: return
        if not self.provider_available_for_fixit():
            self.telemetry.emit("FIXIT_SKIPPED", "No provider currently available; preserving quota"); return
        incident = self._latest_incident()
        if incident is None: return
        self.last_fixit_at = time.time(); self.state = "REPAIRING"
        self.current_action = f"One bounded FixIt turn for {incident.stem}"; self.persist_health(force=True)
        self.telemetry.emit("FIXIT_START", self.current_action)
        try:
            result = subprocess.run([sys.executable, str(FIXIT), "--incident", str(incident), "--attempt", "1"], cwd=REPO,
                                    text=True, capture_output=True, timeout=FIXIT_TIMEOUT_SECONDS, check=False)
            outcome = read_json(FIXIT_RESULT)
            self.telemetry.emit("FIXIT_END", f"FixIt exit={result.returncode} result={outcome.get('result', 'unknown')}",
                                stdout=clean_text(result.stdout[-4000:], 4000), stderr=clean_text(result.stderr[-4000:], 4000))
        except subprocess.TimeoutExpired:
            self.telemetry.emit("FIXIT_TIMEOUT", "Bounded FixIt exceeded timeout; returning to local backoff")
        except Exception as error:
            self.telemetry.emit("FIXIT_ERROR", f"{type(error).__name__}: {error}")

    def _open_output(self):
        COTS.mkdir(parents=True, exist_ok=True)
        try:
            if OUTPUT_LOG.exists() and OUTPUT_LOG.stat().st_size > 10_000_000:
                rotated = OUTPUT_LOG.with_suffix(".previous.log")
                try: rotated.unlink()
                except OSError: pass
                OUTPUT_LOG.replace(rotated)
        except OSError: pass
        return OUTPUT_LOG.open("a", encoding="utf-8", buffering=1)

    def launch_factory(self) -> tuple[dict[str, Any], float]:
        self.generation += 1; before = progress_signature(); started = time.time(); output = self._open_output()
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
        self.factory = subprocess.Popen([sys.executable, str(FACTORY)], cwd=REPO, text=True,
                                        stdout=output, stderr=subprocess.STDOUT, creationflags=creationflags)
        output.close(); self.state = "RUNNING"; self.current_action = f"Factory generation {self.generation} running"
        self.telemetry.emit("FACTORY_LAUNCH", self.current_action, pid=self.factory.pid, signature=before); self.persist_health(force=True)
        return before, started

    def graceful_stop_factory(self, reason: str) -> None:
        if not self.factory or self.factory.poll() is not None: return
        supervisor_pid = read_json(FACTORY_STATE).get("supervisor_pid")
        if isinstance(supervisor_pid, int) and supervisor_pid > 0:
            try: request_provider_cancel(supervisor_pid, reason)
            except Exception: pass
        deadline = time.time() + 25
        while self.factory.poll() is None and time.time() < deadline: time.sleep(0.5)
        if self.factory.poll() is None:
            try:
                self.factory.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT); self.factory.wait(timeout=10)
            except Exception:
                try: self.factory.terminate(); self.factory.wait(timeout=10)
                except Exception:
                    try: self.factory.kill()
                    except Exception: pass
        clear_provider_cancel(); self.local_cleanup()

    def process_control(self) -> str | None:
        command = consume_control(); action = command.get("action")
        if not action: return None
        self.telemetry.emit("CONTROL", f"Local control action: {action}", source=command.get("source"))
        if action == "restart":
            self.graceful_stop_factory("remote/local restart request"); self.no_progress_streak = 0; self.cooldown_until = 0; return "restart"
        if action == "stop":
            STOP_FILE.write_text(f"requested {time.time()}\n", encoding="utf-8"); self.graceful_stop_factory("safe stop request"); return "stop"
        if action == "resume":
            try: STOP_FILE.unlink()
            except OSError: pass
            self.no_progress_streak = 0; self.cooldown_until = 0; return "resume"
        return None

    def wait_with_telemetry(self, seconds: float, state: str, action: str) -> str | None:
        self.state, self.current_action = state, action; end = time.time() + max(0, seconds); self.cooldown_until = end; self.persist_health(force=True)
        while not self.stop_event.is_set() and time.time() < end:
            self.tailer.poll(); self.log_state_transition(); control = self.process_control()
            if control: return control
            self.persist_health(); self.stop_event.wait(min(POLL_SECONDS, max(0.05, end - time.time())))
        return None

    def monitor_factory(self, before: dict[str, Any], started: float) -> tuple[int, float, bool, str | None]:
        assert self.factory is not None
        while self.factory.poll() is None and not self.stop_event.is_set():
            self.tailer.poll(); self.log_state_transition(); control = self.process_control()
            if control in {"restart", "stop"}:
                return self.factory.poll() if self.factory.poll() is not None else 130, time.time() - started, False, control
            self.persist_health(); time.sleep(POLL_SECONDS)
        if self.stop_event.is_set() and self.factory.poll() is None: self.graceful_stop_factory("watchdog shutdown")
        exit_code = int(self.factory.poll() if self.factory.poll() is not None else 130)
        return exit_code, max(0.0, time.time() - started), meaningful_progress(before, progress_signature()), None

    def run(self) -> int:
        self.start_http(); self.telemetry.emit("WATCHDOG_START", "CotS 24x7 watchdog online", pid=os.getpid())
        try:
            while not self.stop_event.is_set():
                self.persist_health(); self.tailer.poll(); self.log_state_transition(); control = self.process_control()
                if control == "stop": self.state = "STOPPED_BY_USER"
                if STOP_FILE.exists():
                    self.state = "STOPPED_BY_USER"; self.current_action = "Autonomy paused; telemetry remains online"; self.persist_health(force=True)
                    while STOP_FILE.exists() and not self.stop_event.is_set():
                        self.tailer.poll(); self.process_control(); self.persist_health(); time.sleep(POLL_SECONDS)
                    continue
                if read_json(FACTORY_STATE).get("factory") == "COMPLETE":
                    self.wait_with_telemetry(60, "ROADMAP_COMPLETE", "Roadmap complete; telemetry/watchdog remain online"); continue

                self.local_cleanup(); before, started = self.launch_factory(); exit_code, runtime, progressed, control = self.monitor_factory(before, started)
                after = progress_signature(); self.factory = None
                if control == "stop": continue
                if control == "restart": self.restart_count += 1; continue
                if progressed:
                    self.no_progress_streak = 0; self.last_progress_at = time.time()
                elif runtime <= NO_PROGRESS_WINDOW_SECONDS or exit_code != 0:
                    self.no_progress_streak += 1
                self.last_exit = {"code": exit_code, "runtime_seconds": runtime, "progressed": progressed, "at": time.time(), "before": before, "after": after}
                self.telemetry.emit("FACTORY_EXIT", f"exit={exit_code} runtime={runtime:.1f}s progress={'YES' if progressed else 'NO'} no-progress-streak={self.no_progress_streak}", **self.last_exit)
                if exit_code == 0 and read_json(FACTORY_STATE).get("factory") == "COMPLETE": continue
                if exit_code == HUMAN_REQUIRED_EXIT:
                    reason = self._human_reason()
                    if self._is_true_human_gate(reason):
                        self.state = "HUMAN_REQUIRED"; self.current_action = reason or "Genuine human-only gate"; self.telemetry.emit("HUMAN_REQUIRED", self.current_action)
                        while not self.stop_event.is_set():
                            ctl = self.wait_with_telemetry(30, self.state, self.current_action)
                            if ctl in {"restart", "resume"}: break
                        continue
                    self.telemetry.emit("FALSE_HUMAN_GATE", f"Reclassified locally as recoverable: {reason}")
                self.restart_count += 1; self.maybe_run_fixit()
                index = min(self.no_progress_streak, len(BACKOFF_STEPS) - 1); delay = BACKOFF_STEPS[index] if self.no_progress_streak else BACKOFF_STEPS[0]
                if progressed: delay = BACKOFF_STEPS[0]
                self.telemetry.emit("BACKOFF", f"Local cooldown {delay}s before restart; provider is not called during cooldown", no_progress_streak=self.no_progress_streak)
                self.wait_with_telemetry(delay, "COOLDOWN", f"Protecting provider quota after exit {exit_code}; restart in {delay}s"); self.cooldown_until = 0
            return 0
        except KeyboardInterrupt:
            self.telemetry.emit("WATCHDOG_STOP", "Keyboard interrupt"); return 130
        except BaseException as error:
            trace = "".join(traceback.format_exception(type(error), error, error.__traceback__))[-12000:]
            self.telemetry.emit("WATCHDOG_CRASH", f"{type(error).__name__}: {error}", traceback=trace); print(trace, file=sys.stderr); return 1
        finally:
            self.state = "STOPPING"; self.current_action = "Safe watchdog shutdown"
            try: self.graceful_stop_factory("watchdog shutdown")
            except Exception: pass
            self.persist_health(force=True); self.stop_http()


def main() -> int:
    parser = argparse.ArgumentParser(description="CotS 24x7 autonomous watchdog")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-serve", action="store_true")
    args = parser.parse_args(); instance = SingleInstance()
    try: return Watchdog(args.host, args.port, not args.no_serve).run()
    finally: instance.close()


if __name__ == "__main__":
    raise SystemExit(main())
