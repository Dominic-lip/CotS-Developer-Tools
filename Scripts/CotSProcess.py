#!/usr/bin/env python3
"""Small cross-platform process identity helpers used by CotS control-plane code.

Windows deliberately does not use ``os.kill(pid, 0)``: it is not a reliable
liveness probe there and previously caused WinError 87/SystemError incidents.
"""
from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from typing import Any

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    creation_time_100ns: int | None

    def to_json(self) -> dict[str, int | None]:
        return {"pid": self.pid, "creation_time_100ns": self.creation_time_100ns}


def _valid_pid(pid: Any) -> bool:
    return isinstance(pid, int) and not isinstance(pid, bool) and pid > 0


def _windows_identity(pid: int) -> ProcessIdentity | None:
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return None
        if exit_code.value != STILL_ACTIVE:
            return None
        creation = ctypes.c_ulonglong()
        exit_time = ctypes.c_ulonglong()
        kernel = ctypes.c_ulonglong()
        user = ctypes.c_ulonglong()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return ProcessIdentity(pid, None)
        return ProcessIdentity(pid, int(creation.value))
    finally:
        kernel32.CloseHandle(handle)


def process_identity(pid: Any) -> ProcessIdentity | None:
    if not _valid_pid(pid):
        return None
    pid = int(pid)
    if os.name == "nt":
        return _windows_identity(pid)
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    # Portable creation time is intentionally omitted rather than guessed.
    return ProcessIdentity(pid, None)


def pid_running(pid: Any) -> bool:
    return process_identity(pid) is not None


def identity_matches(recorded: dict[str, Any] | None) -> bool:
    if not isinstance(recorded, dict):
        return False
    current = process_identity(recorded.get("pid"))
    if current is None:
        return False
    expected_creation = recorded.get("creation_time_100ns")
    if expected_creation is None or current.creation_time_100ns is None:
        return True
    return int(expected_creation) == current.creation_time_100ns
