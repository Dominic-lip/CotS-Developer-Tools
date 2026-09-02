#!/usr/bin/env python3
"""Non-fatal cross-platform process liveness checks for CotS runtime control.

On Windows, ``os.kill(pid, 0)`` is not a reliable process-existence probe and
can surface CPython ``SystemError`` for stale/racing PIDs.  The 24x7 runtime
must never crash merely because a previously recorded child PID disappeared,
so use Win32 process-query APIs there and make probe failure return False.
"""
from __future__ import annotations

import os


def process_live(pid: object) -> bool:
    """Return whether *pid* appears alive; probe failures are always non-fatal."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False

    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel32.GetExitCodeProcess.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL

            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            try:
                code = wintypes.DWORD(0)
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return False
                return int(code.value) == STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            # A liveness probe is advisory.  Stale/racing/corrupt PID state must
            # never be able to terminate the watchdog or Control Center.
            return False

    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError, SystemError):
        return False


if __name__ == "__main__":
    print("alive" if process_live(os.getpid()) else "not-alive")
