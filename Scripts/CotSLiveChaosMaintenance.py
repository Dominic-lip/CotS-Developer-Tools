#!/usr/bin/env python3
"""Explicit maintenance-mode live chaos tests for the CotS 24x7 stack.

Nothing runs unless ``--live`` is supplied.  Process faults target only exact
PIDs recorded by CotS durable state.  Provider-network isolation is optional,
Windows-only, requires admin, and installs an independent timed cleanup before
adding firewall rules so a harness crash cannot leave a permanent block.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from CotS24x7Common import COTS, FACTORY_STATE, HEALTH_PATH, SUPERVISOR_STATE, atomic_json, read_json

RESULT = COTS / "live-chaos-last-result.local.json"
TASK_NAME = "CotS Autonomous Factory 24x7"


def pid_live(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0: return False
    try: os.kill(pid, 0); return True
    except OSError: return False


def kill_exact(pid: int, *, tree: bool = False) -> None:
    if not pid_live(pid): return
    if os.name == "nt":
        command = ["taskkill", "/PID", str(pid), "/F"]
        if tree: command.insert(-1, "/T")
        subprocess.run(command, text=True, capture_output=True, timeout=15, check=False)
    else:
        os.kill(pid, signal.SIGTERM)


def wait_until(check: Callable[[], bool], timeout: float = 120.0, interval: float = 1.0) -> bool:
    deadline=time.time()+timeout
    while time.time()<deadline:
        if check(): return True
        time.sleep(interval)
    return False


def host_ready() -> bool:
    try:
        with socket.create_connection(("127.0.0.1",8010),timeout=1): return True
    except OSError: return False


def _record(name: str, passed: bool, detail: str, started: float) -> dict[str, Any]:
    return {"name":name,"passed":passed,"detail":detail,"started_at":started,"completed_at":time.time(),"duration_seconds":time.time()-started}


def chaos_provider() -> dict[str, Any]:
    started=time.time(); sup=read_json(SUPERVISOR_STATE); owner=sup.get("provider_ownership") if isinstance(sup.get("provider_ownership"),dict) else {}
    pid=owner.get("pid"); parent=owner.get("supervisor_pid"); kind=owner.get("kind")
    if kind not in {"codex_app_server","claude_print"} or not isinstance(pid,int) or not isinstance(parent,int) or not pid_live(parent):
        return _record("provider-kill",False,"No safely attributable live provider child",started)
    kill_exact(pid,tree=True)
    passed=wait_until(lambda: (not pid_live(pid)) and str(read_json(SUPERVISOR_STATE).get("state") or "") not in {"FAILED","TERMINAL_FAILURE"},90)
    return _record("provider-kill",passed,f"killed recorded {kind} pid={pid}; supervisor remained/recovered",started)


def chaos_supervisor() -> dict[str, Any]:
    started=time.time(); fac=read_json(FACTORY_STATE); old=fac.get("supervisor_pid")
    if not isinstance(old,int) or not pid_live(old): return _record("supervisor-kill",False,"No recorded live supervisor PID",started)
    kill_exact(old,tree=True)
    passed=wait_until(lambda: isinstance(read_json(FACTORY_STATE).get("supervisor_pid"),int) and read_json(FACTORY_STATE).get("supervisor_pid")!=old and pid_live(read_json(FACTORY_STATE).get("supervisor_pid")),120)
    return _record("supervisor-kill",passed,f"old={old} new={read_json(FACTORY_STATE).get('supervisor_pid')}",started)


def chaos_host() -> dict[str, Any]:
    started=time.time(); fac=read_json(FACTORY_STATE); old=fac.get("host_pid")
    if not isinstance(old,int) or not pid_live(old): return _record("host-mcp-kill",False,"Host MCP is not owned by the current Factory (host_pid unavailable)",started)
    kill_exact(old,tree=False)
    passed=wait_until(host_ready,120)
    return _record("host-mcp-kill",passed,f"killed owned host pid={old}; localhost:8010 ready={passed}",started)


def chaos_factory() -> dict[str, Any]:
    started=time.time(); health=read_json(HEALTH_PATH); old=health.get("factory_pid")
    if not isinstance(old,int) or not pid_live(old): return _record("factory-kill",False,"No recorded live Factory PID",started)
    kill_exact(old,tree=True)
    def recovered() -> bool:
        new=read_json(HEALTH_PATH).get("factory_pid"); return isinstance(new,int) and new!=old and pid_live(new)
    passed=wait_until(recovered,120)
    return _record("factory-kill",passed,f"old={old} new={read_json(HEALTH_PATH).get('factory_pid')}",started)


def _scheduled_task_present() -> bool:
    if os.name!="nt": return False
    result=subprocess.run(["schtasks","/Query","/TN",TASK_NAME],text=True,capture_output=True,timeout=10,check=False)
    return result.returncode==0


def chaos_watchdog() -> dict[str, Any]:
    started=time.time(); health=read_json(HEALTH_PATH); old=health.get("pid")
    if not _scheduled_task_present(): return _record("watchdog-kill",False,"Windows recovery task is not installed; refusing to kill watchdog",started)
    if not isinstance(old,int) or not pid_live(old): return _record("watchdog-kill",False,"No recorded live watchdog PID",started)
    kill_exact(old,tree=False)
    def recovered() -> bool:
        new=read_json(HEALTH_PATH).get("pid"); return isinstance(new,int) and new!=old and pid_live(new)
    passed=wait_until(recovered,180)
    return _record("watchdog-kill",passed,f"old={old} new={read_json(HEALTH_PATH).get('pid')}",started)


def _provider_executables() -> list[str]:
    result=[]
    for name in ("codex","claude"):
        found=shutil.which(name)
        if found and found.lower().endswith(".exe"): result.append(str(Path(found).resolve()))
    return result


def chaos_provider_network(seconds: int = 30) -> dict[str, Any]:
    started=time.time()
    if os.name!="nt": return _record("provider-network-isolation",False,"Windows firewall test only",started)
    executables=_provider_executables()
    if not executables: return _record("provider-network-isolation",False,"No native provider .exe paths found; refusing broad node/python firewall block",started)
    suffix=str(int(time.time())); rules=[f"CotS-Chaos-{suffix}-{i}" for i,_ in enumerate(executables)]
    cleanup_script="; ".join([f"Remove-NetFirewallRule -DisplayName '{rule}' -ErrorAction SilentlyContinue" for rule in rules])
    # Independent timed cleanup is armed before any block is created.
    ps=shutil.which("powershell") or shutil.which("pwsh")
    if not ps: return _record("provider-network-isolation",False,"PowerShell unavailable",started)
    subprocess.Popen([ps,"-NoProfile","-WindowStyle","Hidden","-Command",f"Start-Sleep -Seconds {seconds+20}; {cleanup_script}"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    added=[]
    try:
        for rule,exe in zip(rules,executables):
            command=f"New-NetFirewallRule -DisplayName '{rule}' -Direction Outbound -Action Block -Program '{exe}' | Out-Null"
            result=subprocess.run([ps,"-NoProfile","-Command",command],text=True,capture_output=True,timeout=15,check=False)
            if result.returncode!=0: return _record("provider-network-isolation",False,"Administrator PowerShell is required for provider-only firewall chaos",started)
            added.append(rule)
        time.sleep(max(1,seconds))
        return _record("provider-network-isolation",True,f"blocked only native provider executables for {seconds}s; timed cleanup armed",started)
    finally:
        for rule in added:
            subprocess.run([ps,"-NoProfile","-Command",f"Remove-NetFirewallRule -DisplayName '{rule}' -ErrorAction SilentlyContinue"],text=True,capture_output=True,timeout=15,check=False)


def run_selected(components: list[str], include_network: bool) -> dict[str, Any]:
    mapping={"provider":chaos_provider,"supervisor":chaos_supervisor,"host":chaos_host,"factory":chaos_factory,"watchdog":chaos_watchdog}
    results=[]
    for component in components:
        results.append(mapping[component]())
    if include_network: results.append(chaos_provider_network())
    value={"live":True,"completed_at":time.time(),"passed":all(item["passed"] for item in results),"results":results}
    atomic_json(RESULT,value); return value


def main() -> int:
    parser=argparse.ArgumentParser(description="Explicit live CotS 24x7 maintenance chaos")
    parser.add_argument("--live",action="store_true",help="Required acknowledgement for live process faults")
    parser.add_argument("--components",default="provider,supervisor,host,factory",help="Comma list: provider,supervisor,host,factory,watchdog")
    parser.add_argument("--include-provider-network",action="store_true",help="Temporarily firewall only native codex/claude executables (admin required)")
    args=parser.parse_args()
    if not args.live:
        print("Refusing live chaos without --live. Use CotSChaosRunner.py for safe simulations."); return 2
    components=[item.strip() for item in args.components.split(",") if item.strip()]
    invalid=[item for item in components if item not in {"provider","supervisor","host","factory","watchdog"}]
    if invalid: print(f"Unknown components: {invalid}"); return 2
    value=run_selected(components,args.include_provider_network); print(json.dumps(value,indent=2)); return 0 if value["passed"] else 1


if __name__=="__main__": raise SystemExit(main())
