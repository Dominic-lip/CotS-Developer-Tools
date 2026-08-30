import unittest
from pathlib import Path


LAUNCHER = Path(__file__).resolve().parents[1] / "Launch-CotS-Agents.bat"


class TestLaunchCotSAgents(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = LAUNCHER.read_text(encoding="utf-8").replace("\r\n", "\n")

    def section(self, start: str, end: str) -> str:
        return self.text.split(start, 1)[1].split(end, 1)[0]

    def test_trusted_manual_mode_uses_current_invocation_local_permissions(self):
        trusted = self.section(":manual_trusted", ":manual_safe")
        self.assertIn("CotS Manual Codex", trusted)
        self.assertIn("TRUSTED WORKSPACE", trusted)
        self.assertIn("Routine approvals disabled.", trusted)
        self.assertIn("codex --ask-for-approval never --sandbox danger-full-access", trusted)
        self.assertNotIn("untrusted", trusted.lower())

    def test_safe_manual_mode_preserves_default_approvals(self):
        safe = self.text.split(":manual_safe", 1)[1]
        self.assertIn("SAFE MODE", safe)
        self.assertIn("codex --cd", safe)
        self.assertNotIn("--ask-for-approval", safe)
        self.assertNotIn("--sandbox", safe)

    def test_factory_path_uses_stable_bootstrap(self):
        factory = self.text.split("if /I \"%1\"==\"manual-safe\" goto manual_safe", 1)[1].split(":manual_trusted", 1)[0]
        self.assertIn('start "CotS Autonomous Factory" cmd /k python "%~dp0CotSFactoryBootstrap.py"', factory)
        self.assertNotIn("danger-full-access", factory)


if __name__ == "__main__":
    unittest.main()
