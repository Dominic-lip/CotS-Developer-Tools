#!/usr/bin/env python3
"""Create/validate the empty CotS production Git workspace for TASK-015.

This performs only repository plumbing. It does not create Unreal content or
copy Shardlands. The production agent remains responsible for the actual
TASK-015 project bootstrap on an autonomous task branch.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

try:
    from CotSWorkspaceProfiles import load_profile, normalized_github_repo
except ModuleNotFoundError:
    from Scripts.CotSWorkspaceProfiles import load_profile, normalized_github_repo

PROFILE = load_profile("production")
ROOT = PROFILE.workspace_root
REMOTE_URL = f"https://github.com/{PROFILE.repository}.git"
INITIAL_BRANCH = PROFILE.autonomous_branch_prefix + "task-015"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args], text=True, capture_output=True,
        check=False, timeout=60,
    )


def fail(message: str) -> int:
    print(f"[BLOCKED] {message}", file=sys.stderr)
    return 2


def main() -> int:
    ROOT.mkdir(parents=True, exist_ok=True)
    git_dir = ROOT / ".git"
    if not git_dir.exists():
        # Refuse to turn a non-empty arbitrary directory into the game repo.
        existing = [entry for entry in ROOT.iterdir() if entry.name != ".git"]
        if existing:
            return fail(
                "C:\\Dev\\CotS exists but is not a Git repository and is not empty; "
                "manual inspection is required before bootstrap"
            )
        initialized = subprocess.run(
            ["git", "init", f"--initial-branch={INITIAL_BRANCH}", str(ROOT)],
            text=True, capture_output=True, check=False, timeout=60,
        )
        if initialized.returncode:
            return fail((initialized.stderr or initialized.stdout).strip())
        added = run("remote", "add", "origin", REMOTE_URL)
        if added.returncode:
            return fail((added.stderr or added.stdout).strip())
    remote = run("remote", "get-url", "origin")
    if remote.returncode:
        return fail((remote.stderr or remote.stdout).strip())
    actual = normalized_github_repo(remote.stdout.strip())
    if actual is None or actual.lower() != PROFILE.repository.lower():
        return fail(f"unexpected production origin: {remote.stdout.strip()!r}")
    branch = run("rev-parse", "--abbrev-ref", "HEAD")
    current = branch.stdout.strip() if branch.returncode == 0 else ""
    if current and current != INITIAL_BRANCH and current != PROFILE.default_branch:
        return fail(f"unexpected production branch {current!r}")
    if current == PROFILE.default_branch:
        # Only switch when the repo has no commits; established production main
        # is never silently moved by bootstrap.
        head = run("rev-parse", "--verify", "HEAD")
        if head.returncode == 0:
            return fail("production repository already has commits on main; TASK-015 bootstrap is no longer appropriate")
        symbolic = run("symbolic-ref", "HEAD", f"refs/heads/{INITIAL_BRANCH}")
        if symbolic.returncode:
            return fail((symbolic.stderr or symbolic.stdout).strip())
    print(f"[OK] production workspace: {ROOT}")
    print(f"[OK] origin: {PROFILE.repository}")
    print(f"[OK] autonomous bootstrap branch: {INITIAL_BRANCH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
