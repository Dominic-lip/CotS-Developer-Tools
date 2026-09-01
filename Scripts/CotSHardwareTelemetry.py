#!/usr/bin/env python3
"""Local hardware telemetry and safety gates for CotS 24x7.

Uses only local OS tools/stdlib.  No cloud provider is contacted.  Missing
sensors are reported as unavailable rather than treated as failures.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

from CotS24x7Common import COTS, atomic_json, clean_text

REPO = Path(__file__).resolve().parent.parent
STATE = COTS / "hardware-telemetry.local.json"
DISK_PAUSE_GB = 10.0
RAM_PAUSE_GB = 1.5
GPU_TEMP_PAUSE_C = 91.0
GPU_VRAM_FREE_PAUSE_MB = 768.0


def _run(command: list[str], timeout: float = 5.0) -> str:
    """Run a local telemetry command without ever surfacing a console window.

    The 24x7 watchdog normally runs under pythonw.exe.  On Windows, spawning a
    console program such as powershell.exe from a windowless parent creates a
    visible transient console unless CREATE_NO_WINDOW is supplied.  Hardware
    polling happens every few seconds, so omitting this flag caused the blue
    PowerShell windows seen during commissioning.
    """
    try:
        kwargs: dict[str, Any] = {}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            **kwargs,
        )
        return (result.stdout or "").strip()
    except Exception:
        return ""


def _powershell(script: str, timeout: float = 6.0) -> Any:
    if os.name != "nt": return None
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe: return None
    output = _run([exe, "-NoProfile", "-Command", script], timeout)
    if not output: return None
    try: return json.loads(output)
    except json.JSONDecodeError: return None


def memory_snapshot() -> dict[str, Any]:
    if os.name == "nt":
        value = _powershell("$o=Get-CimInstance Win32_OperatingSystem; [pscustomobject]@{TotalKB=[double]$o.TotalVisibleMemorySize;FreeKB=[double]$o.FreePhysicalMemory}|ConvertTo-Json -Compress")
        if isinstance(value, dict):
            total = float(value.get("TotalKB") or 0) * 1024
            free = float(value.get("FreeKB") or 0) * 1024
            return {"total_bytes": int(total), "free_bytes": int(free), "used_percent": ((total-free)/total*100) if total else None}
    return {"total_bytes": None, "free_bytes": None, "used_percent": None}


def gpu_snapshot() -> dict[str, Any]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        default = Path(r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe")
        exe = str(default) if default.exists() else None
    if not exe:
        return {"available": False}
    query = "temperature.gpu,memory.total,memory.used,memory.free,utilization.gpu,power.draw,name"
    output = _run([exe, f"--query-gpu={query}", "--format=csv,noheader,nounits"], 5)
    if not output: return {"available": False}
    line = output.splitlines()[0]
    parts = [part.strip() for part in line.split(",")]
    if len(parts) < 7: return {"available": False, "raw": clean_text(line, 500)}
    def num(index: int) -> float | None:
        try: return float(parts[index])
        except (ValueError, IndexError): return None
    return {
        "available": True, "temperature_c": num(0), "vram_total_mb": num(1), "vram_used_mb": num(2),
        "vram_free_mb": num(3), "utilization_percent": num(4), "power_w": num(5), "name": parts[6],
    }


def unreal_snapshot() -> dict[str, Any]:
    if os.name != "nt": return {"processes": 0, "working_set_bytes": 0}
    value = _powershell("$p=Get-Process UnrealEditor* -ErrorAction SilentlyContinue; [pscustomobject]@{Count=@($p).Count;WorkingSet=(@($p)|Measure-Object WorkingSet64 -Sum).Sum;CPU=(@($p)|Measure-Object CPU -Sum).Sum}|ConvertTo-Json -Compress")
    if not isinstance(value, dict): return {"processes": 0, "working_set_bytes": 0}
    return {
        "processes": int(value.get("Count") or 0), "working_set_bytes": int(value.get("WorkingSet") or 0),
        "cpu_seconds": float(value.get("CPU") or 0),
    }


def network_snapshot() -> dict[str, Any]:
    started = time.monotonic()
    try:
        with socket.create_connection(("1.1.1.1", 53), timeout=1.5):
            return {"online": True, "probe_ms": round((time.monotonic()-started)*1000, 1)}
    except OSError as error:
        return {"online": False, "probe_ms": None, "error": clean_text(error, 160)}


def disk_snapshot() -> dict[str, Any]:
    usage = shutil.disk_usage(REPO)
    return {"total_bytes": usage.total, "used_bytes": usage.used, "free_bytes": usage.free, "free_gb": usage.free / (1024**3)}


def cpu_snapshot() -> dict[str, Any]:
    result: dict[str, Any] = {"temperature_c": None, "load_percent": None}
    if os.name == "nt":
        value = _powershell("$c=Get-CimInstance Win32_Processor|Measure-Object LoadPercentage -Average; [pscustomobject]@{Load=$c.Average}|ConvertTo-Json -Compress")
        if isinstance(value, dict) and isinstance(value.get("Load"), (int, float)):
            result["load_percent"] = float(value["Load"])
        # ACPI temperatures are not exposed on many desktop boards.  Use only
        # sane values; otherwise leave the sensor explicitly unavailable.
        temp = _powershell("$t=Get-CimInstance -Namespace root/wmi -Class MSAcpi_ThermalZoneTemperature -ErrorAction SilentlyContinue|Select-Object -First 1 CurrentTemperature; if($t){[math]::Round(($t.CurrentTemperature/10)-273.15,1)|ConvertTo-Json -Compress}")
        if isinstance(temp, (int, float)) and 0 < float(temp) < 125:
            result["temperature_c"] = float(temp)
    return result


def safety_reason(snapshot: dict[str, Any]) -> str | None:
    disk = snapshot.get("disk") or {}; memory = snapshot.get("memory") or {}; gpu = snapshot.get("gpu") or {}
    free_gb = disk.get("free_gb")
    if isinstance(free_gb, (int, float)) and free_gb < DISK_PAUSE_GB:
        return f"Disk free space critically low: {free_gb:.1f} GB"
    free_ram = memory.get("free_bytes")
    if isinstance(free_ram, (int, float)) and free_ram / (1024**3) < RAM_PAUSE_GB:
        return f"Available RAM critically low: {free_ram/(1024**3):.1f} GB"
    temp = gpu.get("temperature_c")
    if isinstance(temp, (int, float)) and temp >= GPU_TEMP_PAUSE_C:
        return f"GPU temperature too high: {temp:.0f} C"
    vram = gpu.get("vram_free_mb")
    if isinstance(vram, (int, float)) and vram < GPU_VRAM_FREE_PAUSE_MB and (snapshot.get("unreal") or {}).get("processes", 0):
        return f"GPU VRAM critically low while Unreal is running: {vram:.0f} MB free"
    return None


class HardwareMonitor:
    def __init__(self, network_interval: float = 30.0, slow_interval: float = 10.0) -> None:
        self.network_interval = network_interval; self.slow_interval = slow_interval
        self.last_network_at = 0.0; self.last_slow_at = 0.0
        self.cached_network: dict[str, Any] = {}; self.cached_cpu: dict[str, Any] = {}

    def poll(self) -> dict[str, Any]:
        now = time.time()
        if now - self.last_network_at >= self.network_interval:
            self.cached_network = network_snapshot(); self.last_network_at = now
        if now - self.last_slow_at >= self.slow_interval:
            self.cached_cpu = cpu_snapshot(); self.last_slow_at = now
        value = {
            "updated_at": now, "disk": disk_snapshot(), "memory": memory_snapshot(), "gpu": gpu_snapshot(),
            "cpu": self.cached_cpu, "unreal": unreal_snapshot(), "network": self.cached_network,
        }
        value["safety_reason"] = safety_reason(value)
        atomic_json(STATE, value)
        return value


if __name__ == "__main__":
    print(json.dumps(HardwareMonitor().poll(), indent=2, default=str))
