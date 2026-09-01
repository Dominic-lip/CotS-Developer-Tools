#!/usr/bin/env python3
"""Authoritative CotS workspace/repository boundary definitions.

The control plane always lives in CotSDeveloperTools, while task work may target
that tooling repository or the clean CotS production repository.  Shardlands is
always treated as donor/reference and never as an autonomous write target.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
from typing import Iterable

TOOLS_ROOT = Path(r"C:\Dev\CotSDeveloperTools")
PRODUCTION_ROOT = Path(r"C:\Dev\CotS")
SHARDLANDS_ROOT = Path(r"C:\Dev\Shardlands")


@dataclass(frozen=True)
class WorkspaceProfile:
    name: str
    workspace_root: Path
    project_path: Path
    repository: str
    default_branch: str
    build_script: Path
    automation_filter: str
    write_roots: tuple[Path, ...]
    readonly_roots: tuple[Path, ...]
    autonomous_branch_prefix: str

    def normalized(self) -> "WorkspaceProfile":
        return WorkspaceProfile(
            self.name,
            self.workspace_root.resolve(strict=False),
            self.project_path.resolve(strict=False),
            self.repository,
            self.default_branch,
            self.build_script.resolve(strict=False),
            self.automation_filter,
            tuple(path.resolve(strict=False) for path in self.write_roots),
            tuple(path.resolve(strict=False) for path in self.readonly_roots),
            self.autonomous_branch_prefix,
        )


PROFILES: dict[str, WorkspaceProfile] = {
    "tooling": WorkspaceProfile(
        name="tooling",
        workspace_root=TOOLS_ROOT,
        project_path=TOOLS_ROOT / "ToolLab" / "CotSToolLab.uproject",
        repository="Dominic-lip/CotS-Developer-Tools",
        default_branch="main",
        build_script=TOOLS_ROOT / "Scripts" / "Build-ToolLab.cmd",
        automation_filter="CotS",
        write_roots=(TOOLS_ROOT,),
        readonly_roots=(PRODUCTION_ROOT, SHARDLANDS_ROOT),
        autonomous_branch_prefix="factory/",
    ),
    "production": WorkspaceProfile(
        name="production",
        workspace_root=PRODUCTION_ROOT,
        project_path=PRODUCTION_ROOT / "CotS.uproject",
        repository="Dominic-lip/CotS-Game",
        default_branch="main",
        build_script=TOOLS_ROOT / "Scripts" / "Build-CotS.cmd",
        automation_filter="CotS",
        write_roots=(PRODUCTION_ROOT,),
        readonly_roots=(SHARDLANDS_ROOT,),
        autonomous_branch_prefix="autonomous/",
    ),
}


class WorkspaceBoundaryError(RuntimeError):
    pass


def profile_for_task(task_id: str | None) -> WorkspaceProfile:
    """TASK-015 and TASK-100+ are production work; everything earlier is tooling."""
    if not task_id:
        return load_profile(os.environ.get("COTS_WORKSPACE_PROFILE", "tooling"))
    match = re.fullmatch(r"TASK-(\d+)(?:[A-Z])?", task_id.strip(), re.IGNORECASE)
    if not match:
        return load_profile(os.environ.get("COTS_WORKSPACE_PROFILE", "tooling"))
    number = int(match.group(1))
    return load_profile("production" if number == 15 or number >= 100 else "tooling")


def load_profile(name: str | None = None) -> WorkspaceProfile:
    selected = (name or os.environ.get("COTS_WORKSPACE_PROFILE") or "tooling").strip().lower()
    try:
        return PROFILES[selected].normalized()
    except KeyError as error:
        raise WorkspaceBoundaryError(f"unknown workspace profile: {selected!r}") from error


def _is_within(path: Path, root: Path) -> bool:
    path = path.resolve(strict=False)
    root = root.resolve(strict=False)
    return path == root or root in path.parents


def assert_write_allowed(path: Path | str, profile: WorkspaceProfile) -> Path:
    candidate = Path(path).resolve(strict=False)
    if any(_is_within(candidate, root) for root in profile.readonly_roots):
        raise WorkspaceBoundaryError(f"write forbidden by read-only boundary: {candidate}")
    if not any(_is_within(candidate, root) for root in profile.write_roots):
        raise WorkspaceBoundaryError(
            f"write outside profile {profile.name!r} write roots: {candidate}"
        )
    return candidate


def assert_paths_write_allowed(paths: Iterable[Path | str], profile: WorkspaceProfile) -> None:
    for path in paths:
        assert_write_allowed(path, profile)


def normalized_github_repo(remote_url: str) -> str | None:
    value = remote_url.strip().replace("\\", "/")
    value = re.sub(r"\.git$", "", value)
    for pattern in (
        r"https?://github\.com/([^/]+/[^/]+)$",
        r"ssh://git@github\.com/([^/]+/[^/]+)$",
        r"git@github\.com:([^/]+/[^/]+)$",
    ):
        match = re.fullmatch(pattern, value, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def git_output(profile: WorkspaceProfile, *args: str, timeout: int = 20) -> str:
    completed = subprocess.run(
        ["git", "-C", str(profile.workspace_root), *args],
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode:
        raise WorkspaceBoundaryError(
            f"git {' '.join(args)} failed ({completed.returncode}): "
            + (completed.stderr or completed.stdout)[-1200:]
        )
    return completed.stdout.strip()


def assert_expected_git_remote(profile: WorkspaceProfile) -> str:
    remote = git_output(profile, "remote", "get-url", "origin")
    actual = normalized_github_repo(remote)
    if actual is None or actual.lower() != profile.repository.lower():
        raise WorkspaceBoundaryError(
            f"profile {profile.name!r} expected origin {profile.repository!r}, got {remote!r}"
        )
    return remote


def profile_summary(profile: WorkspaceProfile) -> dict[str, object]:
    return {
        "profile": profile.name,
        "workspace_root": str(profile.workspace_root),
        "project_path": str(profile.project_path),
        "repository": profile.repository,
        "default_branch": profile.default_branch,
        "build_script": str(profile.build_script),
        "automation_filter": profile.automation_filter,
        "write_roots": [str(path) for path in profile.write_roots],
        "readonly_roots": [str(path) for path in profile.readonly_roots],
        "autonomous_branch_prefix": profile.autonomous_branch_prefix,
    }
