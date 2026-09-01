#!/usr/bin/env python3
"""Local zero-AI-cost CotS 24x7 control center."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

from CotS24x7Common import (
    COTS, FACTORY_STATE, HEALTH_PATH, STOP_FILE, SUPERVISOR_STATE, TOKEN_PATH,
    DailyTelemetry, clean_text, ensure_control_token, read_json, write_control,
)
from CotSSupportBundle import create_support_bundle

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "Scripts"
WATCHDOG = SCRIPTS / "CotSWatchdog24x7.py"
LOCAL_URL = "http://127.0.0.1:8765/"


def pid_live(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0: return False
    try: os.kill(pid, 0); return True
    except OSError: return False


def detached_python() -> str:
    executable = Path(sys.executable)
    if os.name == "nt":
        pythonw = executable.with_name("pythonw.exe")
        if pythonw.exists(): return str(pythonw)
    return str(executable)


class ControlCenter(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("CotS Development Control Center — 24x7")
        self.geometry("1380x860")
        self.minsize(1100, 720)
        self.telemetry = DailyTelemetry()
        self.token = ensure_control_token()
        self.selected_day: str | None = None
        self.last_day_list: list[str] = []
        self._build()
        self.after(250, self.refresh)

    def _build(self) -> None:
        top = ttk.Frame(self, padding=10); top.pack(fill="x")
        ttk.Label(top, text="CotS Development Control Center", font=("", 18, "bold")).pack(side="left")
        self.status_badge = ttk.Label(top, text="STARTING"); self.status_badge.pack(side="right", padx=8)
        controls = ttk.Frame(self, padding=(10, 0, 10, 10)); controls.pack(fill="x")
        ttk.Button(controls, text="Run 24/7", command=self.start_watchdog).pack(side="left", padx=(0, 6))
        ttk.Button(controls, text="Stop Safely", command=self.stop_safe).pack(side="left", padx=6)
        ttk.Button(controls, text="Restart Stack", command=self.restart_stack).pack(side="left", padx=6)
        ttk.Button(controls, text="Open Local Telemetry", command=lambda: webbrowser.open(LOCAL_URL)).pack(side="left", padx=6)
        ttk.Button(controls, text="Open Logs Folder", command=self.open_logs_folder).pack(side="left", padx=6)
        ttk.Button(controls, text="Create Support Bundle", command=self.create_bundle).pack(side="left", padx=6)
        ttk.Label(controls, text="The Control Center may be closed. The watchdog continues independently.").pack(side="right")

        self.tabs = ttk.Notebook(self); self.tabs.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.overview = ttk.Frame(self.tabs, padding=12); self.logs = ttk.Frame(self.tabs, padding=12)
        self.diagnostics = ttk.Frame(self.tabs, padding=12); self.remote = ttk.Frame(self.tabs, padding=12)
        self.tabs.add(self.overview, text="Overview"); self.tabs.add(self.logs, text="Daily Logs")
        self.tabs.add(self.diagnostics, text="Diagnostics"); self.tabs.add(self.remote, text="Remote / Tunnel")
        self._build_overview(); self._build_logs(); self._build_diagnostics(); self._build_remote()

    def _build_overview(self) -> None:
        self.overview.columnconfigure(1, weight=1)
        fields = [("Watchdog","watchdog"),("Factory","factory"),("Supervisor","supervisor"),("Task","task"),("Phase","phase"),
                  ("Active provider","provider"),("Current action","action"),("Uptime","uptime"),("Restarts","restarts"),
                  ("No-progress streak","streak"),("Last progress","last_progress"),("Cooldown","cooldown"),("Last successful gate","gate")]
        self.overview_vars: dict[str, tk.StringVar] = {}
        for row, (label, key) in enumerate(fields):
            ttk.Label(self.overview, text=label+":", font=("",10,"bold")).grid(row=row,column=0,sticky="nw",padx=(0,14),pady=5)
            var=tk.StringVar(value="—"); self.overview_vars[key]=var
            ttk.Label(self.overview,textvariable=var,wraplength=1000).grid(row=row,column=1,sticky="nw",pady=5)
        ttk.Separator(self.overview).grid(row=len(fields),column=0,columnspan=2,sticky="ew",pady=10)
        self.usage_text=tk.Text(self.overview,height=10,wrap="word"); self.usage_text.grid(row=len(fields)+1,column=0,columnspan=2,sticky="nsew")
        self.overview.rowconfigure(len(fields)+1,weight=1)

    def _build_logs(self) -> None:
        pane=ttk.Panedwindow(self.logs,orient="horizontal"); pane.pack(fill="both",expand=True)
        left=ttk.Frame(pane); right=ttk.Frame(pane); pane.add(left,weight=1); pane.add(right,weight=5)
        ttk.Label(left,text="Days",font=("",11,"bold")).pack(anchor="w",pady=(0,6))
        self.day_list=tk.Listbox(left,exportselection=False); self.day_list.pack(fill="both",expand=True); self.day_list.bind("<<ListboxSelect>>",self.on_day_select)
        ttk.Label(right,text="Simplified local activity log — generated without Codex/Claude usage",font=("",11,"bold")).pack(anchor="w",pady=(0,6))
        self.log_text=tk.Text(right,wrap="none"); self.log_text.pack(fill="both",expand=True)

    def _build_diagnostics(self) -> None:
        ttk.Label(self.diagnostics,text="Local diagnostic state (no provider usage)",font=("",11,"bold")).pack(anchor="w",pady=(0,6))
        self.diag_text=tk.Text(self.diagnostics,wrap="none"); self.diag_text.pack(fill="both",expand=True)

    def _build_remote(self) -> None:
        self.remote.columnconfigure(0,weight=1); self.remote.rowconfigure(7,weight=1)
        ttk.Label(self.remote,text="Private remote telemetry",font=("",14,"bold")).grid(row=0,column=0,sticky="w",pady=(0,8))
        ttk.Label(self.remote,text="Recommended: Tailscale Serve proxies the localhost telemetry endpoint into your private tailnet. The endpoint itself never calls an AI provider. Remote control actions additionally require the local bearer token.",wraplength=1050).grid(row=1,column=0,sticky="w",pady=(0,12))
        self.remote_status=tk.StringVar(value="Checking Tailscale…"); ttk.Label(self.remote,textvariable=self.remote_status).grid(row=2,column=0,sticky="w",pady=5)
        ttk.Label(self.remote,text=f"Local endpoint: {LOCAL_URL}").grid(row=3,column=0,sticky="w",pady=5)
        ttk.Label(self.remote,text=f"Control token file: {TOKEN_PATH}").grid(row=4,column=0,sticky="w",pady=5)
        buttons=ttk.Frame(self.remote); buttons.grid(row=5,column=0,sticky="w",pady=12)
        ttk.Button(buttons,text="Enable Tailscale Serve",command=self.enable_tailscale).pack(side="left",padx=(0,6))
        ttk.Button(buttons,text="Copy Control Token",command=self.copy_token).pack(side="left",padx=6)
        ttk.Button(buttons,text="Open Local Endpoint",command=lambda:webbrowser.open(LOCAL_URL)).pack(side="left",padx=6)
        ttk.Label(self.remote,text="For shell access, use Windows OpenSSH over the Tailscale interface rather than exposing SSH to the public Internet. The HTTP control endpoint is enough for status, logs, safe stop and restart in normal operation.",wraplength=1050).grid(row=6,column=0,sticky="w",pady=(10,0))
        self.remote_output=tk.Text(self.remote,height=16,wrap="word"); self.remote_output.grid(row=7,column=0,sticky="nsew",pady=(12,0))

    def start_watchdog(self) -> None:
        health=read_json(HEALTH_PATH)
        if pid_live(health.get("pid")):
            try: STOP_FILE.unlink()
            except OSError: pass
            write_control("resume",source="control_center"); return
        try: STOP_FILE.unlink()
        except OSError: pass
        kwargs:dict[str,Any]={"cwd":REPO}
        if os.name=="nt": kwargs["creationflags"]=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen([detached_python(),str(WATCHDOG)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,stdin=subprocess.DEVNULL,**kwargs)

    def stop_safe(self) -> None: write_control("stop",source="control_center")
    def restart_stack(self) -> None: write_control("restart",source="control_center")

    def open_logs_folder(self) -> None:
        folder=COTS/"telemetry"; folder.mkdir(parents=True,exist_ok=True)
        if os.name=="nt": os.startfile(folder)  # type: ignore[attr-defined]
        else: webbrowser.open(folder.as_uri())

    def create_bundle(self) -> None:
        try:
            path=create_support_bundle()
            if os.name=="nt": os.startfile(path.parent)  # type: ignore[attr-defined]
            messagebox.showinfo("CotS 24x7",f"Support bundle created:\n{path}\n\nUpload this ZIP for diagnosis.")
        except Exception as error: messagebox.showerror("CotS 24x7",f"Could not create support bundle: {error}")

    def copy_token(self) -> None:
        self.clipboard_clear(); self.clipboard_append(self.token); self.update(); messagebox.showinfo("CotS 24x7","Control token copied to clipboard.")

    def enable_tailscale(self) -> None:
        exe=shutil.which("tailscale")
        if not exe: messagebox.showinfo("Tailscale","Tailscale CLI is not installed or not on PATH."); return
        try:
            result=subprocess.run([exe,"serve","--bg","http://127.0.0.1:8765"],text=True,capture_output=True,timeout=30,check=False)
            self.remote_output.delete("1.0","end"); self.remote_output.insert("1.0",(result.stdout+"\n"+result.stderr).strip())
        except Exception as error: messagebox.showerror("Tailscale",str(error))

    def on_day_select(self,_event:object=None) -> None:
        selection=self.day_list.curselection()
        if not selection:return
        self.selected_day=self.day_list.get(selection[0]); self.refresh_log_text()

    def refresh_log_text(self) -> None:
        day=self.selected_day or (self.last_day_list[0] if self.last_day_list else None)
        if not day:return
        self.log_text.delete("1.0","end"); self.log_text.insert("1.0",self.telemetry.read_day(day)); self.log_text.see("end")

    @staticmethod
    def format_age(epoch:object)->str:
        if not isinstance(epoch,(int,float)) or epoch<=0:return "—"
        seconds=max(0,time.time()-epoch)
        if seconds<60:return f"{seconds:.0f}s ago"
        if seconds<3600:return f"{seconds/60:.1f}m ago"
        return f"{seconds/3600:.1f}h ago"

    def refresh(self) -> None:
        try:
            health=read_json(HEALTH_PATH); supervisor=read_json(SUPERVISOR_STATE); factory=read_json(FACTORY_STATE)
            alive=pid_live(health.get("pid")); state=health.get("state") if alive else "STOPPED"; self.status_badge.configure(text=str(state))
            self.overview_vars["watchdog"].set(f"{state}  pid={health.get('pid') or '—'}")
            self.overview_vars["factory"].set(str(health.get("factory_state") or factory.get("factory") or "—")); self.overview_vars["supervisor"].set(str(health.get("supervisor_state") or supervisor.get("state") or "—"))
            self.overview_vars["task"].set(str(health.get("task") or supervisor.get("task") or "—")); self.overview_vars["phase"].set(str(health.get("phase") or supervisor.get("phase") or "—")); self.overview_vars["provider"].set(str(health.get("active_agent") or supervisor.get("active_agent") or "none")); self.overview_vars["action"].set(str(health.get("current_action") or supervisor.get("current_action") or "—"))
            self.overview_vars["uptime"].set(f"{float(health.get('uptime_seconds') or 0)/3600:.2f} h"); self.overview_vars["restarts"].set(str(health.get("restart_count") or 0)); self.overview_vars["streak"].set(str(health.get("no_progress_streak") or 0)); self.overview_vars["last_progress"].set(self.format_age(health.get("last_progress_at")))
            cooldown=health.get("cooldown_until"); self.overview_vars["cooldown"].set("none" if not isinstance(cooldown,(int,float)) or cooldown<=time.time() else f"{max(0,cooldown-time.time()):.0f}s remaining")
            self.overview_vars["gate"].set(str(health.get("last_successful_gate") or supervisor.get("last_successful_gate") or "—"))
            usage={"Codex":supervisor.get("codex") or {},"Claude":supervisor.get("claude") or {},"Efficiency":supervisor.get("efficiency") or {},"Note":"Usage figures are local checkpoint/protocol telemetry. The Control Center does not ask a model to summarize them."}
            self.usage_text.delete("1.0","end"); self.usage_text.insert("1.0",json.dumps(usage,indent=2,default=str))
            days=self.telemetry.list_days()
            if days!=self.last_day_list:
                self.last_day_list=days; self.day_list.delete(0,"end")
                for day in days:self.day_list.insert("end",day)
                if self.selected_day not in days:
                    self.selected_day=days[0] if days else None
                    if days:self.day_list.selection_set(0)
            if self.tabs.index(self.tabs.select())==1 and self.selected_day:self.refresh_log_text()
            self.diag_text.delete("1.0","end"); self.diag_text.insert("1.0",json.dumps({"watchdog":health,"factory":factory,"supervisor":supervisor},indent=2,default=str))
            tailscale=shutil.which("tailscale")
            if tailscale:
                try:
                    result=subprocess.run([tailscale,"status","--json"],text=True,capture_output=True,timeout=4,check=False); status=json.loads(result.stdout) if result.stdout.strip().startswith("{") else {}
                    self.remote_status.set(f"Tailscale: {status.get('BackendState','installed')} · {((status.get('Self') or {}).get('DNSName') or '').rstrip('.') or 'no DNS name'}")
                except Exception:self.remote_status.set("Tailscale installed; status unavailable")
            else:self.remote_status.set("Tailscale CLI not found")
        except Exception as error:self.status_badge.configure(text=f"UI ERROR: {clean_text(error,120)}")
        finally:self.after(1000,self.refresh)


if __name__=="__main__": ControlCenter().mainloop()
