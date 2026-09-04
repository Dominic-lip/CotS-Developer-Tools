#!/usr/bin/env python3
from __future__ import annotations

import http.client
import json
import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import CotSProductionHostBridge as bridge
import CotSProductionLifecycleCampaign as campaign


class TestProductionHostBridge(unittest.TestCase):
    def test_campaign_authorization_preserves_read_only_task_116(self) -> None:
        campaign.install_campaign()
        self.assertNotIn("TASK-116", campaign.base.ALLOWED_TASKS)
        for task in range(117, 122):
            self.assertIn(f"TASK-{task}", campaign.base.ALLOWED_TASKS)

    def test_transport_validation_is_bounded(self) -> None:
        self.assertEqual(bridge.validate_argv(["status"]), ["status"])
        with self.assertRaises(ValueError):
            bridge.validate_argv([])
        with self.assertRaises(ValueError):
            bridge.validate_argv(["../cmd"])
        with self.assertRaises(ValueError):
            bridge.validate_argv(["apply-manifest", "bad\nname.json"])

    def test_loopback_health_requires_token(self) -> None:
        service = bridge.ProductionHostBridge(port=0)
        service.start()
        try:
            assert service.httpd is not None
            port = int(service.httpd.server_address[1])
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            connection.request("GET", "/health")
            response = connection.getresponse(); response.read()
            self.assertEqual(response.status, 403)
            connection.close()

            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            connection.request("GET", "/health", headers={"X-CotS-Production-Token": service.token})
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
            connection.close()
            self.assertEqual(response.status, 200)
            self.assertTrue(payload["success"])
            self.assertEqual(payload["service"], "CotSProductionHostBridge")
        finally:
            service.stop()

    def test_unknown_lifecycle_operation_cannot_select_an_executable(self) -> None:
        result = bridge.execute_fixed(["definitely-not-a-lifecycle-operation"])
        self.assertEqual(result["exit_code"], 2)
        combined = (result.get("stdout") or "") + (result.get("stderr") or "")
        self.assertIn("invalid choice", combined.lower())


if __name__ == "__main__":
    unittest.main()
