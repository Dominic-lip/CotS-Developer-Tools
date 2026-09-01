#!/usr/bin/env python3
"""Minimal loopback client for CotS Host MCP V4 status checks."""
from __future__ import annotations

import http.client
import json
from typing import Any

HOST = "127.0.0.1"
PORT = 8010


def call(tool_name: str, arguments: dict[str, Any] | None = None, *, timeout: float = 3.0) -> dict[str, Any]:
    connection = http.client.HTTPConnection(HOST, PORT, timeout=timeout)
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    try:
        initialize = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "CotS Host Client", "version": "4.0"},
            },
        }
        connection.request("POST", "/mcp", body=json.dumps(initialize), headers=headers)
        response = connection.getresponse()
        raw = response.read().decode("utf-8", errors="replace")
        session = response.getheader("Mcp-Session-Id")
        if response.status != 200 or not session:
            raise RuntimeError(f"host initialize failed: {response.status}: {raw[-400:]}")
        payload = json.loads(raw)
        version = payload.get("result", {}).get("protocolVersion", "2025-11-25")
        session_headers = {**headers, "Mcp-Session-Id": session, "Mcp-Protocol-Version": version}
        connection.request(
            "POST", "/mcp",
            body=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}),
            headers=session_headers,
        )
        initialized = connection.getresponse()
        initialized.read()
        if initialized.status not in (200, 202):
            raise RuntimeError(f"host initialized notification failed: {initialized.status}")
        request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments or {}},
        }
        connection.request("POST", "/mcp", body=json.dumps(request), headers=session_headers)
        response = connection.getresponse()
        raw = response.read().decode("utf-8", errors="replace")
        if response.status != 200:
            raise RuntimeError(f"host tool call failed: {response.status}: {raw[-400:]}")
        payload = json.loads(raw)
        text = payload["result"]["content"][0]["text"]
        result = json.loads(text)
        if not isinstance(result, dict):
            raise RuntimeError("host result was not an object")
        return result
    finally:
        connection.close()


def status(*, timeout: float = 3.0) -> dict[str, Any]:
    return call("GetWorkspaceStatus", timeout=timeout)


def ready_for_profile(profile_name: str, repository: str, *, timeout: float = 3.0) -> tuple[bool, dict[str, Any] | None, str | None]:
    try:
        payload = status(timeout=timeout)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        if payload.get("success") is not True:
            return False, data, str(payload.get("error") or "host status unsuccessful")
        if data.get("profile") != profile_name:
            return False, data, f"wrong Host profile: expected {profile_name!r}, got {data.get('profile')!r}"
        if str(data.get("repository") or "").lower() != repository.lower():
            return False, data, f"wrong Host repository: expected {repository!r}, got {data.get('repository')!r}"
        return True, data, None
    except Exception as error:
        return False, None, str(error)
