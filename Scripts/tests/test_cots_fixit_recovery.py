"""Deterministic contract coverage for the external FixIt recovery layer."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]

def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec); assert spec.loader
    spec.loader.exec_module(module)
    return module

recovery = load("CotSRecovery")
fixit = load("CotSAgentFixIt")
bootstrap = load("CotSFactoryBootstrap")


class Result:
    def __init__(self, text): self.stdout, self.stderr, self.returncode = text, "", 0


class Process:
    def __init__(self, code): self.code = code
    def wait(self): return self.code


class TestIncidentContract(unittest.TestCase):
    def test_structured_incident_is_durable_and_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); incidents = root / "incidents"
            checkpoint = {"task": "TASK-012", "phase": "proof", "state": "FAILED", "recent_events": ["x" * 900] * 20}
            with mock.patch.object(recovery, "INCIDENTS", incidents), mock.patch.object(recovery, "COTS", root), mock.patch.object(recovery, "SUPERVISOR_STATE", root / "checkpoint.json"), mock.patch.object(recovery, "FACTORY_STATE", root / "factory.json"), mock.patch.object(recovery, "fixed_git", return_value="head"):
                path = recovery.write_incident(recovery.IncidentCategory.SUPERVISOR, "broken", affected_component="supervisor", checkpoint=checkpoint)
            data = json.loads(path.read_text())
            self.assertEqual(data["category"], "SUPERVISOR"); self.assertEqual(data["task_id"], "TASK-012")
            self.assertLessEqual(len(data["relevant_recent_events"]), recovery.MAX_EVENTS)
            self.assertLessEqual(len(data["bounded_relevant_log_excerpt"]), recovery.MAX_INCIDENT_LOG)

    def test_historical_regression_fixture_categories_are_stable(self):
        fixtures = json.loads((SCRIPTS / "tests" / "fixtures" / "fixit_known_incidents.json").read_text())
        self.assertGreaterEqual(len(fixtures), 16)
        for fixture in fixtures:
            self.assertIn(fixture["category"], {item.value for item in recovery.IncidentCategory}, fixture["name"])


class TestFixIt(unittest.TestCase):
    def test_provider_selection_prefers_other_provider_then_alternates_third(self):
        with mock.patch.object(fixit, "read_json", return_value={"active_agent": "codex"}):
            self.assertEqual(fixit.select_provider({"provider_state": {}}, 1, {"codex", "claude"}), "claude")
            self.assertEqual(fixit.select_provider({"provider_state": {}}, 3, {"codex", "claude"}), "codex")

    def test_success_preserves_commit_resume_and_validation(self):
        incident = {"incident_id": "abc", "task_id": "TASK-012", "checkpoint_path": str(fixit.SUPERVISOR_STATE)}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "incident.json"; path.write_text(json.dumps(incident))
            with mock.patch.object(fixit, "select_provider", return_value="codex"), mock.patch.object(fixit, "validate", return_value=(True, "")), mock.patch.object(fixit, "atomic_json"):
                result = fixit.run_incident(path, 1, runner=lambda *a, **k: Result("FIXIT_RESULT: SUCCESS\nFIXIT_COMMIT: abc1234\nFIXIT_RESTART_COMPONENTS: factory,supervisor,host_mcp\nFIXIT_RESUME_TASK: TASK-012"))
        self.assertEqual(result["result"], "SUCCESS"); self.assertEqual(result["commit"], "abc1234")
        self.assertEqual(result["resume_task"], "TASK-012")

    def test_human_required_and_retryable_results_parse(self):
        self.assertEqual(fixit.parse_result("FIXIT_RESULT: HUMAN_REQUIRED", {})["result"], "HUMAN_REQUIRED")
        self.assertEqual(fixit.parse_result("broken", {})["result"], "RETRYABLE_FAILURE")

    def test_active_mutating_agent_blocks_concurrent_repair(self):
        self.assertTrue(fixit.active_mutator({"state": "RUNNING_CLAUDE", "active_agent": "claude"}))
        self.assertFalse(fixit.active_mutator({"state": "WAITING_FOR_AGENT_CAPACITY", "active_agent": None}))


class TestBootstrap(unittest.TestCase):
    def test_success_restarts_factory_and_resumes_same_task(self):
        calls = []
        def popen(*_args, **_kwargs):
            calls.append("factory"); return Process(recovery.RECOVERABLE_EXIT if len(calls) == 1 else 0)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); incident = root / "inc.json"; incident.write_text("{}")
            result = root / "result.json"; result.write_text(json.dumps({"result": "SUCCESS", "resume_task": "TASK-012"}))
            with mock.patch.object(bootstrap, "latest_incident", return_value=incident), mock.patch.object(bootstrap, "RESULT_PATH", result, create=True), mock.patch.object(bootstrap, "COTS", root), mock.patch.object(bootstrap, "FACTORY_STATE", root / "factory.json"), mock.patch.object(bootstrap, "set_recovery"), mock.patch.object(bootstrap, "read_json", return_value={"result": "SUCCESS", "resume_task": "TASK-012"}):
                self.assertEqual(bootstrap.run(popen=popen, runner=lambda *a, **k: Result("FIXIT_RESULT: SUCCESS")), 0)
        self.assertEqual(calls, ["factory", "factory"])

    def test_retries_escalate_on_third_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); incident = root / "incident.json"; incident.write_text("{}")
            cots = root / ".cots"; cots.mkdir(); (cots / "fixit-result.local.json").write_text(json.dumps({"result": "RETRYABLE_FAILURE"}))
            with mock.patch.object(bootstrap, "COTS", cots), mock.patch.object(bootstrap, "FACTORY_STATE", root / "factory.json"), mock.patch.object(bootstrap, "latest_incident", return_value=incident), mock.patch.object(bootstrap, "set_recovery") as saved:
                self.assertEqual(bootstrap.run(popen=lambda *a, **k: Process(recovery.RECOVERABLE_EXIT), runner=lambda *a, **k: Result("")), recovery.HUMAN_REQUIRED_EXIT)
        self.assertTrue(any(call.args[1] == "HUMAN_REQUIRED" for call in saved.call_args_list))
