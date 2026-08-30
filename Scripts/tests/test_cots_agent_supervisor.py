#!/usr/bin/env python3
"""Deterministic tests for TASK-008C's Codex/Claude usage-limit detection,
failed-turn classification, hot-loop circuit breaker, rotation, checkpoint
hygiene, task reconciliation, and dashboard rendering.

Run with: python -m unittest Scripts.tests.test_cots_agent_supervisor -v
(from the repository root), or `python Scripts/tests/test_cots_agent_supervisor.py`.

Fixtures under Scripts/tests/fixtures/ are captured live from the installed
CLIs where that was safely possible (Codex's real incident capture in
.cots/codex-protocol.log, and one real `claude -p ... --output-format json`
invocation of the installed Claude Code 2.1.251). The one exception is the
Claude usage-limit fixture, which cannot be captured without actually
exhausting account quota; its provenance and reasoning are documented inline
in Scripts/tests/fixtures/claude_usage_limit.json.
"""
from __future__ import annotations

import json
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SCRIPTS_DIR))

import importlib.util

_spec = importlib.util.spec_from_file_location("cots_agent_supervisor", SCRIPTS_DIR / "CotSAgentSupervisor.py")
sup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sup)


def load_jsonl_fixture(name: str) -> list[dict]:
    """Parse a ``.cots/*-protocol.log``-style trace file: each line is
    prefixed "> " (sent) or "< " (received) followed by one JSON object."""
    messages = []
    for line in (FIXTURES_DIR / name).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        messages.append(json.loads(line[2:]))
    return messages


def load_json_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def make_bare_app_server() -> "sup.AppServer":
    """An AppServer instance with none of the subprocess/thread machinery
    from __init__, for feeding real captured messages through _handle_message
    directly (the actual protocol-classification code path)."""
    app = sup.AppServer.__new__(sup.AppServer)
    app.messages = []
    app.usage_reset_reason = None
    app.usage_reset_at = None
    app.last_error = None
    app.last_rate_limits = None
    app.capacity_exhausted_hint = False
    app.lock = threading.Condition()
    return app


class NullStatusBusIO(unittest.TestCase):
    """Base class that prevents StatusBus from touching the real, live
    .cots/agent-supervisor.local.json and .cots/supervisor-events.log used by
    the actual incident this task is repairing."""

    def setUp(self) -> None:
        self._save_state_patch = mock.patch.object(sup, "save_state", lambda value: None)
        self._log_event_patch = mock.patch.object(sup, "log_event", lambda text: None)
        self._save_state_patch.start()
        self._log_event_patch.start()
        self.addCleanup(self._save_state_patch.stop)
        self.addCleanup(self._log_event_patch.stop)


# ---------------------------------------------------------------------------
# 1. Codex usageLimitExceeded classification against the ACTUAL captured
#    protocol (.cots/codex-protocol.log, excerpted into a fixture).
# ---------------------------------------------------------------------------

class TestCodexUsageLimitDetection(unittest.TestCase):
    def test_real_captured_exchange_marks_usage_exhausted(self):
        app = make_bare_app_server()
        for message in load_jsonl_fixture("codex_usage_limit_excerpt.jsonl"):
            app._handle_message(message)
        self.assertEqual(app.usage_reset_reason, "usageLimitExceeded")
        # "...or try again at 4:22 AM." parsed into a real future epoch.
        self.assertIsNotNone(app.usage_reset_at)
        self.assertGreater(app.usage_reset_at, time.time())

    def test_rate_limits_reached_type_null_is_not_a_false_negative_source(self):
        # The real capture's account/rateLimits/updated always has
        # rateLimitReachedType: null even mid-exhaustion; this must not be
        # required for detection (that was the root-cause bug).
        rate_limit_messages = [
            m for m in load_jsonl_fixture("codex_usage_limit_excerpt.jsonl")
            if m.get("method") == "account/rateLimits/updated"
        ]
        self.assertTrue(rate_limit_messages)
        for message in rate_limit_messages:
            self.assertIsNone(message["params"]["rateLimits"]["rateLimitReachedType"])

    def test_is_codex_usage_limit_error_matches_real_error_shape(self):
        error_messages = [m for m in load_jsonl_fixture("codex_usage_limit_excerpt.jsonl") if m.get("method") == "error"]
        self.assertTrue(error_messages)
        error = error_messages[0]["params"]["error"]
        self.assertTrue(sup.is_codex_usage_limit_error(error))

    def test_capacity_exhausted_rate_limits_hint_from_real_credits_shape(self):
        # Real captured shape: rateLimitReachedType is null, but credits show
        # no purchased balance. Surfaced as an informational hint only (see
        # is_capacity_exhausted_rate_limits docstring) -- never the sole
        # trigger for a state transition.
        messages = load_jsonl_fixture("codex_usage_limit_excerpt.jsonl")
        rate_limits_message = next(m for m in messages if m.get("method") == "account/rateLimits/updated")
        app = make_bare_app_server()
        app._handle_message(rate_limits_message)
        self.assertTrue(app.capacity_exhausted_hint)
        self.assertIsNone(app.usage_reset_reason)  # not, by itself, a hard trigger

    def test_unrelated_mcp_startup_failure_is_not_usage_limit(self):
        # Real captured line: cloudflare-api MCP login failure. Must never be
        # misclassified as a usage-limit/exhaustion signal.
        messages = load_jsonl_fixture("codex_usage_limit_excerpt.jsonl")
        cloudflare_failure = next(
            m for m in messages
            if m.get("method") == "mcpServer/startupStatus/updated" and m["params"].get("name") == "cloudflare-api"
        )
        app = make_bare_app_server()
        app._handle_message(cloudflare_failure)
        self.assertIsNone(app.usage_reset_reason)


# ---------------------------------------------------------------------------
# 2. Failed-turn classification: an empty failed Codex turn must never
#    become CONTINUE.
# ---------------------------------------------------------------------------

class FakeCodexAppServer:
    def __init__(self, turn: dict, last_error: dict | None = None):
        self._turn = turn
        self.last_error = last_error
        self.requests: list[tuple[str, dict]] = []

    def request(self, method, params, timeout=30):
        self.requests.append((method, params))
        return {}

    def wait_turn(self, thread_id, timeout=None):
        return self._turn


class TestFailedTurnClassification(unittest.TestCase):
    def _codex_agent(self, turn: dict, last_error: dict | None = None) -> "sup.CodexAgent":
        agent = sup.CodexAgent()
        agent.app = FakeCodexAppServer(turn, last_error)
        agent.thread_id = "thread-1"
        return agent

    def test_real_captured_failed_turn_raises_usage_reset_not_continuing(self):
        messages = load_jsonl_fixture("codex_usage_limit_excerpt.jsonl")
        failed_turn = next(m for m in messages if m.get("method") == "turn/completed")["params"]["turn"]
        self.assertEqual(failed_turn["status"], "failed")
        self.assertEqual(failed_turn["items"], [])  # the exact "empty items" shape from the incident
        agent = self._codex_agent(failed_turn)
        with self.assertRaises(sup.UsageResetRequired):
            agent.run_turn("continue")

    def test_unknown_failed_turn_is_not_continuing(self):
        turn = {
            "id": "t1", "status": "failed", "items": [],
            "error": {"message": "internal_error: something else broke", "codexErrorInfo": "internalError"},
            "durationMs": 500,
        }
        agent = self._codex_agent(turn)
        with self.assertRaises(sup.TurnFailed) as ctx:
            agent.run_turn("continue")
        self.assertFalse(ctx.exception.transient)

    def test_successful_turn_with_continue_marker_is_continuing(self):
        turn = {
            "id": "t1", "status": "completed", "error": None, "durationMs": 45000,
            "items": [{"type": "agentMessage", "text": "did work\nSUPERVISOR_OUTCOME: CONTINUE"}],
        }
        agent = self._codex_agent(turn)
        result = agent.run_turn("continue")
        kind, _ = sup.turn_outcome(result.text)
        self.assertEqual(kind, "CONTINUING")
        self.assertFalse(result.is_suspicious())

    def test_structured_human_gate_is_classified_human_gate(self):
        text = "Blocked.\nHUMAN_GATE: needs a human decision"
        kind, detail = sup.turn_outcome(text)
        self.assertEqual(kind, "HUMAN_GATE")
        self.assertEqual(detail, "needs a human decision")


# ---------------------------------------------------------------------------
# 3. Claude usage exhaustion classification against captured/representative
#    schema (see module docstring for what is real vs. representative).
# ---------------------------------------------------------------------------

class TestClaudeUsageLimitDetection(unittest.TestCase):
    def test_real_captured_success_payload_is_not_usage_limited(self):
        payload = load_json_fixture("claude_success.json")
        is_limited, _ = sup.detect_usage_limit(payload["result"], payload)
        self.assertFalse(is_limited)

    def test_representative_usage_limit_payload_is_detected(self):
        payload = load_json_fixture("claude_usage_limit.json")
        combined = f"{json.dumps(payload)}\n"
        is_limited, reset_at = sup.detect_usage_limit(combined, payload)
        self.assertTrue(is_limited)
        self.assertIsNotNone(reset_at)
        self.assertGreater(reset_at, time.time())

    def test_claude_error_payload_that_is_not_usage_limit_raises_turn_failed(self):
        payload = {"is_error": True, "subtype": "error_max_turns", "api_error_status": None, "result": "gave up"}
        completed = mock.Mock(returncode=1, stdout=json.dumps(payload), stderr="")
        agent = sup.ClaudeAgent()
        with mock.patch.object(sup.subprocess, "run", return_value=completed), \
             mock.patch.object(sup, "log_claude_protocol", lambda *a: None):
            with self.assertRaises(sup.TurnFailed) as ctx:
                agent.run_turn("continue")
        self.assertFalse(ctx.exception.transient)


# ---------------------------------------------------------------------------
# 4/5/6. Provider rotation: Codex -> Claude, Claude -> Codex, both unavailable.
# ---------------------------------------------------------------------------

class TestProviderRotation(unittest.TestCase):
    def test_codex_exhausted_rotates_to_claude(self):
        checkpoint = {
            "codex": {"status": "USAGE_EXHAUSTED", "reset_at": time.time() + 3600},
            "claude": {"status": "IDLE"},
        }
        next_name = sup.pick_ready_agent(checkpoint, {"codex", "claude"}, ["codex", "claude"], "codex")
        self.assertEqual(next_name, "claude")

    def test_claude_exhausted_rotates_back_to_codex_once_reset(self):
        checkpoint = {
            "codex": {"status": "IDLE"},
            "claude": {"status": "USAGE_EXHAUSTED", "reset_at": time.time() - 1},  # already reset
        }
        next_name = sup.pick_ready_agent(checkpoint, {"codex", "claude"}, ["codex", "claude"], "claude")
        self.assertEqual(next_name, "codex")

    def test_both_exhausted_waits_for_capacity(self):
        checkpoint = {
            "codex": {"status": "USAGE_EXHAUSTED", "reset_at": time.time() + 3600},
            "claude": {"status": "USAGE_EXHAUSTED", "reset_at": time.time() + 3600},
        }
        next_name = sup.pick_ready_agent(checkpoint, {"codex", "claude"}, ["codex", "claude"], "codex")
        self.assertIsNone(next_name)

    def test_stalled_provider_is_gated_like_usage_exhausted(self):
        checkpoint = {
            "codex": {"status": "STALLED_PROVIDER", "reset_at": time.time() + 60},
            "claude": {"status": "IDLE"},
        }
        self.assertFalse(sup.is_agent_usable(checkpoint["codex"], True))
        self.assertEqual(sup.pick_ready_agent(checkpoint, {"codex", "claude"}, ["codex", "claude"], "codex"), "claude")

    def test_not_configured_agent_is_never_usable(self):
        self.assertFalse(sup.is_agent_usable({"status": "IDLE"}, configured=False))


# ---------------------------------------------------------------------------
# 7. Hot-loop / no-op circuit breaker.
# ---------------------------------------------------------------------------

class TestHotLoopCircuitBreaker(unittest.TestCase):
    def test_three_consecutive_empty_fast_turns_trip_the_breaker(self):
        stall_streak: dict[str, int] = {}
        suspicious = sup.TurnResult(text="", duration_ms=900, activity_count=0)
        tripped = [sup.record_turn_and_check_stall(stall_streak, "codex", suspicious) for _ in range(3)]
        self.assertEqual(tripped, [False, False, True])

    def test_real_work_resets_the_streak(self):
        stall_streak = {"codex": 2}
        productive = sup.TurnResult(text="did real edits\nSUPERVISOR_OUTCOME: CONTINUE", duration_ms=45000, activity_count=3)
        tripped = sup.record_turn_and_check_stall(stall_streak, "codex", productive)
        self.assertFalse(tripped)
        self.assertEqual(stall_streak["codex"], 0)

    def test_slow_empty_turn_is_not_suspicious(self):
        # A turn with no text but that took real wall-clock time (e.g. a long
        # tool call that produced no final message) is not the same failure
        # shape as the sub-second empty-turn hot loop and must not trip early.
        result = sup.TurnResult(text="", duration_ms=45000, activity_count=0)
        self.assertFalse(result.is_suspicious())

    def test_provider_stalled_uses_short_backoff_not_provider_reset(self):
        error = sup.ProviderStalled("codex stalled")
        self.assertEqual(error.status_label, "STALLED_PROVIDER")
        self.assertAlmostEqual(error.reset_at, time.time() + sup.STALL_BACKOFF_SECONDS, delta=2)


# ---------------------------------------------------------------------------
# 8. Stale checkpoint field clearing.
# ---------------------------------------------------------------------------

class TestStaleCheckpointFields(NullStatusBusIO):
    def test_human_gate_clears_when_leaving_human_gate_state(self):
        bus = sup.StatusBus({"state": "STARTING"})
        bus.update(state="HUMAN_GATE", human_gate="needs a human decision")
        self.assertEqual(bus.data["human_gate"], "needs a human decision")
        # Reproduces the observed incident: state moves on to a running/failed
        # state without an explicit human_gate= in the same update call.
        bus.update(state="RUNNING_CODEX")
        self.assertIsNone(bus.data["human_gate"])

    def test_human_gate_set_together_with_state_is_preserved(self):
        bus = sup.StatusBus({"state": "STARTING"})
        bus.update(state="HUMAN_GATE", human_gate="needs a human decision")
        self.assertEqual(bus.data["human_gate"], "needs a human decision")


# ---------------------------------------------------------------------------
# 9. Task/phase reconciliation.
# ---------------------------------------------------------------------------

class TestTaskReconciliation(NullStatusBusIO):
    def test_task_from_lease_owner_matches_observed_live_value(self):
        self.assertEqual(sup.task_from_lease_owner("codex-task-012"), "TASK-012")

    def test_task_from_lease_owner_none_when_no_task_suffix(self):
        self.assertIsNone(sup.task_from_lease_owner("none"))
        self.assertIsNone(sup.task_from_lease_owner(None))

    def test_reconcile_falls_back_to_lease_owner_when_no_marker_seen(self):
        bus = sup.StatusBus({"task": None, "phase": None})
        sup.reconcile_task_phase(bus, "codex-task-012")
        self.assertEqual(bus.data["task"], "TASK-012")
        self.assertEqual(bus.data["phase"], "RECONCILING")

    def test_reconcile_never_overwrites_a_marker_already_parsed(self):
        bus = sup.StatusBus({"task": "TASK-008C", "phase": "dashboard-fix"})
        sup.reconcile_task_phase(bus, "codex-task-012")
        self.assertEqual(bus.data["task"], "TASK-008C")
        self.assertEqual(bus.data["phase"], "dashboard-fix")

    def test_reconcile_uses_explicit_reconciling_not_unknown_forever(self):
        bus = sup.StatusBus({"task": None, "phase": None})
        sup.reconcile_task_phase(bus, None)
        self.assertEqual(bus.data["task"], "RECONCILING")


# ---------------------------------------------------------------------------
# 10. Dashboard atomic rendering / bounded event history.
# ---------------------------------------------------------------------------

class TestDashboardRendering(unittest.TestCase):
    def test_frame_lines_are_single_line_and_ansi_free(self):
        snapshot = {"state": "RUNNING_CODEX", "recent_events": ["ok"], "task": "TASK-012"}
        for line in sup.render_frame_lines(snapshot):
            self.assertNotIn("\n", line)
            self.assertNotIn("\x1b", line)

    def test_event_history_is_bounded(self):
        snapshot = {"state": "RUNNING_CODEX", "recent_events": [f"event {i}" for i in range(50)]}
        lines = sup.render_frame_lines(snapshot)
        event_lines = [line for line in lines if line.strip().startswith("event ")]
        self.assertLessEqual(len(event_lines), sup.MAX_RECENT_EVENTS)

    def test_raw_stderr_dump_is_summarized_to_one_safe_line(self):
        # Reproduces the exact real event text observed in
        # .cots/supervisor-events.log during the incident: a multi-line,
        # ANSI-colored subprocess stderr dump passed as one event string.
        raw = "Unrecoverable failure: app_server_exited: \x1b[2m2026-08-30T01:03:08Z\x1b[0m \x1b[31mERROR\x1b[0m worker quit\nwith fatal: Transport channel closed"
        summarized = sup.summarize_event(raw)
        self.assertNotIn("\n", summarized)
        self.assertNotIn("\x1b", summarized)

    def test_frame_payload_erases_every_line_before_its_newline(self):
        lines = ["short", "a longer line than before"]
        payload = sup._frame_payload(lines)
        self.assertEqual(payload.count("\x1b[K"), len(lines))  # exactly one erase-to-end-of-line per row
        self.assertTrue(payload.startswith("\x1b[H"))
        self.assertTrue(payload.endswith("\x1b[0J\n"))

    def test_stalled_provider_status_shows_reset_line(self):
        snapshot = {"state": "RUNNING_CODEX", "codex": {"status": "STALLED_PROVIDER", "reset_at": time.time() + 60}}
        lines = sup.render_frame_lines(snapshot)
        self.assertTrue(any("reset=" in line for line in lines))

    def test_rotating_agent_shows_no_active_agent(self):
        snapshot = {"state": "ROTATING_AGENT", "active_agent": None}
        lines = sup.render_frame_lines(snapshot)
        self.assertTrue(any("Active Agent:" in line and "transitioning" in line for line in lines))

    def test_unknown_task_phase_render_as_reconciling_not_unknown(self):
        lines = sup.render_frame_lines({"state": "STARTING"})
        joined = "\n".join(lines)
        self.assertNotIn("(unknown)", joined)
        self.assertIn("RECONCILING", joined)


# ---------------------------------------------------------------------------
# 11. Single-agent lease invariant.
# ---------------------------------------------------------------------------

class TestSupervisorLease(unittest.TestCase):
    def test_second_instance_is_refused(self):
        with mock.patch.object(sup, "LEASE", Path(SCRIPTS_DIR / "tests" / "_lease_test.local.lock")):
            sup.LEASE.parent.mkdir(exist_ok=True)
            if sup.LEASE.exists():
                sup.LEASE.unlink()
            first = sup.SupervisorLease()
            try:
                with self.assertRaises(sup.AppServerError):
                    sup.SupervisorLease()
            finally:
                first.close()
                sup.LEASE.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 9 (dirty-work classification helper used by the dashboard, TASK-008C #9).
# ---------------------------------------------------------------------------

class TestGitStatusClassification(unittest.TestCase):
    def test_classifies_supervisor_vs_protected_vs_untracked(self):
        status_lines = [
            " M Scripts/CotSAgentSupervisor.py",
            " M UnrealPlugin/CotSDeveloperTools/Source/CotSDeveloperTools/Private/Mutation/CotSMutationToolset.cpp",
            "?? ToolLab/Content/",
            "?? Scripts/tests/test_cots_agent_supervisor.py",
        ]
        counts = sup.classify_git_status(status_lines)
        self.assertEqual(counts, {"supervisor": 2, "protected": 1, "untracked_other": 1})


if __name__ == "__main__":
    unittest.main()
