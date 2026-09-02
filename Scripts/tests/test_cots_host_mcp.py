#!/usr/bin/env python3
"""Regression test for TASK-016's dual-agent MCP parity fix.

Discovered live while proving Codex could reach CotS Host MCP in the same
session as Claude: Codex's rmcp Streamable HTTP client opens a GET stream
(and later a DELETE) against the server's single ``/mcp`` endpoint. Python's
``BaseHTTPRequestHandler`` answers an unimplemented method with a bare 501,
which the spec reserves for "we don't understand this at all" -- Codex's
client treated that 501 as a fatal transport error and dropped the whole
server, so none of its tools (not just the unsupported GET stream) were ever
exposed to the model. The Streamable HTTP transport spec requires 405 for an
unsupported *optional* method instead; Claude's client already tolerated
either code, so this asymmetry was invisible from the Claude side alone.

Run with: python -m unittest Scripts.tests.test_cots_host_mcp -v
(from the repository root), or `python Scripts/tests/test_cots_host_mcp.py`.
"""
from __future__ import annotations

import http.client
import importlib.util
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

_spec = importlib.util.spec_from_file_location("cots_host_mcp", SCRIPTS_DIR / "CotSHostMcp.py")
host_mcp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(host_mcp)


class HostMcpHttpServerTestCase(unittest.TestCase):
    """Exercises the real Handler over a loopback socket rather than calling
    its methods directly, since the behavior under test is the literal HTTP
    status code/headers a client sees."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), host_mcp.Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.thread.join(timeout=5)
        cls.server.server_close()

    def connection(self) -> http.client.HTTPConnection:
        return http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)

    def test_get_on_mcp_endpoint_returns_405_not_501(self) -> None:
        """The optional server-push stream is unsupported; the Streamable
        HTTP spec requires 405 here, and a bare 501 is what previously made
        Codex's MCP client tear down the whole server connection."""
        connection = self.connection()
        try:
            connection.request("GET", "/mcp")
            response = connection.getresponse()
            response.read()
            self.assertEqual(response.status, 405)
            self.assertEqual(response.getheader("Allow"), "POST")
        finally:
            connection.close()

    def test_delete_on_mcp_endpoint_returns_405_not_501(self) -> None:
        connection = self.connection()
        try:
            connection.request("DELETE", "/mcp")
            response = connection.getresponse()
            response.read()
            self.assertEqual(response.status, 405)
            self.assertEqual(response.getheader("Allow"), "POST")
        finally:
            connection.close()

    def test_post_still_serves_the_fixed_toolset(self) -> None:
        """Regression guard: the GET/DELETE fix must not disturb the existing
        POST-based JSON-RPC path the whole lifecycle depends on."""
        connection = self.connection()
        try:
            connection.request(
                "POST", "/mcp",
                body='{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}',
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            payload = response.read()
            self.assertEqual(response.status, 200)
            self.assertIn(b"GetToolLabStatus", payload)
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
