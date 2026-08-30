import importlib.util
import json
import io
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("factory", SCRIPTS / "CotSFactoryController.py")
factory = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(factory)

dashboard_spec = importlib.util.spec_from_file_location("factory_dashboard", SCRIPTS / "CotSFactoryDashboard.py")
dashboard = importlib.util.module_from_spec(dashboard_spec)
assert dashboard_spec.loader is not None
dashboard_spec.loader.exec_module(dashboard)


class FakeProcess:
    def __init__(self, pid=123, exit_code=None): self.pid, self.exit_code, self.terminated, self.killed = pid, exit_code, False, False
    def poll(self): return self.exit_code
    def terminate(self): self.terminated = True; self.exit_code = 0
    def kill(self): self.killed = True; self.exit_code = -9
    def wait(self, timeout=None): return self.exit_code


class TestGateClassification(unittest.TestCase):
    def test_structured_category_is_authoritative(self):
        category, reason, action = factory.classify_gate({"recoverable_gate": {"category": "RECOVERABLE_HOST_MCP", "reason": "missing session", "recommended_action": "restart"}})
        self.assertEqual(category, factory.GateCategory.RECOVERABLE_HOST_MCP); self.assertEqual(reason, "missing session"); self.assertEqual(action, "restart")
    def test_recursive_validation_is_recoverable(self):
        category, _, action = factory.classify_gate({"state": "HUMAN_GATE", "human_gate": "nested `codex exec` cannot reach network"})
        self.assertEqual(category, factory.GateCategory.RECOVERABLE_VALIDATION_TOPOLOGY); self.assertEqual(action, "use_active_adapter")
    def test_authentication_remains_human_required(self):
        category, _, _ = factory.classify_gate({"state": "HUMAN_GATE", "human_gate": "MFA login required"})
        self.assertEqual(category, factory.GateCategory.HUMAN_REQUIRED)
    def test_unstructured_failure_restarts_supervisor(self):
        category, _, _ = factory.classify_gate({"state": "FAILED", "failure": "app server exited"}, 1)
        self.assertEqual(category, factory.GateCategory.RECOVERABLE_SUPERVISOR)
    def test_unknown_gate_fails_closed(self):
        category, _, _ = factory.classify_gate({"state": "HUMAN_GATE", "human_gate": "choose game design"})
        self.assertEqual(category, factory.GateCategory.TERMINAL_FAILURE)


class TestRecoveryPolicy(unittest.TestCase):
    def test_fingerprint_includes_task_and_phase(self):
        first = factory.incident_fingerprint(factory.GateCategory.RECOVERABLE_BUILD_TEST, "failed", {"task": "TASK-001", "phase": "test"})
        second = factory.incident_fingerprint(factory.GateCategory.RECOVERABLE_BUILD_TEST, "failed", {"task": "TASK-002", "phase": "test"})
        self.assertNotEqual(first, second)
    def test_alternate_provider_is_preferred(self):
        state = {"active_agent": "codex", "codex": {"status": "ACTIVE"}, "claude": {"status": "IDLE"}}
        self.assertEqual(factory.choose_repair_agents(state), "claude,codex")
    def test_repair_prompt_requires_validation_and_preserves_task(self):
        prompt = factory.repair_prompt({"task": "TASK-001", "reason": "nested", "checkpoint": {}}, 2)
        self.assertIn("TASK-001", prompt); self.assertIn("py_compile", prompt); self.assertIn("CotS-GitCompletion.py", prompt); self.assertIn("Do not write Shardlands", prompt)

    def test_repair_prompt_is_bounded_to_relevant_incident(self):
        prompt = factory.repair_prompt({"task": "TASK-001", "reason": "broken", "checkpoint": {"compact_task_context": {"next_actions": ["fix"]}}, "codex_protocol": "x" * 9000}, 1)
        self.assertIn("BOUNDED INCIDENT EVIDENCE", prompt)
        self.assertLess(len(prompt), 8000)
    def test_bounded_attempts_escalate_without_repair(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(factory, "STATE_PATH", Path(directory) / "factory.json"), mock.patch.object(factory, "SUPERVISOR_STATE", Path(directory) / "supervisor.json"):
            checkpoint = {"state": "HUMAN_GATE", "human_gate": "nested `codex exec` cannot reach network", "task": "TASK-001"}
            factory.SUPERVISOR_STATE.write_text(json.dumps(checkpoint), encoding="utf-8")
            controller = factory.FactoryController(); category, reason, _ = factory.classify_gate(checkpoint)
            controller.state["repair_attempts"][factory.incident_fingerprint(category, reason, checkpoint)] = factory.MAX_REPAIR_ATTEMPTS
            with mock.patch.object(controller, "start_supervisor") as start:
                self.assertFalse(controller.handle_gate(0)); start.assert_not_called()
            self.assertEqual(controller.state["factory"], "HUMAN_REQUIRED")


class TestOwnedProcesses(unittest.TestCase):
    def test_stop_owned_touches_only_given_process(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(factory, "STATE_PATH", Path(directory) / "factory.json"), mock.patch.object(factory.subprocess, "run"):
            controller = factory.FactoryController(); target, other = FakeProcess(), FakeProcess(pid=456)
            controller.stop_owned(target, "supervisor")
            self.assertTrue(target.terminated); self.assertFalse(other.terminated)

    def test_stop_owned_sweeps_process_tree_on_windows(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(factory, "STATE_PATH", Path(directory) / "factory.json"), mock.patch.object(factory.sys, "platform", "win32"), mock.patch.object(factory.subprocess, "run") as run:
            controller = factory.FactoryController(); target = FakeProcess(pid=789)
            controller.stop_owned(target, "supervisor")
            run.assert_called_once()
            args = run.call_args.args[0]
            self.assertEqual(args[0], "taskkill"); self.assertIn("789", args); self.assertIn("/T", args); self.assertIn("/F", args)

    def test_stop_owned_skips_taskkill_off_windows(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(factory, "STATE_PATH", Path(directory) / "factory.json"), mock.patch.object(factory.sys, "platform", "linux"), mock.patch.object(factory.subprocess, "run") as run:
            controller = factory.FactoryController(); target = FakeProcess(pid=789)
            controller.stop_owned(target, "supervisor")
            run.assert_not_called()
    def test_supervisor_command_is_fixed(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(factory, "STATE_PATH", Path(directory) / "factory.json"), mock.patch.object(factory.subprocess, "Popen", return_value=FakeProcess()) as popen:
            controller = factory.FactoryController(); controller.start_supervisor("repair", "claude,codex")
            args = popen.call_args.args[0]
            self.assertIn(str(factory.SUPERVISOR_SCRIPT), args); self.assertIn("--max-turns", args); self.assertNotIn("shell", popen.call_args.kwargs)


class TestSupervisorLifecycleMonitoring(unittest.TestCase):
    def controller_for_checkpoint(self, directory, checkpoint, process=None):
        state_path = Path(directory) / "factory.json"
        supervisor_path = Path(directory) / "supervisor.json"
        supervisor_path.write_text(json.dumps(checkpoint), encoding="utf-8")
        patches = mock.patch.object(factory, "STATE_PATH", state_path), mock.patch.object(factory, "SUPERVISOR_STATE", supervisor_path)
        return patches, process or FakeProcess()

    def test_active_states_are_nonterminal(self):
        states = ("RUNNING_CODEX", "RUNNING_CLAUDE", "RECONCILING", "ROTATING_AGENT", "WAITING_FOR_AGENT_CAPACITY")
        with tempfile.TemporaryDirectory() as directory:
            for state in states:
                with self.subTest(state=state):
                    patches, process = self.controller_for_checkpoint(directory, {"state": state, "updated_at": 1000.0})
                    with patches[0], patches[1]:
                        controller = factory.FactoryController(); controller.supervisor = process
                        controller.state["supervisor_started_at"] = 900.0
                        self.assertEqual(controller.live_supervisor_boundary(now=1001.0), (None, None))
                        self.assertFalse(process.terminated)

    def test_unknown_fresh_state_does_not_kill_supervisor(self):
        with tempfile.TemporaryDirectory() as directory:
            patches, process = self.controller_for_checkpoint(directory, {"state": "FUTURE_PROVIDER_PHASE", "updated_at": 1000.0})
            with patches[0], patches[1]:
                controller = factory.FactoryController(); controller.supervisor = process
                controller.state["supervisor_started_at"] = 900.0
                self.assertEqual(controller.live_supervisor_boundary(now=1001.0), (None, None))
                self.assertFalse(process.terminated)

    def test_actual_child_exit_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            patches, process = self.controller_for_checkpoint(directory, {"state": "RUNNING_CLAUDE", "updated_at": 1000.0}, FakeProcess(exit_code=1))
            with patches[0], patches[1]:
                controller = factory.FactoryController(); controller.supervisor = process
                category, reason = controller.live_supervisor_boundary(now=1001.0)
                self.assertEqual(category, factory.GateCategory.RECOVERABLE_SUPERVISOR)
                self.assertIn("exited", reason)

    def test_stale_heartbeat_triggers_bounded_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            patches, process = self.controller_for_checkpoint(directory, {"state": "RUNNING_CLAUDE", "updated_at": 1.0})
            with patches[0], patches[1]:
                controller = factory.FactoryController(); controller.supervisor = process
                category, reason = controller.live_supervisor_boundary(now=1.0 + factory.CHECKPOINT_STALE_SECONDS + 1)
                self.assertEqual(category, factory.GateCategory.RECOVERABLE_STALE_STATE)
                self.assertIn("stale", reason)

    def test_recoverable_gate_schedules_repair(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(factory, "STATE_PATH", Path(directory) / "factory.json"), mock.patch.object(factory, "SUPERVISOR_STATE", Path(directory) / "supervisor.json"):
            checkpoint = {"state": "RECOVERABLE_GATE", "recoverable_gate": {"category": "RECOVERABLE_HOST_MCP", "reason": "host unavailable", "recommended_action": "restart"}}
            factory.SUPERVISOR_STATE.write_text(json.dumps(checkpoint), encoding="utf-8")
            controller = factory.FactoryController()
            with mock.patch.object(controller, "start_supervisor") as start, mock.patch.object(controller, "capture", return_value={"task": "TASK-004"}):
                self.assertTrue(controller.handle_gate(0))
                start.assert_called_once()

    def test_human_required_and_complete_are_terminal_cleanly(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(factory, "STATE_PATH", Path(directory) / "factory.json"), mock.patch.object(factory, "SUPERVISOR_STATE", Path(directory) / "supervisor.json"):
            factory.SUPERVISOR_STATE.write_text(json.dumps({"state": "HUMAN_GATE", "human_gate": "choose game design"}), encoding="utf-8")
            controller = factory.FactoryController()
            self.assertFalse(controller.handle_gate(0))
            self.assertEqual(controller.state["factory"], "HUMAN_REQUIRED")
            factory.SUPERVISOR_STATE.write_text(json.dumps({"state": "COMPLETE"}), encoding="utf-8")
            controller = factory.FactoryController()
            self.assertFalse(controller.handle_gate(0))
            self.assertEqual(controller.state["factory"], "COMPLETE")


class TestHostDisconnectNoise(unittest.TestCase):
    def test_loopback_connection_reset_is_logged_without_traceback(self):
        host_spec = importlib.util.spec_from_file_location("host_for_disconnect_test", SCRIPTS / "CotSHostMcp.py")
        host = importlib.util.module_from_spec(host_spec)
        assert host_spec.loader is not None
        host_spec.loader.exec_module(host)
        handler = object.__new__(host.Handler)
        handler.client_address = ("127.0.0.1", 8010)
        handler.send_response = lambda *_args: None
        handler.send_header = lambda *_args: None
        handler.end_headers = lambda: None
        handler.wfile = mock.Mock()
        handler.wfile.write.side_effect = ConnectionResetError("controlled disconnect")
        with self.assertLogs(host.LOGGER, "DEBUG") as logs:
            handler.reply(200, {"ok": True})
        self.assertIn("Loopback MCP client disconnected", "\n".join(logs.output))


class TtyBuffer(io.StringIO):
    def isatty(self): return True


class TestFactoryDashboard(unittest.TestCase):
    def snapshot(self, **overrides):
        value = {
            "factory": "RUNNING", "started_at": time.time() - 10, "supervisor_state": "RUNNING_CODEX",
            "host_state": "READY", "git_branch": "main", "git_status": "clean", "last_commit": "123abcd Subject",
            "supervisor": {"state": "RUNNING_CODEX", "task": "TASK-001", "task_title": "Shared Task Runner",
                           "phase": "VALIDATION", "current_action": "Reading validation", "updated_at": time.time() - 5,
                           "active_agent": "codex", "preferred_agent": "codex", "turn_count": 3, "rotation_count": 1,
                           "codex": {"status": "ACTIVE", "version": "0.1"}, "claude": {"status": "IDLE", "version": "2.0"}},
            "recent_events": ["07:42:11  Codex turn started"],
        }
        value.update(overrides)
        return value

    def test_spinner_progression_and_state_mapping(self):
        self.assertNotEqual(dashboard.spinner_frame(0), dashboard.spinner_frame(1))
        self.assertEqual(dashboard.status_style("RUNNING_CODEX"), ("WORKING", "cyan"))
        self.assertEqual(dashboard.status_style("HUMAN_REQUIRED"), ("HUMAN_REQUIRED", "red"))
        self.assertEqual(dashboard.status_style("FAILED"), ("FAILED", "red"))
        self.assertEqual(dashboard.status_style("COMPLETE"), ("COMPLETE", "green"))

    def test_task_title_phase_and_terminal_states_render(self):
        rendered = dashboard.render_frame(self.snapshot(), width=90)
        self.assertIn("TASK-001", rendered); self.assertIn("Shared Task Runner", rendered); self.assertIn("VALIDATION", rendered)
        self.assertIn("COMPLETE", dashboard.render_frame(self.snapshot(factory="COMPLETE"), width=90))
        self.assertIn("HUMAN_REQUIRED", dashboard.render_frame(self.snapshot(factory="HUMAN_REQUIRED"), width=90))
        self.assertIn("FAILED", dashboard.render_frame(self.snapshot(factory="FAILED"), width=90))

    def test_recovery_section_is_conditional(self):
        self.assertNotIn("Recovery\n", dashboard.render_frame(self.snapshot(), width=90))
        recovered = self.snapshot(recovery={"state": "REPAIRING", "category": "RECOVERABLE_HOST_MCP", "incident": "abc", "attempt": 2, "reason": "host down"})
        rendered = dashboard.render_frame(recovered, width=90)
        self.assertIn("Recovery", rendered); self.assertIn("RECOVERABLE_HOST_MCP", rendered); self.assertIn("Attempt 2/3", rendered)

    def test_efficiency_telemetry_renders_checkpoint_facts(self):
        snapshot = self.snapshot()
        snapshot["supervisor"]["efficiency"] = {"task_turns": 3, "files_newly_read_this_turn": 12, "files_reread_unchanged": 1, "targeted_test_runs": 5, "full_suite_runs": 0, "repeated_failure_count": 0}
        rendered = dashboard.render_frame(snapshot, width=100)
        self.assertIn("Efficiency", rendered)
        self.assertIn("Targeted tests 5", rendered)

    def test_events_are_human_safe_and_bounded(self):
        rendered = dashboard.render_frame(self.snapshot(recent_events=["\x1b[31m{\"jsonrpc\":\"2.0\"}\nRaw" for _ in range(20)]), width=90)
        self.assertNotIn("\x1b", rendered); self.assertNotIn("\nRaw", rendered)
        self.assertNotIn("jsonrpc", rendered)

    def test_shorter_redraw_erases_rows_and_plain_fallback_has_no_ansi(self):
        stream = TtyBuffer(); sink = dashboard.TerminalDashboard(stream, color=True)
        sink.draw(self.snapshot(supervisor={"current_action": "x" * 300}))
        sink.draw(self.snapshot(supervisor={"current_action": "done"}))
        self.assertGreaterEqual(stream.getvalue().count("\x1b[K"), 2)
        plain = io.StringIO(); dashboard.TerminalDashboard(plain, color=False).draw(self.snapshot())
        self.assertNotIn("\x1b", plain.getvalue())


if __name__ == "__main__": unittest.main()
