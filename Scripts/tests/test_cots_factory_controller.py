import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("factory", SCRIPTS / "CotSFactoryController.py")
factory = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(factory)


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
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(factory, "STATE_PATH", Path(directory) / "factory.json"):
            controller = factory.FactoryController(); target, other = FakeProcess(), FakeProcess(pid=456)
            controller.stop_owned(target, "supervisor")
            self.assertTrue(target.terminated); self.assertFalse(other.terminated)
    def test_supervisor_command_is_fixed(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(factory, "STATE_PATH", Path(directory) / "factory.json"), mock.patch.object(factory.subprocess, "Popen", return_value=FakeProcess()) as popen:
            controller = factory.FactoryController(); controller.start_supervisor("repair", "claude,codex")
            args = popen.call_args.args[0]
            self.assertIn(str(factory.SUPERVISOR_SCRIPT), args); self.assertIn("--max-turns", args); self.assertNotIn("shell", popen.call_args.kwargs)


if __name__ == "__main__": unittest.main()
