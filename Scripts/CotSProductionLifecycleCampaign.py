#!/usr/bin/env python3
"""Campaign authorization wrapper for the fixed CotS production lifecycle.

Provider processes execute under a restricted Windows sandbox identity.  Normal
campaign calls therefore proxy to the loopback production-host bridge owned by
the persistent local watchdog.  The bridge re-enters this exact script with a
private direct flag under the operator account; all existing fixed lifecycle
validation still runs unchanged.
"""
from __future__ import annotations

import http.client
import json
import os
import sys
from pathlib import Path

import CotSProductionLifecycle as base

CAMPAIGN_FIRST_TASK = 117
CAMPAIGN_LAST_TASK = 121
REPO = Path(__file__).resolve().parent.parent
TOKEN_PATH = REPO / ".cots" / "production-host-token.local.txt"
HOST, PORT = "127.0.0.1", 8011
DIRECT_ENV = "COTS_PRODUCTION_HOST_DIRECT"


def install_campaign() -> None:
    base.ALLOWED_TASKS = {
        "TASK-015",
        *(f"TASK-{n}" for n in range(100, 116)),
        *(f"TASK-{n}" for n in range(CAMPAIGN_FIRST_TASK, CAMPAIGN_LAST_TASK + 1)),
    }


def _token() -> str:
    try:
        value = TOKEN_PATH.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise RuntimeError(f"production_host_bridge_token_unavailable: {error}") from error
    if len(value) < 32:
        raise RuntimeError("production_host_bridge_token_invalid")
    return value


def _proxy_timeout(argv: list[str]) -> int:
    timeout = 2 * 60 * 60 + 15 * 60
    for index, value in enumerate(argv[:-1]):
        if value == "--timeout":
            try:
                requested = int(argv[index + 1])
            except ValueError:
                break
            timeout = max(60, min(requested + 600, timeout))
            break
    return timeout


def proxy_main(argv: list[str]) -> int:
    try:
        token = _token()
        connection = http.client.HTTPConnection(HOST, PORT, timeout=_proxy_timeout(argv))
        payload = json.dumps({"argv": argv}, separators=(",", ":"))
        connection.request(
            "POST", "/run", body=payload,
            headers={"Content-Type": "application/json", "X-CotS-Production-Token": token},
        )
        response = connection.getresponse()
        raw = response.read().decode("utf-8", errors="replace")
        connection.close()
        if response.status != 200:
            print(json.dumps({
                "success": False,
                "error": "production_host_bridge_http_error",
                "status": response.status,
                "detail": raw[-4000:],
            }, indent=2))
            return 2
        result = json.loads(raw)
        stdout = str(result.get("stdout") or "")
        stderr = str(result.get("stderr") or "")
        if stdout:
            sys.stdout.write(stdout)
            if not stdout.endswith("\n"):
                sys.stdout.write("\n")
        if stderr:
            sys.stderr.write(stderr)
            if not stderr.endswith("\n"):
                sys.stderr.write("\n")
        return int(result.get("exit_code", 2))
    except (OSError, RuntimeError, json.JSONDecodeError, ValueError) as error:
        print(json.dumps({
            "success": False,
            "error": f"production_host_bridge_unavailable: {error}",
            "recommended_action": "restart the CotS campaign watchdog so its loopback production bridge is live",
        }, indent=2))
        return 2


def main() -> int:
    install_campaign()
    if os.environ.get(DIRECT_ENV) == "1":
        return int(base.main())
    return proxy_main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
