#!/usr/bin/env python3
"""Enhanced CotS 24x7 watchdog with productivity, hardware and local-AI guards."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import CotSWatchdog24x7 as base
from CotS24x7Common import FACTORY_STATE, STOP_FILE, SUPERVISOR_STATE, clean_text, meaningful_progress, progress_signature, read_json
from CotSHardwareTelemetry import HardwareMonitor
from CotSLegacyGovernorRecovery import recover_persisted
from CotSLocalAI import LocalAI
from CotSNotifications import MilestoneNotifier
from CotSOperationalMetrics import OperationalMetrics
from CotSProductivityGovernor import ProductivityGovernor
from CotSRollbackGuard import RollbackGuard
from CotSUsageLedger import ProviderUsageLedger
from CotSRecovery import HUMAN_REQUIRED_EXIT

LOCAL_POLL_SECONDS = 5.0


class EnhancedWatchdog(base.Watchdog):
    def __init__(self, host: str = "127.0.0.1", port: int = 8765, serve: bool = True) -> None:
        super().__init__(host, port, serve)
        self.usage = ProviderUsageLedger()
        self.governor = ProductivityGovernor()
        self.hardware_monitor = HardwareMonitor()
        self.local_ai = LocalAI()
        self.notifier = MilestoneNotifier()
        self.metrics = OperationalMetrics()
        self.rollback = RollbackGuard()
        self.cached_usage: dict[str, Any] = {}
        self.cached_governor: dict[str, Any] = self.governor.snapshot()
        self.cached_hardware: dict[str, Any] = {}
        self.local_analysis: dict[str, Any] | None = None
        self._last_local_poll = 0.0
        self._hardware_clear_streak = 0

    def _poll_local(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_local_poll < LOCAL_POLL_SECONDS: return
        self._last_local_poll = now
        try:
            self.usage.poll(); self.cached_usage = self.usage.snapshot()
        except Exception as error:
            self.telemetry.emit("LOCAL_USAGE_ERROR", f"Usage ledger failed safely: {error}")
        supervisor = read_json(SUPERVISOR_STATE)
        try:
            self.cached_governor = self.governor.observe(supervisor)
        except Exception as error:
            self.telemetry.emit("GOVERNOR_ERROR", f"Productivity governor failed safely: {error}")
        try:
            self.cached_hardware = self.hardware_monitor.poll()
        except Exception as error:
            self.telemetry.emit("HARDWARE_ERROR", f"Hardware telemetry failed safely: {error}")
        try:
            cooldown = max(0.0, float(self.cooldown_until or 0) - now)
            self.notifier.poll(self.health_base(), supervisor, cooldown_seconds=cooldown)
        except Exception as error:
            self.telemetry.emit("NOTIFY_ERROR", f"Milestone notifier failed safely: {error}")
        try:
            self.metrics.record(self.health_base(), supervisor, self.cached_governor, self.cached_hardware)
        except Exception as error:
            self.telemetry.emit("METRICS_ERROR", f"Operational metrics failed safely: {error}")

    def health_base(self) -> dict[str, Any]:
        return super().health()

    def health(self) -> dict[str, Any]:
        value = self.health_base()
        report = self.metrics.report(24.0)
        governor = self.cached_governor or self.governor.snapshot()
        last_productive = governor.get("last_productive_at")
        productive_now = isinstance(last_productive, (int, float)) and time.time() - last_productive <= 15 * 60
        value.update({
            "runtime_profile": "enhanced-24x7",
            "alive": value.get("state") not in {"STOPPING", "STOPPED"},
            "productive": productive_now,
            "usage": self.cached_usage,
            "productivity_governor": governor,
            "hardware": self.cached_hardware,
            "report_24h": report,
            "local_ai": {"available": self.local_ai.available, "model": self.local_ai.model, "last_analysis": self.local_analysis},
        })
        return value

    def _recent_log_text(self) -> str:
        days = self.telemetry.list_days()
        return self.telemetry.read_day(days[0])[-12000:] if days else ""

    def _run_local_diagnosis(self, trigger: str) -> dict[str, Any]:
        excerpt = self._recent_log_text()
        wake, analysis = self.local_ai.should_wake_cloud(excerpt or trigger)
        analysis = dict(analysis); analysis["cloud_wake_recommended"] = wake; analysis["trigger"] = trigger
        self.local_analysis = analysis
        self.telemetry.emit("LOCAL_DIAGNOSIS", clean_text(analysis.get("summary") or trigger, 800), analysis=analysis)
        return analysis

    def monitor_factory(self, before: dict[str, Any], started: float) -> tuple[int, float, bool, str | None]:
        assert self.factory is not None
        while self.factory.poll() is None and not self.stop_event.is_set():
            self.tailer.poll(); self.log_state_transition(); self._poll_local()
            control = self.process_control()
            if control in {"restart", "stop"}:
                return self.factory.poll() if self.factory.poll() is not None else 130, time.time() - started, False, control

            reason = (self.cached_hardware or {}).get("safety_reason")
            if reason:
                self.telemetry.emit("HARDWARE_PAUSE", str(reason))
                self.graceful_stop_factory(f"hardware safety gate: {reason}")
                return self.factory.poll() if self.factory.poll() is not None else 130, time.time() - started, False, "hardware_pause"

            # The new productivity governor is the authoritative quota guard.
            # If it has observed enough real provider turns to trip, honour it
            # before attempting any compatibility recovery of the older guard.
            if self.governor.tripped():
                reason = str((self.cached_governor or {}).get("trip_reason") or "productivity governor tripped")
                self.telemetry.emit("GOVERNOR_PAUSE", reason, governor=self.cached_governor)
                self.graceful_stop_factory(reason)
                self._run_local_diagnosis(reason)
                return self.factory.poll() if self.factory.poll() is not None else 130, time.time() - started, False, "governor_pause"

            # Older V3.x supervisors intentionally park forever in
            # GOVERNOR_PAUSED when their package-local zero/micro-delta guard
            # wants a changed strategy.  In a 24x7 system that creates a
            # deadlock: no provider turn can happen, so no new evidence can
            # ever clear the block.  Rebaseline only those strategy streaks,
            # preserve all historical counters, then restart the factory.  A
            # hard package-budget block is deliberately not overridden.
            supervisor = read_json(SUPERVISOR_STATE)
            if str(supervisor.get("state") or "") == "GOVERNOR_PAUSED":
                task_id = str(supervisor.get("task") or "").strip()
                legacy_reason = clean_text(supervisor.get("current_action") or supervisor.get("failure") or "legacy usage governor paused", 900)
                recovery = recover_persisted(task_id, source="24x7-watchdog") if task_id else {"recovered": False, "reason": "missing task id"}
                if recovery.get("recovered"):
                    self.telemetry.emit(
                        "LEGACY_GOVERNOR_RECOVERED",
                        f"Rebaselined {task_id}/{recovery.get('package')} after strategy-only legacy governor block",
                        recovery=recovery,
                        previous_action=legacy_reason,
                    )
                    self.state = "RECOVERING"
                    self.current_action = f"Legacy governor strategy block cleared for {task_id}; restarting factory"
                    self.persist_health(force=True)
                    self.graceful_stop_factory("legacy usage-governor strategy rebaseline")
                    return self.factory.poll() if self.factory.poll() is not None else 130, time.time() - started, False, "legacy_governor_recover"
                self.state = "LEGACY_GOVERNOR_BLOCKED"
                self.current_action = f"Legacy governor block preserved: {clean_text(recovery.get('reason') or legacy_reason, 500)}"
                self.persist_health(force=True)

            self.persist_health(); time.sleep(base.POLL_SECONDS)
        if self.stop_event.is_set() and self.factory.poll() is None: self.graceful_stop_factory("watchdog shutdown")
        exit_code = int(self.factory.poll() if self.factory.poll() is not None else 130)
        return exit_code, max(0.0, time.time() - started), meaningful_progress(before, progress_signature()), None

    def _wait_hardware(self) -> str | None:
        self.state = "HARDWARE_PAUSED"; self.current_action = str((self.cached_hardware or {}).get("safety_reason") or "Hardware safety gate")
        self.telemetry.emit("HARDWARE_WAIT", self.current_action)
        self._hardware_clear_streak = 0
        while not self.stop_event.is_set():
            self._poll_local(force=True)
            reason = (self.cached_hardware or {}).get("safety_reason")
            if reason:
                self._hardware_clear_streak = 0; self.current_action = str(reason)
            else:
                self._hardware_clear_streak += 1
                if self._hardware_clear_streak >= 2:
                    self.telemetry.emit("HARDWARE_RECOVERED", "Hardware safety conditions recovered; autonomous work may resume")
                    return None
            control = self.process_control()
            if control in {"restart", "resume", "stop"}: return control
            self.persist_health(force=True); self.stop_event.wait(10)
        return "stop"

    def _wait_governor(self) -> str | None:
        cooldown_until = (self.cached_governor or {}).get("cooldown_until")
        if not isinstance(cooldown_until, (int, float)): cooldown_until = time.time() + 15 * 60
        delay = max(60.0, cooldown_until - time.time())
        self.telemetry.emit("GOVERNOR_COOLDOWN", f"Cloud provider paused locally for {delay/60:.1f} minutes", analysis=self.local_analysis)
        control = self.wait_with_telemetry(delay, "GOVERNOR_PAUSED", "Local diagnosis/cooldown after unproductive provider turns")
        if control in {"stop", "restart"}: return control
        self.governor.reset_streak("local diagnosis cooldown completed"); self.cached_governor = self.governor.snapshot()
        return control

    def _canary_runtime(self) -> None:
        changed = self.rollback.changed_files()
        if not changed: return
        self.telemetry.emit("RUNTIME_CANARY", f"Autonomous runtime changed {len(changed)} managed file(s); running local canary", files=changed)
        try:
            ok, detail = self.rollback.run_canary()
        except Exception as error:
            ok, detail = False, f"canary exception: {error}"
        if ok:
            self.rollback.promote(detail); self.telemetry.emit("RUNTIME_PROMOTED", detail, files=changed)
        else:
            restored = self.rollback.restore(detail)
            self.telemetry.emit("RUNTIME_ROLLBACK", f"Canary failed; restored {len(restored)} pre-generation runtime file(s)", detail=detail, files=restored)

    def run(self) -> int:
        self.start_http(); self.telemetry.emit("WATCHDOG_START", "CotS enhanced 24x7 watchdog online", pid=__import__("os").getpid())
        try:
            while not self.stop_event.is_set():
                self._poll_local(); self.persist_health(); self.tailer.poll(); self.log_state_transition(); control = self.process_control()
                if control == "stop": self.state = "STOPPED_BY_USER"
                if STOP_FILE.exists():
                    self.state = "STOPPED_BY_USER"; self.current_action = "Autonomy paused; telemetry remains online"; self.persist_health(force=True)
                    while STOP_FILE.exists() and not self.stop_event.is_set():
                        self._poll_local(); self.tailer.poll(); self.process_control(); self.persist_health(); time.sleep(base.POLL_SECONDS)
                    continue
                if read_json(FACTORY_STATE).get("factory") == "COMPLETE":
                    self.wait_with_telemetry(60, "ROADMAP_COMPLETE", "Roadmap complete; telemetry/watchdog remain online"); continue

                self.local_cleanup()
                self.rollback.prepare_generation(self.generation + 1)
                before, started = self.launch_factory()
                exit_code, runtime, progressed, control = self.monitor_factory(before, started)
                after = progress_signature(); self.factory = None
                self._canary_runtime(); self._poll_local(force=True)

                if control == "stop": continue
                if control == "restart": self.restart_count += 1; continue
                if control == "hardware_pause":
                    ctl = self._wait_hardware()
                    if ctl == "stop": continue
                    self.restart_count += 1; continue
                if control == "governor_pause":
                    ctl = self._wait_governor()
                    if ctl == "stop": continue
                    self.restart_count += 1; continue
                if control == "legacy_governor_recover":
                    # Do not reset the new productivity governor here.  It must
                    # continue counting actual no-value provider turns across
                    # compatibility recoveries and will trip at its own limit.
                    self.restart_count += 1
                    self.telemetry.emit("LEGACY_GOVERNOR_RESTART", "Restarting factory after local strategy rebaseline; provider quota not used during restart")
                    self.wait_with_telemetry(5, "RECOVERING", "Restarting after legacy governor strategy rebaseline")
                    continue

                if progressed:
                    self.no_progress_streak = 0; self.last_progress_at = time.time()
                elif runtime <= base.NO_PROGRESS_WINDOW_SECONDS or exit_code != 0:
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
                index = min(self.no_progress_streak, len(base.BACKOFF_STEPS) - 1)
                delay = base.BACKOFF_STEPS[index] if self.no_progress_streak else base.BACKOFF_STEPS[0]
                if progressed: delay = base.BACKOFF_STEPS[0]
                self.telemetry.emit("BACKOFF", f"Local cooldown {delay}s before restart; provider is not called during cooldown", no_progress_streak=self.no_progress_streak)
                self.wait_with_telemetry(delay, "COOLDOWN", f"Protecting provider quota after exit {exit_code}; restart in {delay}s"); self.cooldown_until = 0
            return 0
        except KeyboardInterrupt:
            self.telemetry.emit("WATCHDOG_STOP", "Keyboard interrupt"); return 130
        except BaseException as error:
            import traceback, sys
            trace = "".join(traceback.format_exception(type(error), error, error.__traceback__))[-12000:]
            self.telemetry.emit("WATCHDOG_CRASH", f"{type(error).__name__}: {error}", traceback=trace); print(trace, file=sys.stderr); return 1
        finally:
            self.state = "STOPPING"; self.current_action = "Safe watchdog shutdown"
            try: self.graceful_stop_factory("watchdog shutdown")
            except Exception: pass
            self.persist_health(force=True); self.stop_http()


def main() -> int:
    parser = argparse.ArgumentParser(description="CotS enhanced 24x7 autonomous watchdog")
    parser.add_argument("--host", default="127.0.0.1"); parser.add_argument("--port", type=int, default=8765); parser.add_argument("--no-serve", action="store_true")
    args = parser.parse_args()
    try: lease = base.SingleInstance()
    except RuntimeError as error:
        print(error); return 2
    watchdog = EnhancedWatchdog(args.host, args.port, not args.no_serve)
    try: return watchdog.run()
    finally: lease.close()


if __name__ == "__main__": raise SystemExit(main())
