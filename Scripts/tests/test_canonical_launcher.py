from __future__ import annotations

import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1]


class CanonicalLauncherTests(unittest.TestCase):
    def test_canonical_launcher_owns_the_campaign_path(self) -> None:
        text = (SCRIPTS / "Launch-CotS.bat").read_text(encoding="utf-8")
        self.assertIn("CotSWatchdogCampaign.py", text)
        self.assertIn("CotSControlCenter.py", text)
        self.assertNotIn("CotSWatchdog24x7Final.py", text)

    def test_legacy_launchers_are_explicit_redirects(self) -> None:
        for name in ("Launch-CotS-24x7.bat", "Launch-CotS-Campaign-Control-Center.bat"):
            text = (SCRIPTS / name).read_text(encoding="utf-8")
            self.assertIn("Legacy launcher", text)
            self.assertIn("Launch-CotS.bat", text)

    def test_control_center_fallback_keeps_campaign_scheduler(self) -> None:
        text = (SCRIPTS / "CotSControlCenter.py").read_text(encoding="utf-8")
        self.assertIn("CotSWatchdogCampaign.py", text)

    def test_scheduled_task_uses_campaign_watchdog(self) -> None:
        text = (SCRIPTS / "Install-CotS24x7.ps1").read_text(encoding="utf-8")
        self.assertIn('"CotSWatchdogCampaign.py"', text)


if __name__ == "__main__":
    unittest.main()
