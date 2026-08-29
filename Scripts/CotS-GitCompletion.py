#!/usr/bin/env python3
"""Narrow Git entry point for autonomous CotS task completion."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.resolve()


def git(*args: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(REPO), *args], text=True, check=False, capture_output=capture)


def print_result(result: subprocess.CompletedProcess[str]) -> int:
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result.returncode


def repo_file(value: str) -> str:
    candidate = (REPO / value).resolve()
    if candidate == REPO or REPO not in candidate.parents or ".git" in candidate.parts:
        raise argparse.ArgumentTypeError("path must be a repository-relative non-.git path")
    if not candidate.exists():
        raise argparse.ArgumentTypeError(f"path does not exist: {value}")
    return candidate.relative_to(REPO).as_posix()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    for name in ("status", "diff", "diff-check"):
        sub.add_parser(name)
    complete = sub.add_parser("complete", help="Validate, stage exact files, commit, and push origin/main.")
    complete.add_argument("--message", required=True)
    complete.add_argument("files", nargs="+", type=repo_file)
    args = parser.parse_args()
    if args.operation == "status":
        return print_result(git("status", "--short", "--branch", capture=True))
    if args.operation == "diff":
        return print_result(git("diff", "--", capture=True))
    if args.operation == "diff-check":
        return print_result(git("diff", "--check", capture=True))
    if "\n" in args.message or not args.message.strip():
        parser.error("commit message must be a non-empty single line")
    staged = git("diff", "--cached", "--name-only", capture=True)
    if staged.returncode:
        return print_result(staged)
    requested = sorted(set(args.files))
    existing = sorted(line for line in staged.stdout.splitlines() if line)
    if existing and existing != requested:
        print("[BLOCKED] pre-existing staged files differ from this task completion set", file=sys.stderr)
        return 2
    result = git("add", "--", *requested, capture=True)
    if result.returncode:
        return print_result(result)
    result = git("diff", "--cached", "--check", capture=True)
    if result.returncode:
        return print_result(result)
    if not git("diff", "--cached", "--quiet").returncode:
        print("[BLOCKED] no staged changes to commit", file=sys.stderr)
        return 2
    result = git("commit", "-m", args.message, capture=True)
    if result.returncode:
        return print_result(result)
    return print_result(git("push", "origin", "main", capture=True))


if __name__ == "__main__":
    sys.exit(main())
