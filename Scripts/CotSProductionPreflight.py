#!/usr/bin/env python3
"""Fail-closed preflight for switching autonomous work into CotS production."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

try:
    from CotSWorkspaceProfiles import (
        WorkspaceBoundaryError,
        assert_expected_git_remote,
        assert_write_allowed,
        load_profile,
        profile_summary,
    )
except ModuleNotFoundError:
    from Scripts.CotSWorkspaceProfiles import (
        WorkspaceBoundaryError,
        assert_expected_git_remote,
        assert_write_allowed,
        load_profile,
        profile_summary,
    )


def git(root: Path, *args: str) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args], text=True, capture_output=True,
            timeout=20, check=False,
        )
    except OSError as error:
        return 127, str(error)
    return completed.returncode, ((completed.stdout or "") + (completed.stderr or "")).strip()


def check(profile_name: str) -> dict[str, Any]:
    profile = load_profile(profile_name)
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    add("workspace_exists", profile.workspace_root.is_dir(), str(profile.workspace_root))
    add("project_exists", profile.project_path.is_file(), str(profile.project_path))
    try:
        assert_write_allowed(profile.workspace_root, profile)
        add("workspace_write_boundary", True, "selected root is writable by profile policy")
    except WorkspaceBoundaryError as error:
        add("workspace_write_boundary", False, str(error))
    for root in profile.readonly_roots:
        try:
            assert_write_allowed(root, profile)
        except WorkspaceBoundaryError:
            add(f"readonly_boundary:{root}", True, "write correctly refused")
        else:
            add(f"readonly_boundary:{root}", False, "write unexpectedly allowed")
    try:
        remote = assert_expected_git_remote(profile)
        add("expected_origin", True, remote)
    except WorkspaceBoundaryError as error:
        add("expected_origin", False, str(error))
    rc, branch = git(profile.workspace_root, "rev-parse", "--abbrev-ref", "HEAD")
    add("git_branch_readable", rc == 0, branch)
    rc, status = git(profile.workspace_root, "status", "--porcelain=v1")
    add("git_status_readable", rc == 0, status[-1000:])
    if profile.name == "production" and rc == 0:
        add(
            "production_branch_policy",
            branch == profile.default_branch or branch.startswith(profile.autonomous_branch_prefix),
            f"branch={branch!r}; expected main or {profile.autonomous_branch_prefix}*",
        )
    build_exists = profile.build_script.is_file()
    add("build_entry_point", build_exists, str(profile.build_script))

    passed = all(item["ok"] for item in checks)
    return {
        "schema_version": 1,
        "profile": profile_summary(profile),
        "passed": passed,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("tooling", "production"), default="production")
    args = parser.parse_args()
    report = check(args.profile)
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
