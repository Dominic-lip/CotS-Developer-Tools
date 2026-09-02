#!/usr/bin/env python3
"""Production entry point for the enhanced CotS 24x7 watchdog."""
from __future__ import annotations

import time

import CotSWatchdog24x7Enhanced as enhanced
from CotS24x7Common import STOP_FILE, SUPERVISOR_STATE, clean_text, read_json
from CotSLoopGuard import LoopGuard, durable_evidence, durable_progress
from CotSProcessLiveness import process_live
from CotSUsageLedgerSafe import LockedProviderUsageLedger

# EnhancedWatchdog resolves this module global when it constructs the ledger.
enhanced.ProviderUsageLedger = LockedProviderUsageLedger
# Base watchdog cleanup must never use os.kill(pid, 0) as a Windows liveness
# probe. A stale/racing supervisor PID previously raised SystemError and killed
# the entire outer watchdog immediately after successful local governor recovery.
enhanced.base._pid_live = process_live

# A provider turn completing is activity, not durable engineering progress.
# Both the base launch/exit snapshot and enhanced monitor must use the same
# evidence definition so a repeated gate cannot reset no-progress backoff.
def _durable_progressed(before: dict, after: dict) -> bool:
    return durable_progress(before, after)[0]

enhanced.base.progress_signature = durable_evidence
enhanced.base.meaningful_progress = _durable_progressed
enhanced.progress_signature = durable_evidence
enhanced.meaningful_progress = _durable_progressed


class ProductionWatchdog(enhanced.EnhancedWatchdog):
    """Keep zero-cost telemetry alive and make unchanged provider loops impossible."""
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.loop_guard = LoopGuard(threshold=2)

    def health(self) -> dict:
        value = super().health()
        value["loop_guard"] = self.loop_guard.snapshot()
        return value

    def wait_with_telemetry(self, seconds: float, state: str, action: str) -> str | None:
        self.state, self.current_action = state, action
        end = time.time() + max(0, seconds)
        self.cooldown_until = end
        self.persist_health(force=True)
        while not self.stop_event.is_set() and time.time() < end:
            self.tailer.poll()
            self.log_state_transition()
            self._poll_local()
            control = self.process_control()
            if control:
                return control
            self.persist_health()
            self.stop_event.wait(min(enhanced.base.POLL_SECONDS, max(0.05, end - time.time())))
        return None

    def _wait_loop_guard(self, decision: dict) -> str:
        gate = decision.get("gate") if isinstance(decision.get("gate"), dict) else {}
        reason = clean_text(gate.get("reason") or "repeated unchanged engineering gate", 700)
        repeats = int(decision.get("repeat_count") or 0)
        blocked_kind = str(decision.get("blocked_kind") or "repeated_gate")
        self.state = "BLOCKED_CONFIGURATION" if blocked_kind == "configuration" else "BLOCKED_REPEAT"
        self.current_action = f"Provider suspended after {repeats} unchanged gates: {reason}"
        self.cooldown_until = 0
        self.telemetry.emit(
            "LOOP_GUARD_BLOCKED",
            self.current_action,
            decision=decision,
            loop_guard=self.loop_guard.snapshot(),
        )
        self.persist_health(force=True)

        while not self.stop_event.is_set():
            self.tailer.poll()
            self.log_state_transition()
            self._poll_local()
            supervisor = read_json(SUPERVISOR_STATE)
            if self.loop_guard.condition_changed(supervisor):
                self.loop_guard.clear("durable evidence or gate condition changed")
                self.telemetry.emit(
                    "LOOP_GUARD_RELEASED",
                    "Relevant engineering/configuration state changed; one bounded retry is allowed",
                )
                return "changed"
            control = self.process_control()
            if control == "stop" or STOP_FILE.exists():
                return "stop"
            if control in {"restart", "resume"}:
                # A human/operator explicitly requested a new experiment. This
                # is the only way to retry an unchanged fingerprint; automatic
                # cooldowns/restarts never clear the guard.
                self.loop_guard.clear(f"explicit operator {control}")
                self.telemetry.emit(
                    "LOOP_GUARD_OPERATOR_OVERRIDE",
                    f"Explicit operator {control} cleared the repeated-gate hold for one new attempt",
                )
                return "changed"
            self.persist_health()
            self.stop_event.wait(5.0)
        return "stop"

    def monitor_factory(self, before: dict, started: float) -> tuple[int, float, bool, str | None]:
        exit_code, runtime, _progressed, control = super().monitor_factory(before, started)
        if control is not None:
            return exit_code, runtime, False, control

        supervisor = read_json(SUPERVISOR_STATE)
        after = durable_evidence(supervisor)
        progressed, progress_reasons = durable_progress(before, after)
        decision = self.loop_guard.observe(supervisor, before, after)

        if decision.get("blocked"):
            # The Factory has already exited at this point. Stay alive locally,
            # serve telemetry, and make zero further provider calls until a
            # relevant state change or explicit operator override occurs.
            self.last_exit = {
                "code": exit_code,
                "runtime_seconds": runtime,
                "progressed": False,
                "at": time.time(),
                "before": before,
                "after": after,
                "loop_guard": decision,
            }
            outcome = self._wait_loop_guard(decision)
            return exit_code, runtime, False, "stop" if outcome == "stop" else "restart"

        if progressed:
            self.telemetry.emit("DURABLE_PROGRESS", ", ".join(progress_reasons), reasons=progress_reasons)
        return exit_code, runtime, progressed, control

    def maybe_run_fixit(self) -> None:
        """Ask local analysis whether an expensive cloud repair turn is useful."""
        if self.no_progress_streak < enhanced.base.FIXIT_TRIGGER_STREAK:
            return
        analysis = self._run_local_diagnosis("repeated no-progress factory failures before cloud FixIt")
        if analysis.get("cloud_wake_recommended") is False:
            self.telemetry.emit(
                "FIXIT_SKIPPED_LOCAL_AI",
                "Local diagnosis says a cloud repair turn is not useful yet; keeping recovery local",
                analysis=analysis,
            )
            return
        super().maybe_run_fixit()


# enhanced.main() instantiates its module-global EnhancedWatchdog class.
enhanced.EnhancedWatchdog = ProductionWatchdog

if __name__ == "__main__":
    raise SystemExit(enhanced.main())
