#!/usr/bin/env python3
"""Profile-aware, fixed-scope Git completion for autonomous CotS work.

Unlike the legacy helper this can safely target either CotSDeveloperTools or
CotS-Game, validates the expected origin, supports deletions, and forbids
production autonomous commits directly on main.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys

try:
    from CotSWorkspaceProfiles import (
        WorkspaceBoundaryError,
        assert_expected_git_remote,
        assert_write_allowed,
        load_profile,
    )
except ModuleNotFoundError:
    from Scripts.CotSWorkspaceProfiles import (
        WorkspaceBoundaryError,
        assert_expected_git_remote,
        assert_write_allowed,
        load_profile,
    )


def git(root: Path, *args: str, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        check=False,
        capture_output=capture,
        timeout=120,
    )


def emit(result: subprocess.CompletedProcess[str]) -> int:
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result.returncode


def repo_path(value: str, root: Path) -> str:
    candidate = (root / value).resolve(strict=False)
    assert_write_allowed(candidate, CURRENT_PROFILE)
    if candidate == root or root not in candidate.parents:
        raise argparse.ArgumentTypeError("path must be repository-relative")
    if ".git" in candidate.parts:
        raise argparse.ArgumentTypeError(".git paths are forbidden")
    return candidate.relative_to(root).as_posix()


def current_branch(root: Path) -> str:
    result = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip())
    return result.stdout.strip()


def changed_paths(root: Path) -> list[str]:
    result = git(root, "status", "--porcelain=v1")
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip())
    values: list[str] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        payload = line[3:].strip()
        # For rename records, Git porcelain emits "old -> new". The new path
        # is the path Git ultimately stages/commits.
        values.append(payload.rsplit(" -> ", 1)[-1])
    return values


def staged_paths(root: Path) -> list[str]:
    result = git(root, "diff", "--cached", "--name-only", "--diff-filter=ACDMRTUXB")
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip())
    return sorted(line.strip() for line in result.stdout.splitlines() if line.strip())


def require_safe_branch(profile_name: str, branch: str, prefix: str, default_branch: str) -> None:
    if profile_name == "production":
        if branch == default_branch:
            raise WorkspaceBoundaryError(
                "production autonomous completion refuses direct commits to main; use an autonomous/* task branch"
            )
        if not branch.startswith(prefix):
            raise WorkspaceBoundaryError(
                f"production branch must start with {prefix!r}, got {branch!r}"
            )


def main(argv: list[str] | None = None) -> int:
    global CURRENT_PROFILE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("tooling", "production"), default=None)
    sub = parser.add_subparsers(dest="operation", required=True)
    for name in ("status", "diff", "diff-check", "verify"):
        sub.add_parser(name)
    branch_parser = sub.add_parser("ensure-task-branch")
    branch_parser.add_argument("task_id")
    complete = sub.add_parser("complete")
    complete.add_argument("--message", required=True)
    complete.add_argument("files", nargs="+")
    args = parser.parse_args(argv)

    CURRENT_PROFILE = load_profile(args.profile)
    root = CURRENT_PROFILE.workspace_root
    try:
        assert_write_allowed(root, CURRENT_PROFILE)
        assert_expected_git_remote(CURRENT_PROFILE)
    except WorkspaceBoundaryError as error:
        print(f"[BLOCKED] {error}", file=sys.stderr)
        return 2

    if args.operation == "verify":
        print(f"profile={CURRENT_PROFILE.name}")
        print(f"workspace={root}")
        print(f"repository={CURRENT_PROFILE.repository}")
        print(f"branch={current_branch(root)}")
        return 0
    if args.operation == "status":
        return emit(git(root, "status", "--short", "--branch"))
    if args.operation == "diff":
        return emit(git(root, "diff", "--"))
    if args.operation == "diff-check":
        return emit(git(root, "diff", "--check"))
    if args.operation == "ensure-task-branch":
        task = args.task_id.strip().lower()
        if not re.fullmatch(r"task-\d+(?:[a-z])?", task):
            parser.error("task_id must look like TASK-015 or TASK-100")
        desired = CURRENT_PROFILE.autonomous_branch_prefix + task
        branch = current_branch(root)
        if branch == desired:
            print(desired)
            return 0
        if branch != CURRENT_PROFILE.default_branch:
            print(
                f"[BLOCKED] refusing to switch from unexpected branch {branch!r}; expected "
                f"{CURRENT_PROFILE.default_branch!r} or {desired!r}",
                file=sys.stderr,
            )
            return 2
        created = git(root, "switch", "-c", desired)
        if created.returncode:
            return emit(created)
        print(desired)
        return 0

    if "\n" in args.message or not args.message.strip():
        parser.error("commit message must be a non-empty single line")
    branch = current_branch(root)
    try:
        require_safe_branch(
            CURRENT_PROFILE.name,
            branch,
            CURRENT_PROFILE.autonomous_branch_prefix,
            CURRENT_PROFILE.default_branch,
        )
    except WorkspaceBoundaryError as error:
        print(f"[BLOCKED] {error}", file=sys.stderr)
        return 2

    requested: list[str] = []
    for raw in args.files:
        try:
            requested.append(repo_path(raw, root))
        except (WorkspaceBoundaryError, argparse.ArgumentTypeError) as error:
            print(f"[BLOCKED] {error}", file=sys.stderr)
            return 2
    requested = sorted(set(requested))

    existing_staged = staged_paths(root)
    if existing_staged and existing_staged != requested:
        print("[BLOCKED] pre-existing staged files differ from this completion set", file=sys.stderr)
        return 2

    # -A stages modifications, additions *and deletions* for exactly the
    # requested repository-relative paths.
    added = git(root, "add", "-A", "--", *requested)
    if added.returncode:
        return emit(added)
    staged = staged_paths(root)
    if staged != requested:
        print(
            f"[BLOCKED] staged set differs from requested set: requested={requested!r} staged={staged!r}",
            file=sys.stderr,
        )
        return 2
    checked = git(root, "diff", "--cached", "--check")
    if checked.returncode:
        return emit(checked)
    quiet = git(root, "diff", "--cached", "--quiet")
    if quiet.returncode == 0:
        print("[BLOCKED] no staged changes to commit", file=sys.stderr)
        return 2
    if quiet.returncode not in (0, 1):
        return emit(quiet)

    committed = git(root, "commit", "-m", args.message)
    if committed.returncode:
        return emit(committed)
    # Push only the currently validated branch. Never hard-code main.
    return emit(git(root, "push", "-u", "origin", branch))


CURRENT_PROFILE = load_profile("tooling")

if __name__ == "__main__":
    raise SystemExit(main())
