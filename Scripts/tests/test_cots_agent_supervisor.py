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
import tempfile
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


def load_stream_fixture_lines(name: str) -> list[str]:
    """Load a plain (unprefixed) stream-json capture: one JSON object per
    line, as `claude -p --output-format stream-json` actually emits it."""
    return [line for line in (FIXTURES_DIR / name).read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Test doubles for the streamed Claude turn driver (TASK-008C Claude-hang
# fix): FakeClaudeProcess stands in for subprocess.Popen so
# _drive_claude_process / ClaudeAgent.run_turn can be driven deterministically
# without spawning a real `claude` process, exactly the way FakeCodexAppServer
# stands in for AppServer above.
# ---------------------------------------------------------------------------

class _StreamThenHang:
    """Yields the given lines, then blocks forever -- simulates a process
    that produced some real output and then genuinely stalled."""

    def __init__(self, lines):
        self._lines = list(lines)

    def __iter__(self):
        return self

    def __next__(self):
        if self._lines:
            return self._lines.pop(0)
        time.sleep(3600)


class FakeClaudeProcess:
    """Minimal subprocess.Popen stand-in: pre-scripted stdout/stderr, no real
    OS process. terminate()/kill() are recorded, never touch anything real."""

    def __init__(self, stdout_lines=(), stderr_lines=(), exit_code=0, hang=False):
        self.stdout = _StreamThenHang(stdout_lines) if hang else iter(list(stdout_lines))
        self.stderr = _StreamThenHang(stderr_lines) if hang else iter(list(stderr_lines))
        self._exit_code = exit_code
        self._hanging = hang
        self.terminated = False
        self.killed = False

    def poll(self):
        return None if self._hanging else self._exit_code

    def terminate(self):
        self.terminated = True
        self._hanging = False

    def kill(self):
        self.killed = True
        self._hanging = False

    def wait(self, timeout=None):
        return self._exit_code


class RecordingBus:
    """Records every event/current_action passed to .update(), matching only
    the subset of StatusBus's interface _drive_claude_process actually uses
    -- no real file I/O, so these tests never touch .cots/*."""

    def __init__(self):
        self.events: list[str] = []
        self.current_actions: list[str] = []
        self.data: dict = {}

    def update(self, event=None, **fields):
        self.data.update(fields)
        if event:
            self.events.append(event)
        if "current_action" in fields:
            self.current_actions.append(fields["current_action"])


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


class TestRoadmapCompletionState(unittest.TestCase):
    def test_checked_in_state_schedules_earliest_unverified_foundation_task(self):
        self.assertEqual(sup.next_required_task(), "TASK-012")
        verified, reason = sup.foundation_completion_decision()
        self.assertFalse(verified)
        self.assertEqual(reason, "Foundation gate outstanding: TASK-012")

    def test_malformed_or_incomplete_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state_path.write_text('{"tasks": []}', encoding="utf-8")
            with self.assertRaises(sup.AppServerError):
                sup.load_foundation_completion_state(state_path)

    def test_unverified_complete_marker_has_a_scheduler_instruction(self):
        instruction = sup.scheduled_task_instruction()
        self.assertIn("TASK-012", instruction)
        self.assertIn("durable evidence", instruction)

    def test_provider_self_validation_rule_uses_the_active_adapter(self):
        self.assertIn("active supervisor\nadapter", sup.PROVIDER_SELF_VALIDATION_RULE)
        self.assertIn("unsupported validation topology", sup.PROVIDER_SELF_VALIDATION_RULE)
        self.assertIn(sup.PROVIDER_SELF_VALIDATION_RULE, sup.CODEX_START)
        self.assertIn(sup.PROVIDER_SELF_VALIDATION_RULE, sup.CLAUDE_START)


class TestDeferredProviderVerification(unittest.TestCase):
    def checkpoint(self):
        return {
            "task": "TASK-012", "phase": "claude-proof", "compact_task_context": {
                "task_id": "TASK-012", "acceptance_remaining": ["Claude independent compatibility/autonomy proof"],
            }, "claude": {"status": "USAGE_EXHAUSTED", "next_availability_probe_at": 1234.0},
        }

    def test_provider_specific_gate_is_deferred_but_remains_incomplete(self):
        parked, candidate = sup.park_provider_verification(self.checkpoint(), required_provider="claude", remaining_acceptance=["Claude proof"], hard_dependency_scope="TASK-015")
        self.assertEqual(candidate, "TASK-013")
        self.assertEqual(parked["deferred_verifications"][0]["task_id"], "TASK-012")
        self.assertEqual(sup.next_required_task(), "TASK-012")
        self.assertFalse(sup.foundation_completion_decision()[0])

    def test_safe_independent_work_proceeds_but_true_dependency_blocks(self):
        self.assertEqual(sup.safe_independent_task(self.checkpoint(), "TASK-012"), "TASK-013")
        self.assertNotIn("TASK-015", sup.INDEPENDENT_FOUNDATION_WORK)

    def test_parking_is_idempotent_and_does_not_duplicate_evidence_work(self):
        parked, _ = sup.park_provider_verification(self.checkpoint(), required_provider="claude", remaining_acceptance=["Claude proof"], hard_dependency_scope="TASK-015")
        parked_again, _ = sup.park_provider_verification(parked, required_provider="claude", remaining_acceptance=["Claude proof"], hard_dependency_scope="TASK-015")
        self.assertEqual(len(parked_again["deferred_verifications"]), 1)

    def test_recovery_schedules_proof_only_at_safe_boundary(self):
        parked, _ = sup.park_provider_verification(self.checkpoint(), required_provider="claude", remaining_acceptance=["Claude proof"], hard_dependency_scope="TASK-015")
        parked["claude"] = {"status": "READY"}
        ready = sup.deferred_verification_ready(parked, {"codex", "claude"})
        self.assertEqual(ready["required_provider"], "claude")
        self.assertEqual(ready["resume_checkpoint"]["task"], "TASK-012")

    def test_provider_probe_is_not_a_task_turn(self):
        class ProbeOK:
            def probe_availability(self): pass
        bus = sup.StatusBus({"claude": {"status": "USAGE_EXHAUSTED", "reset_at": time.time() - 1}})
        with mock.patch.object(sup, "save_state", lambda value: None), mock.patch.object(sup, "log_event", lambda text: None):
            sup.refresh_provider_availability(bus, {"claude": ProbeOK()})
        self.assertNotIn("task_turns", bus.data.get("efficiency", {}))

    def test_deferred_debt_cannot_be_removed_without_authoritative_proof(self):
        parked, _ = sup.park_provider_verification(self.checkpoint(), required_provider="claude", remaining_acceptance=["Claude proof"], hard_dependency_scope="TASK-015")
        unchanged, completed = sup.complete_deferred_verification(parked, "TASK-012")
        self.assertIsNone(completed)
        self.assertEqual(len(unchanged["deferred_verifications"]), 1)

    def test_roadmap_complete_is_forbidden_while_deferred_debt_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            document = json.loads(sup.FOUNDATION_COMPLETION_STATE.read_text(encoding="utf-8"))
            for task in document["tasks"]:
                task["status"] = "COMPLETE_VERIFIED"; task["evidence"] = ["test"]
            path = Path(directory) / "completion.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            checkpoint = {"deferred_verifications": [{"task_id": "TASK-012", "required_provider": "claude"}]}
            allowed, reason = sup.roadmap_completion_decision(checkpoint, path=path)
        self.assertFalse(allowed)
        self.assertIn("TASK-012", reason)


class TestCapacityWaitTelemetry(NullStatusBusIO):
    def test_local_wait_heartbeat_consumes_no_provider_turn(self):
        class ShutdownNow:
            def is_set(self): return False
            def wait(self, _seconds): return True
        bus = sup.StatusBus({"state": "WAITING_FOR_AGENT_CAPACITY", "claude": {"status": "USAGE_EXHAUSTED", "reset_at": time.time() + 300}})
        self.assertTrue(sup.wait_for_capacity(bus, ShutdownNow(), {"claude"}, provider="claude"))
        self.assertEqual(bus.data["waiting_for_provider"], "claude")
        self.assertIn("wait_heartbeat_at", bus.data)
        self.assertNotIn("provider_turns", bus.data.get("efficiency", {}))

    def test_due_availability_probe_is_still_scheduled_after_wait(self):
        class ProbeOK:
            calls = 0
            def probe_availability(self): self.calls += 1
        provider = ProbeOK()
        bus = sup.StatusBus({"state": "WAITING_FOR_USAGE_RESET", "claude": {"status": "USAGE_EXHAUSTED", "reset_at": time.time() - 1}})
        self.assertEqual(sup.refresh_provider_availability(bus, {"claude": provider}, ["claude"]), {"claude"})
        self.assertEqual(provider.calls, 1)
        self.assertEqual(bus.data["claude"]["status"], "READY")

    def test_test_turn_limit_is_not_completion_state(self):
        # The bounded limit is intentionally represented by STOPPING in main;
        # keep the exact policy visible without launching a provider process.
        self.assertNotIn('state="COMPLETE", current_action="Test turn limit reached"', (SCRIPTS_DIR / "CotSAgentSupervisor.py").read_text(encoding="utf-8"))

    def test_current_action_has_a_real_start_timestamp(self):
        bus = sup.StatusBus({"state": "STARTING"})
        before = time.time()
        bus.update(current_action="Waiting for agent capacity")
        self.assertGreaterEqual(bus.data["action_started_at"], before)
        started = bus.data["action_started_at"]
        bus.update(wait_heartbeat_at=time.time())
        self.assertEqual(bus.data["action_started_at"], started)


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

    def test_structured_handoff_is_not_a_human_gate(self):
        text = "SUPERVISOR_OUTCOME: HANDOFF\nSUPERVISOR_TARGET_AGENT: codex\nSUPERVISOR_HANDOFF_REASON: live MCP proof requires Codex"
        kind, detail = sup.turn_outcome(text)
        self.assertEqual(kind, "HANDOFF")
        self.assertEqual(sup.handoff_target(detail), "codex")

    def test_structured_recoverable_gate_preserves_category_reason_and_action(self):
        text = ("SUPERVISOR_OUTCOME: RECOVERABLE_GATE\n"
                "SUPERVISOR_GATE_CATEGORY: RECOVERABLE_VALIDATION_TOPOLOGY\n"
                "SUPERVISOR_GATE_REASON: recursive provider invocation\n"
                "SUPERVISOR_RECOMMENDED_ACTION: use active adapter")
        kind, detail = sup.turn_outcome(text)
        self.assertEqual(kind, "RECOVERABLE_GATE")
        self.assertEqual(detail, "RECOVERABLE_VALIDATION_TOPOLOGY|recursive provider invocation|use active adapter")

    def test_waiting_checkpoint_restores_pending_structured_handoff(self):
        state = {
            "state": "WAITING_FOR_AGENT_CAPACITY",
            "last_output": "SUPERVISOR_OUTCOME: HANDOFF\nSUPERVISOR_TARGET_AGENT: claude\nSUPERVISOR_HANDOFF_REASON: independent verification",
        }
        self.assertEqual(sup.restored_handoff_target(state, {"codex", "claude"}), "claude")
        self.assertIsNone(sup.restored_handoff_target({**state, "state": "RUNNING_CODEX"}, {"codex", "claude"}))

    def test_provider_bound_human_gate_is_recoverable_but_real_decision_is_not(self):
        self.assertTrue(sup.human_gate_is_provider_recoverable("Codex reset passed but provider handoff is pending"))
        self.assertFalse(sup.human_gate_is_provider_recoverable("Choose whether to delete the production map"))


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
        payload = {
            "type": "result", "is_error": True, "subtype": "error_max_turns",
            "api_error_status": None, "result": "gave up", "session_id": "s3", "num_turns": 40,
        }
        process = FakeClaudeProcess(stdout_lines=['{"type":"system","subtype":"init"}', json.dumps(payload)], stderr_lines=[])
        agent = sup.ClaudeAgent()
        with mock.patch.object(sup.subprocess, "Popen", return_value=process):
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

    def test_future_reset_is_not_due_for_probe(self):
        self.assertFalse(sup.provider_due_for_probe({"status": "USAGE_EXHAUSTED", "reset_at": time.time() + 60}))

    def test_elapsed_reset_is_due_for_one_probe(self):
        now = time.time()
        self.assertTrue(sup.provider_due_for_probe({"status": "USAGE_EXHAUSTED", "reset_at": now - 1}, now))
        self.assertFalse(sup.provider_due_for_probe({"status": "USAGE_EXHAUSTED", "reset_at": now - 1, "last_availability_probe_at": now}, now))

    def test_unknown_reset_provider_becomes_due_at_persisted_probe_time(self):
        now = 10_000.0
        info = {"status": "USAGE_EXHAUSTED", "reset_at": None, "next_availability_probe_at": now + 1}
        self.assertFalse(sup.provider_due_for_probe(info, now))
        self.assertTrue(sup.provider_due_for_probe(info, now + 1))

    def test_unknown_reset_backoff_is_bounded_and_prevents_probe_spam(self):
        now = 10_000.0
        info = {"status": "USAGE_EXHAUSTED", "reset_at": None}
        first = sup.schedule_unknown_reset_probe(info, now, failed_probe=False)
        self.assertEqual(first["availability_probe_attempts"], 0)
        self.assertEqual(first["next_availability_probe_at"], now + 300)
        failed = sup.schedule_unknown_reset_probe({**info, **first}, now + 300, failed_probe=True)
        self.assertEqual(failed["availability_probe_attempts"], 1)
        self.assertEqual(failed["next_availability_probe_at"], now + 300 + 600)
        self.assertFalse(sup.provider_due_for_probe({**info, **failed}, now + 300 + 599))
        self.assertEqual(sup.unknown_reset_probe_delay(99), sup.UNKNOWN_RESET_MAX_PROBE_SECONDS)

    def test_capacity_wait_wakes_for_earliest_known_or_unknown_deadline(self):
        now = 10_000.0
        checkpoint = {
            "codex": {"status": "USAGE_EXHAUSTED", "reset_at": now + 120},
            "claude": {"status": "USAGE_EXHAUSTED", "reset_at": None, "next_availability_probe_at": now + 45},
        }
        self.assertEqual(sup.capacity_recheck_wait_seconds(checkpoint, {"codex", "claude"}, now), 45)
        self.assertEqual(sup.capacity_recheck_wait_seconds({"codex": checkpoint["codex"]}, {"codex"}, now), 120)

    def test_preferred_return_requires_real_recovery_at_safe_boundary(self):
        checkpoint = {"codex": {"status": "READY"}}
        self.assertTrue(sup.should_return_to_preferred(checkpoint, "claude", "codex", {"codex"}))
        self.assertFalse(sup.should_return_to_preferred(checkpoint, "claude", "codex", set()))
        self.assertFalse(sup.should_return_to_preferred(checkpoint, "codex", "codex", {"codex"}))


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

    def test_recoverable_gate_clears_when_leaving_recoverable_gate_state(self):
        bus = sup.StatusBus({"state": "STARTING"})
        bus.update(state="RECOVERABLE_GATE", recoverable_gate={"category": "RECOVERABLE_HOST_MCP"})
        bus.update(state="RUNNING_CODEX")
        self.assertIsNone(bus.data["recoverable_gate"])

    def test_successful_availability_probe_clears_stale_reset_and_error(self):
        class ProbeOK:
            def probe_availability(self): pass
        bus = sup.StatusBus({"codex": {"status": "USAGE_EXHAUSTED", "reset_at": time.time() - 1, "last_error": "usageLimitExceeded"}})
        recovered = sup.refresh_provider_availability(bus, {"codex": ProbeOK()}, ["codex"])
        self.assertEqual(recovered, {"codex"})
        self.assertEqual(bus.data["codex"]["status"], "READY")
        self.assertIsNone(bus.data["codex"]["reset_at"])
        self.assertIsNone(bus.data["codex"]["last_error"])

    def test_still_exhausted_probe_updates_real_response(self):
        class ProbeLimited:
            def probe_availability(self):
                raise sup.UsageResetRequired("new_limit", time.time() + 120)
        bus = sup.StatusBus({"codex": {"status": "USAGE_EXHAUSTED", "reset_at": time.time() - 1}})
        sup.refresh_provider_availability(bus, {"codex": ProbeLimited()}, ["codex"])
        self.assertEqual(bus.data["codex"]["status"], "USAGE_EXHAUSTED")
        self.assertEqual(bus.data["codex"]["last_error"], "new_limit")
        self.assertGreater(bus.data["codex"]["reset_at"], time.time())

    def test_unknown_reset_failed_probe_schedules_next_without_task_turn(self):
        class ProbeLimited:
            calls = 0
            def probe_availability(self):
                self.calls += 1
                raise sup.UsageResetRequired("still_limited", None)
        now = time.time()
        provider = ProbeLimited()
        bus = sup.StatusBus({"claude": {"status": "USAGE_EXHAUSTED", "reset_at": None, "next_availability_probe_at": now - 1}})
        sup.refresh_provider_availability(bus, {"claude": provider}, ["claude"])
        info = bus.data["claude"]
        self.assertEqual(provider.calls, 1)
        self.assertEqual(info["status"], "USAGE_EXHAUSTED")
        self.assertEqual(info["availability_probe_attempts"], 1)
        self.assertGreater(info["next_availability_probe_at"], time.time())
        sup.refresh_provider_availability(bus, {"claude": provider}, ["claude"])
        self.assertEqual(provider.calls, 1)

    def test_unknown_reset_success_clears_backoff_and_allows_handoff_target(self):
        class ProbeOK:
            def probe_availability(self): pass
        bus = sup.StatusBus({"claude": {
            "status": "USAGE_EXHAUSTED", "reset_at": None, "last_error": "claude_usage_limit",
            "availability_probe_attempts": 3, "next_availability_probe_at": time.time() - 1,
        }})
        recovered = sup.refresh_provider_availability(bus, {"claude": ProbeOK()}, ["claude"])
        info = bus.data["claude"]
        self.assertEqual(recovered, {"claude"})
        self.assertEqual(info["status"], "READY")
        self.assertIsNone(info["reset_at"])
        self.assertIsNone(info["last_error"])
        self.assertEqual(info["availability_probe_attempts"], 0)
        self.assertIsNone(info["next_availability_probe_at"])
        # This is the exact selection condition used by the pending structured
        # HANDOFF branch in main's waiting loop.
        self.assertTrue(sup.is_agent_usable(info, configured=True))

    def test_later_known_reset_replaces_unknown_reset_schedule(self):
        class ProbeLimitedWithReset:
            def probe_availability(self):
                raise sup.UsageResetRequired("limited", time.time() + 120)
        bus = sup.StatusBus({"claude": {
            "status": "USAGE_EXHAUSTED", "reset_at": None,
            "availability_probe_attempts": 2, "next_availability_probe_at": time.time() - 1,
        }})
        sup.refresh_provider_availability(bus, {"claude": ProbeLimitedWithReset()}, ["claude"])
        info = bus.data["claude"]
        self.assertGreater(info["reset_at"], time.time())
        self.assertEqual(info["availability_probe_attempts"], 0)
        self.assertIsNone(info["next_availability_probe_at"])


# ---------------------------------------------------------------------------
# 8b. Checkpoint atomic-replace retry (WinError 5/32 lock collision).
# ---------------------------------------------------------------------------

class TestCheckpointReplaceRetry(unittest.TestCase):
    """Reproduces the observed incident: a transient Windows lock on the
    checkpoint file (another reader has it open for a moment) previously
    raised PermissionError straight out of save_state() and crashed the
    whole supervisor mid-turn."""

    def test_transient_lock_is_retried_then_succeeds(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "state.json.tmp"
            destination = Path(directory) / "state.json"
            source.write_text("{}", encoding="utf-8")
            attempts = {"count": 0}
            real_replace = Path.replace

            def flaky_replace(self, target):
                attempts["count"] += 1
                if attempts["count"] < 3:
                    raise PermissionError(5, "Access is denied")
                return real_replace(self, target)

            with mock.patch.object(sup.time, "sleep", lambda _seconds: None), \
                 mock.patch.object(Path, "replace", flaky_replace):
                sup._replace_with_retry(source, destination)
            self.assertEqual(attempts["count"], 3)
            self.assertTrue(destination.exists())

    def test_persistent_lock_raises_after_exhausting_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "state.json.tmp"
            destination = Path(directory) / "state.json"
            source.write_text("{}", encoding="utf-8")

            def always_denied(self, target):
                raise PermissionError(5, "Access is denied")

            with mock.patch.object(sup.time, "sleep", lambda _seconds: None), \
                 mock.patch.object(Path, "replace", always_denied):
                with self.assertRaises(PermissionError):
                    sup._replace_with_retry(source, destination, attempts=3)


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

    def test_provider_neutral_task_owner(self):
        self.assertEqual(sup.supervisor_task_owner("TASK-012"), "supervisor-task-012")


class TestEfficiencyCheckpoint(unittest.TestCase):
    def test_compact_context_survives_handoff_prompt_without_history(self):
        state = {"task": "TASK-107", "phase": "IMPLEMENTATION", "compact_task_context": {
            "task_id": "TASK-107", "objective": "Build objective", "next_actions": ["targeted test"],
            "files_relevant": ["Scripts/example.py"], "validation_passed": ["focused test"],
        }}
        prompt = sup.build_continue_prompt("claude", state)
        self.assertIn('"task_id":"TASK-107"', prompt)
        self.assertIn("Inspect source only where needed", prompt)
        self.assertNotIn("checked-in roadmap completion state schedules", prompt)

    def test_changed_context_replaces_cached_summary(self):
        prior = {"objective": "old", "read_fingerprints": [{"path": "a.py", "summary": "old"}]}
        merged = sup.merge_compact_context(prior, {"objective": "new", "read_fingerprints": [{"path": "a.py", "fingerprint": "new", "summary": "new"}]}, "TASK-107", "TEST")
        self.assertEqual(merged["objective"], "new")
        self.assertEqual(merged["read_fingerprints"][0]["summary"], "new")

    def test_changed_file_invalidates_cached_summary(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(sup, "REPO", Path(directory)):
            target = Path(directory) / "a.py"
            target.write_text("old", encoding="utf-8")
            old = sup.path_fingerprint("a.py")
            target.write_text("new contents", encoding="utf-8")
            context = sup.invalidate_changed_read_summaries({"read_fingerprints": [{"path": "a.py", "fingerprint": old, "summary": "stale"}]})
            self.assertNotIn("summary", context["read_fingerprints"][0])
            self.assertTrue(context["read_fingerprints"][0]["changed"])

    def test_context_parser_rejects_non_json_and_bounds_lists(self):
        self.assertEqual(sup.parse_compact_context("SUPERVISOR_CONTEXT: nope"), {})
        text = "SUPERVISOR_CONTEXT: " + json.dumps({"next_actions": list(range(20))})
        self.assertEqual(len(sup.parse_compact_context(text)["next_actions"]), 12)

    def test_duplicate_failure_stops_blind_retry(self):
        state = {"task": "TASK-107", "phase": "TEST"}
        _, first = sup.record_failure(state, "build", "same error", ["a.py"])
        _, second = sup.record_failure(state, "build", "same error", ["a.py"])
        self.assertFalse(first)
        self.assertTrue(second)
        self.assertEqual(state["efficiency"]["repeated_failure_count"], 1)

    def test_efficiency_context_is_truthful_when_agent_omits_read_data(self):
        merged = sup.merge_compact_context({}, {}, "TASK-107", "IMPLEMENTATION")
        self.assertNotIn("read_fingerprints", merged)


class TestHostLockTransfer(unittest.TestCase):
    def test_transfer_is_atomic_and_preserves_single_owner(self):
        spec = importlib.util.spec_from_file_location("cots_host_mcp_test", SCRIPTS_DIR / "CotSHostMcp.py")
        host = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(host)
        with tempfile.TemporaryDirectory() as directory:
            original_dir, original_lock = host.STATE_DIR, host.LOCK_FILE
            host.STATE_DIR = Path(directory)
            host.LOCK_FILE = host.STATE_DIR / "mutation-lock.local.json"
            try:
                host.acquire({"agent_id": "codex-task-012"})
                result = host.transfer_lock({"agent_id": "codex-task-012", "target_agent_id": "supervisor-task-012"})
                self.assertTrue(result["success"])
                self.assertEqual(host.lock_owner(), "supervisor-task-012")
                self.assertFalse(host.acquire({"agent_id": "claude-task-012"})["success"])
            finally:
                host.STATE_DIR, host.LOCK_FILE = original_dir, original_lock


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

    def test_unknown_reset_status_shows_next_availability_probe(self):
        snapshot = {"state": "WAITING_FOR_AGENT_CAPACITY", "claude": {
            "status": "USAGE_EXHAUSTED", "reset_at": None,
            "next_availability_probe_at": time.time() + 60,
        }}
        lines = sup.render_frame_lines(snapshot)
        self.assertTrue(any("reset=unknown" in line for line in lines))
        self.assertTrue(any("next availability probe:" in line for line in lines))

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
# 12. Claude turn streaming/watchdogs (TASK-008C Claude-hang fix). Replaces
#     the opaque `subprocess.run(..., timeout=TURN_TIMEOUT_SECONDS)` design
#     that produced no visibility while a turn ran; see
#     Scripts/tests/fixtures/claude_stream_success.jsonl (a trimmed real
#     capture of the installed Claude Code 2.1.251 CLI's `--output-format
#     stream-json --verbose` shape) and CLAUDE_*_TIMEOUT_SECONDS' docstrings
#     for the live incident this repairs.
# ---------------------------------------------------------------------------

class TestClaudeStreamParsing(unittest.TestCase):
    def test_malformed_line_is_skipped_not_raised(self):
        self.assertIsNone(sup.try_parse_stream_line("not json {{{"))

    def test_valid_line_parses(self):
        obj = sup.try_parse_stream_line('{"type":"result","is_error":false}')
        self.assertEqual(obj["type"], "result")

    def test_tool_use_summary_is_bounded_and_correlates_tool_name(self):
        tool_names: dict[str, str] = {}
        obj = {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "toolu_1", "name": "Read", "input": {"file_path": "AGENTS.md"}},
        ]}}
        summary = sup.summarize_claude_stream_object(obj, tool_names)
        self.assertEqual(summary, "invoking Read(AGENTS.md)")
        self.assertEqual(tool_names["toolu_1"], "Read")

    def test_tool_result_summary_uses_correlated_tool_name(self):
        tool_names = {"toolu_1": "Bash"}
        obj = {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "..."}]}}
        summary = sup.summarize_claude_stream_object(obj, tool_names)
        self.assertEqual(summary, "Bash result received")

    def test_thinking_block_is_never_surfaced(self):
        obj = {"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "secret reasoning"}]}}
        self.assertIsNone(sup.summarize_claude_stream_object(obj, {}))

    def test_stream_event_partial_chunk_is_not_surfaced(self):
        # --include-partial-messages token-delta events: real activity (must
        # reset the no-activity watchdog upstream) but never a dashboard event.
        obj = {"type": "stream_event", "event": {"type": "content_block_delta"}}
        self.assertIsNone(sup.summarize_claude_stream_object(obj, {}))

    def test_bash_command_is_truncated_to_bounded_length(self):
        long_command = "python Scripts/CotS-GitCompletion.py " + ("x" * 200)
        obj = {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "toolu_2", "name": "Bash", "input": {"command": long_command}},
        ]}}
        summary = sup.summarize_claude_stream_object(obj, {})
        self.assertLess(len(summary), len(long_command))
        self.assertTrue(summary.endswith(")"))


class TestClaudeWatchdogs(unittest.TestCase):
    def test_no_trip_early_within_startup_window(self):
        self.assertIsNone(sup.claude_watchdog_trip(now=10, started_at=0, last_activity_at=0, saw_first_activity=False))

    def test_startup_timeout_trips_when_never_active(self):
        result = sup.claude_watchdog_trip(now=sup.CLAUDE_STARTUP_TIMEOUT_SECONDS + 1, started_at=0, last_activity_at=0, saw_first_activity=False)
        self.assertEqual(result, "STARTUP_TIMEOUT")

    def test_no_activity_timeout_trips_after_a_long_silent_gap(self):
        now = 10_000.0
        last_activity = now - sup.CLAUDE_NO_ACTIVITY_TIMEOUT_SECONDS - 1
        result = sup.claude_watchdog_trip(now=now, started_at=0, last_activity_at=last_activity, saw_first_activity=True)
        self.assertEqual(result, "NO_ACTIVITY_TIMEOUT")

    def test_recent_activity_does_not_trip_no_activity_timeout(self):
        result = sup.claude_watchdog_trip(now=100, started_at=0, last_activity_at=99, saw_first_activity=True)
        self.assertIsNone(result)

    def test_total_turn_timeout_trips_even_with_recent_activity(self):
        now = sup.CLAUDE_TOTAL_TURN_TIMEOUT_SECONDS + 1
        result = sup.claude_watchdog_trip(now=now, started_at=0, last_activity_at=now - 1, saw_first_activity=True)
        self.assertEqual(result, "TOTAL_TURN_TIMEOUT")

    def test_format_elapsed_hours_minutes_seconds(self):
        self.assertEqual(sup.format_elapsed(3 * 3600 + 12 * 60 + 5), "03:12:05")

    def test_format_elapsed_clamps_negative_to_zero(self):
        self.assertEqual(sup.format_elapsed(-5), "00:00:00")


class TestClaudeFailureClassification(unittest.TestCase):
    def test_auth_required_is_classified(self):
        self.assertEqual(sup.classify_claude_startup_failure("Error: Not authenticated. Please run /login.", 1), "AUTH_REQUIRED")

    def test_permission_required_is_classified(self):
        self.assertEqual(sup.classify_claude_startup_failure("Permission denied for tool Bash", 1), "PERMISSION_REQUIRED")

    def test_invalid_cli_args_is_config_error(self):
        # Real, live-confirmed shape (installed Claude Code 2.1.251, TASK-008C
        # repair): `claude -p ... --output-format stream-json` without
        # --verbose refuses to run with exactly this message.
        text = "Error: When using --print, --output-format=stream-json requires --verbose"
        self.assertEqual(sup.classify_claude_startup_failure(text, 1), "CONFIG_ERROR")

    def test_unsupported_permission_mode_is_config_error(self):
        self.assertEqual(sup.classify_claude_startup_failure("Error: unsupported permission mode 'weird'", 1), "CONFIG_ERROR")

    def test_unrecognized_stderr_is_transport_error_not_silently_ignored(self):
        self.assertEqual(sup.classify_claude_startup_failure("connection reset by peer", 1), "TRANSPORT_ERROR")


class TestDriveClaudeProcess(unittest.TestCase):
    def test_successful_streamed_turn_produces_result_and_bounded_events(self):
        lines = load_stream_fixture_lines("claude_stream_success.jsonl")
        process = FakeClaudeProcess(stdout_lines=lines, stderr_lines=[])
        bus = RecordingBus()
        result_obj, _stderr = sup._drive_claude_process(process, bus, None)
        self.assertIsNotNone(result_obj)
        self.assertEqual(result_obj["type"], "result")
        self.assertFalse(result_obj["is_error"])
        self.assertIn("Claude turn started", bus.events)
        self.assertTrue(any("invoking Read" in e for e in bus.events))
        self.assertTrue(any("Read result received" in e for e in bus.events))
        # Never leak thinking content or raw partial-stream deltas.
        self.assertFalse(any("thinking" in e.lower() for e in bus.events))
        self.assertFalse(any("content_block_delta" in e for e in bus.events))

    def test_malformed_line_among_valid_lines_does_not_crash(self):
        lines = [
            '{"type":"system","subtype":"init"}',
            "not json at all {{{",
            '{"type":"result","is_error":false,"subtype":"success","result":"ok","session_id":"s1","num_turns":1}',
        ]
        process = FakeClaudeProcess(stdout_lines=lines, stderr_lines=[])
        result_obj, _stderr = sup._drive_claude_process(process, None, None)
        self.assertEqual(result_obj["result"], "ok")

    def test_no_false_turn_started_before_any_line_arrives(self):
        process = FakeClaudeProcess(stdout_lines=[], stderr_lines=[], hang=True)
        bus = RecordingBus()
        with mock.patch.object(sup, "CLAUDE_STARTUP_TIMEOUT_SECONDS", 0.05):
            with self.assertRaises(sup.AppServerError):
                sup._drive_claude_process(process, bus, None)
        self.assertNotIn("Claude turn started", bus.events)
        self.assertTrue(process.terminated or process.killed)

    def test_no_activity_timeout_terminates_owned_process_and_raises_stalled(self):
        process = FakeClaudeProcess(stdout_lines=['{"type":"system","subtype":"init"}'], stderr_lines=[], hang=True)
        with mock.patch.object(sup, "CLAUDE_STARTUP_TIMEOUT_SECONDS", 30), \
             mock.patch.object(sup, "CLAUDE_NO_ACTIVITY_TIMEOUT_SECONDS", 0.05), \
             mock.patch.object(sup, "CLAUDE_TOTAL_TURN_TIMEOUT_SECONDS", 5.0):
            with self.assertRaises(sup.ProviderStalled):
                sup._drive_claude_process(process, None, None)
        self.assertTrue(process.terminated or process.killed)

    def test_stderr_activity_prevents_startup_timeout(self):
        # If stderr did not count as activity this would raise
        # STARTUP_TIMEOUT (AppServerError) instead of NO_ACTIVITY_TIMEOUT
        # (ProviderStalled) -- proving stderr resets the same clock as stdout.
        process = FakeClaudeProcess(stdout_lines=[], stderr_lines=["some diagnostic line"], hang=True)
        with mock.patch.object(sup, "CLAUDE_STARTUP_TIMEOUT_SECONDS", 30), \
             mock.patch.object(sup, "CLAUDE_NO_ACTIVITY_TIMEOUT_SECONDS", 0.05), \
             mock.patch.object(sup, "CLAUDE_TOTAL_TURN_TIMEOUT_SECONDS", 5.0):
            with self.assertRaises(sup.ProviderStalled):
                sup._drive_claude_process(process, None, None)

    def test_total_turn_timeout_fires_even_with_recent_activity(self):
        process = FakeClaudeProcess(stdout_lines=['{"type":"system","subtype":"init"}'], stderr_lines=[], hang=True)
        with mock.patch.object(sup, "CLAUDE_STARTUP_TIMEOUT_SECONDS", 30), \
             mock.patch.object(sup, "CLAUDE_NO_ACTIVITY_TIMEOUT_SECONDS", 100), \
             mock.patch.object(sup, "CLAUDE_TOTAL_TURN_TIMEOUT_SECONDS", 0.05):
            with self.assertRaises(sup.AppServerError) as ctx:
                sup._drive_claude_process(process, None, None)
        self.assertIn("claude_turn_timeout", str(ctx.exception))
        self.assertTrue(process.terminated or process.killed)

    def test_ctrl_c_mid_turn_terminates_owned_process_and_raises_shutdown(self):
        process = FakeClaudeProcess(stdout_lines=[], stderr_lines=[], hang=True)
        shutdown_event = threading.Event()
        shutdown_event.set()
        with self.assertRaises(sup.Shutdown):
            sup._drive_claude_process(process, None, shutdown_event)
        self.assertTrue(process.terminated or process.killed)

    def test_dashboard_heartbeat_shows_elapsed_time_format(self):
        process = FakeClaudeProcess(stdout_lines=['{"type":"system","subtype":"init"}'], stderr_lines=[], hang=True)
        bus = RecordingBus()
        with mock.patch.object(sup, "CLAUDE_HEARTBEAT_SECONDS", 0.01), \
             mock.patch.object(sup, "CLAUDE_STARTUP_TIMEOUT_SECONDS", 30), \
             mock.patch.object(sup, "CLAUDE_NO_ACTIVITY_TIMEOUT_SECONDS", 0.3), \
             mock.patch.object(sup, "CLAUDE_TOTAL_TURN_TIMEOUT_SECONDS", 5.0):
            with self.assertRaises(sup.ProviderStalled):
                sup._drive_claude_process(process, bus, None)
        self.assertTrue(any("elapsed " in action for action in bus.current_actions))


class TestOwnedProcessTermination(unittest.TestCase):
    def test_only_the_exact_passed_process_is_touched(self):
        target = FakeClaudeProcess(stdout_lines=[], stderr_lines=[], hang=True)
        other = FakeClaudeProcess(stdout_lines=[], stderr_lines=[], hang=True)
        sup._terminate_owned_process(target)
        self.assertTrue(target.terminated)
        self.assertFalse(other.terminated)
        self.assertFalse(other.killed)

    def test_already_exited_process_is_left_alone(self):
        process = FakeClaudeProcess(stdout_lines=[], stderr_lines=[], hang=False, exit_code=0)
        sup._terminate_owned_process(process)
        self.assertFalse(process.terminated)
        self.assertFalse(process.killed)

    def test_escalates_to_kill_if_terminate_does_not_exit_in_time(self):
        class StubbornProcess(FakeClaudeProcess):
            def terminate(self):
                self.terminated = True  # ignores "SIGTERM": stays "alive"

            def wait(self, timeout=None):
                if not self.killed:
                    raise sup.subprocess.TimeoutExpired(cmd="claude", timeout=timeout or 0)
                return self._exit_code

        process = StubbornProcess(stdout_lines=[], stderr_lines=[], hang=True)
        sup._terminate_owned_process(process)
        self.assertTrue(process.terminated)
        self.assertTrue(process.killed)


class TestClaudeAgentRunTurn(unittest.TestCase):
    def _agent_with_popen(self, process: FakeClaudeProcess) -> "sup.ClaudeAgent":
        agent = sup.ClaudeAgent()
        patcher = mock.patch.object(sup.subprocess, "Popen", return_value=process)
        patcher.start()
        self.addCleanup(patcher.stop)
        return agent

    def test_successful_turn_captures_session_id(self):
        lines = load_stream_fixture_lines("claude_stream_success.jsonl")
        agent = self._agent_with_popen(FakeClaudeProcess(stdout_lines=lines, stderr_lines=[]))
        result = agent.run_turn("continue")
        self.assertEqual(agent.session_id, "097a57a1-c9b9-4bae-971c-059635554f77")
        self.assertFalse(result.is_suspicious())

    def test_second_turn_resumes_captured_session_id(self):
        lines = load_stream_fixture_lines("claude_stream_success.jsonl")
        captured_args: list[list[str]] = []

        def fake_popen(args, **kwargs):
            captured_args.append(args)
            return FakeClaudeProcess(stdout_lines=lines, stderr_lines=[])

        with mock.patch.object(sup.subprocess, "Popen", side_effect=fake_popen):
            agent = sup.ClaudeAgent()
            agent.run_turn("first")
            agent.run_turn("second")
        self.assertNotIn("--resume", captured_args[0])
        self.assertIn("--resume", captured_args[1])
        resume_index = captured_args[1].index("--resume")
        self.assertEqual(captured_args[1][resume_index + 1], "097a57a1-c9b9-4bae-971c-059635554f77")

    def test_mcp_allowlist_exposes_only_the_fixed_host_surface_and_unreal_server(self):
        allowed = sup.CLAUDE_ALLOWED_TOOLS.split()
        self.assertIn("mcp__cots-host__GetToolLabStatus", allowed)
        self.assertIn("mcp__cots-host__RunCotSAutomation", allowed)
        self.assertIn("mcp__unreal-mcp__*", allowed)
        self.assertFalse(any(item.startswith("mcp__cots-host__") and item.endswith("*") for item in allowed))

    def test_allowlist_exposes_the_shared_task_runner(self):
        allowed = sup.CLAUDE_ALLOWED_TOOLS.split()
        self.assertIn("Bash(Scripts\\Run-CotSTask.cmd", " ".join(allowed))

    def test_auth_required_stderr_raises_authentication_required(self):
        process = FakeClaudeProcess(stdout_lines=[], stderr_lines=["Error: Not authenticated. Please run /login."], exit_code=1)
        agent = self._agent_with_popen(process)
        with self.assertRaises(sup.AuthenticationRequired):
            agent.run_turn("continue")

    def test_invalid_cli_args_raises_non_transient_turn_failed(self):
        process = FakeClaudeProcess(
            stdout_lines=[],
            stderr_lines=["Error: When using --print, --output-format=stream-json requires --verbose"],
            exit_code=1,
        )
        agent = self._agent_with_popen(process)
        with self.assertRaises(sup.TurnFailed) as ctx:
            agent.run_turn("continue")
        self.assertFalse(ctx.exception.transient)

    def test_usage_limit_detected_from_streamed_result_payload(self):
        payload = load_json_fixture("claude_usage_limit.json")
        line = json.dumps({**payload, "type": "result"})
        process = FakeClaudeProcess(stdout_lines=['{"type":"system","subtype":"init"}', line], stderr_lines=[])
        agent = self._agent_with_popen(process)
        with self.assertRaises(sup.UsageResetRequired):
            agent.run_turn("continue")

    def test_error_during_execution_is_transient_and_retryable(self):
        # The exact shape of the live TASK-008C incident (.cots/claude-
        # protocol.log, 2026-08-30 02:30-02:39): a real, substantial turn
        # (num_turns=13/20) that ended with is_error/subtype=
        # error_during_execution. Must stay transient=True (bounded retry),
        # not become a terminal FAILED.
        payload = {
            "type": "result", "is_error": True, "subtype": "error_during_execution",
            "api_error_status": None, "result": "aborted", "session_id": "s2", "num_turns": 13,
        }
        process = FakeClaudeProcess(stdout_lines=['{"type":"system","subtype":"init"}', json.dumps(payload)], stderr_lines=[])
        agent = self._agent_with_popen(process)
        with self.assertRaises(sup.TurnFailed) as ctx:
            agent.run_turn("continue")
        self.assertTrue(ctx.exception.transient)


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
