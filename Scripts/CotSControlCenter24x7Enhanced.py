#!/usr/bin/env python3
"""Enhanced zero-cloud-cost GUI for CotS 24x7 autonomy and observability."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

from CotS24x7Common import COTS, FACTORY_STATE, HEALTH_PATH, STOP_FILE, SUPERVISOR_STATE, TOKEN_PATH, DailyTelemetry, clean_text, ensure_control_token, read_json, write_control
from CotSLocalAI import LocalAI
from CotSOperationalMetrics import OperationalMetrics
from CotSSupportBundle import create_support_bundle
from CotSUsageLedger import ProviderUsageLedger, format_reset

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "Scripts"
WATCHDOG = SCRIPTS / "CotSWatchdog24x7Enhanced.py"
CHAOS = SCRIPTS / "CotSChaosRunner.py"
LOCAL_URL = "http://127.0.0.1:8765/"
HARDWARE_STATE = COTS / "hardware-telemetry.local.json"
GOVERNOR_STATE = COTS / "productivity-governor.local.json"
ROLLBACK_STATE = COTS / "rollback-guard.local.json"
CHAOS_STATE = COTS / "chaos-last-result.local.json"

BG = "#0d1117"; PANEL = "#161b22"; PANEL2 = "#1f2630"; FG = "#e6edf3"; MUTED = "#8b949e"
ACCENT = "#58a6ff"; GOOD = "#3fb950"; WARN = "#d29922"; BAD = "#f85149"; PURPLE = "#bc8cff"


def pid_live(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0: return False
    try: os.kill(pid, 0); return True
    except OSError: return False


def detached_python() -> str:
    executable = Path(sys.executable)
    if os.name == "nt":
        candidate = executable.with_name("pythonw.exe")
        if candidate.exists(): return str(candidate)
    return str(executable)


def fmt_age(epoch: object) -> str:
    if not isinstance(epoch, (int, float)) or epoch <= 0: return "—"
    seconds = max(0, time.time() - epoch)
    if seconds < 60: return f"{seconds:.0f}s ago"
    if seconds < 3600: return f"{seconds/60:.1f}m ago"
    return f"{seconds/3600:.1f}h ago"


def fmt_bytes(value: object) -> str:
    if not isinstance(value, (int, float)): return "—"
    amount = float(value)
    for suffix in ("B", "KB", "MB", "GB", "TB"):
        if abs(amount) < 1024: return f"{amount:.1f} {suffix}"
        amount /= 1024
    return f"{amount:.1f} PB"


def fmt_pct(value: object) -> str:
    return f"{float(value):.1f}%" if isinstance(value, (int, float)) else "—"


class Card(ttk.Frame):
    def __init__(self, master: tk.Misc, title: str, **kwargs: Any) -> None:
        super().__init__(master, style="Card.TFrame", padding=14, **kwargs)
        ttk.Label(self, text=title, style="CardTitle.TLabel").pack(anchor="w")
        self.value = ttk.Label(self, text="—", style="CardValue.TLabel", wraplength=320)
        self.value.pack(anchor="w", pady=(7, 2))
        self.sub = ttk.Label(self, text="", style="CardSub.TLabel", wraplength=340)
        self.sub.pack(anchor="w")

    def set(self, value: str, sub: str = "") -> None:
        self.value.configure(text=value); self.sub.configure(text=sub)


class UsageGraph(tk.Canvas):
    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, bg=PANEL, highlightthickness=0, height=230)
        self.rows: list[dict[str, Any]] = []
        self.bind("<Configure>", lambda _event: self.redraw())

    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows; self.redraw()

    def redraw(self) -> None:
        self.delete("all"); width=max(100,self.winfo_width()); height=max(100,self.winfo_height())
        left, top, right, bottom = 48, 18, width-18, height-32
        self.create_rectangle(left, top, right, bottom, outline="#30363d")
        for pct in (0,25,50,75,100):
            y = bottom - (bottom-top)*pct/100
            self.create_line(left,y,right,y,fill="#21262d"); self.create_text(left-8,y,text=str(pct),fill=MUTED,anchor="e",font=("Segoe UI",8))
        points: dict[str,list[tuple[float,float]]] = {"Primary":[],"Secondary":[]}
        if self.rows:
            times=[float(row.get("ts") or 0) for row in self.rows]; lo=min(times); hi=max(times); span=max(1.0,hi-lo)
            for row in self.rows:
                x=left+(right-left)*(float(row.get("ts") or lo)-lo)/span
                for window in row.get("windows") or []:
                    label=str(window.get("label") or ""); used=window.get("used_percent")
                    if label in points and isinstance(used,(int,float)):
                        y=bottom-(bottom-top)*max(0,min(100,float(used)))/100; points[label].append((x,y))
        for label, color in (("Primary",ACCENT),("Secondary",PURPLE)):
            pts=points[label]
            if len(pts)>=2: self.create_line(*[coord for p in pts for coord in p],fill=color,width=2,smooth=True)
            elif pts: self.create_oval(pts[0][0]-2,pts[0][1]-2,pts[0][0]+2,pts[0][1]+2,fill=color,outline=color)
        self.create_text(left, height-14, text="Quota used % — last 24h (when provider reports it)", fill=MUTED, anchor="w", font=("Segoe UI",9))
        self.create_text(right-150, top+8, text="Primary", fill=ACCENT, anchor="w", font=("Segoe UI",9,"bold"))
        self.create_text(right-75, top+8, text="Secondary", fill=PURPLE, anchor="w", font=("Segoe UI",9,"bold"))


class ControlCenter(tk.Tk):
    def __init__(self) -> None:
        super().__init__(); self.title("CotS Development Control Center — 24x7"); self.geometry("1480x900"); self.minsize(1180,760)
        self.configure(bg=BG); self.telemetry=DailyTelemetry(); self.token=ensure_control_token(); self.ledger=ProviderUsageLedger(); self.metrics=OperationalMetrics(); self.local_ai=LocalAI()
        self.selected_day: str|None=None; self.last_day_list:list[str]=[]; self._last_log_tail=""; self._setup_styles(); self._build(); self.after(250,self.refresh)

    def _setup_styles(self) -> None:
        style=ttk.Style(self); style.theme_use("clam")
        style.configure(".",background=BG,foreground=FG,fieldbackground=PANEL,font=("Segoe UI",10))
        style.configure("TFrame",background=BG); style.configure("Card.TFrame",background=PANEL,relief="flat")
        style.configure("TLabel",background=BG,foreground=FG); style.configure("Header.TLabel",font=("Segoe UI",20,"bold"),background=BG,foreground=FG)
        style.configure("Muted.TLabel",background=BG,foreground=MUTED); style.configure("CardTitle.TLabel",background=PANEL,foreground=MUTED,font=("Segoe UI",10,"bold"))
        style.configure("CardValue.TLabel",background=PANEL,foreground=FG,font=("Segoe UI",16,"bold")); style.configure("CardSub.TLabel",background=PANEL,foreground=MUTED,font=("Segoe UI",9))
        style.configure("TButton",background=PANEL2,foreground=FG,padding=(12,7),borderwidth=0); style.map("TButton",background=[("active","#30363d")])
        style.configure("TNotebook",background=BG,borderwidth=0); style.configure("TNotebook.Tab",background=PANEL,foreground=MUTED,padding=(14,8)); style.map("TNotebook.Tab",background=[("selected",PANEL2)],foreground=[("selected",FG)])
        style.configure("TProgressbar",background=ACCENT,troughcolor="#30363d",borderwidth=0)
        style.configure("Treeview",background=PANEL,fieldbackground=PANEL,foreground=FG,rowheight=27,borderwidth=0); style.configure("Treeview.Heading",background=PANEL2,foreground=FG)

    def _build(self) -> None:
        header=ttk.Frame(self,padding=(16,14)); header.pack(fill="x")
        left=ttk.Frame(header); left.pack(side="left"); ttk.Label(left,text="CotS Development Control Center",style="Header.TLabel").pack(anchor="w"); ttk.Label(left,text="24/7 autonomous engineering · local observability first",style="Muted.TLabel").pack(anchor="w",pady=(2,0))
        self.state_badge=tk.Label(header,text="STARTING",bg=PANEL2,fg=ACCENT,font=("Segoe UI",10,"bold"),padx=14,pady=7); self.state_badge.pack(side="right")
        controls=ttk.Frame(self,padding=(16,0,16,12)); controls.pack(fill="x")
        for text,cmd in (("Run 24/7",self.start_watchdog),("Stop Safely",self.stop_safe),("Restart Stack",self.restart_stack),("Open Telemetry",lambda:webbrowser.open(LOCAL_URL)),("Logs Folder",self.open_logs_folder),("Support Bundle",self.create_bundle)):
            ttk.Button(controls,text=text,command=cmd).pack(side="left",padx=(0,7))
        ttk.Label(controls,text="Closing this window does not stop the watchdog.",style="Muted.TLabel").pack(side="right")
        self.tabs=ttk.Notebook(self); self.tabs.pack(fill="both",expand=True,padx=16,pady=(0,16))
        self.pages={name:ttk.Frame(self.tabs,padding=14) for name in ("Overview","Provider Usage","Productivity","Hardware","Daily Logs","Local AI","Chaos / Recovery","Diagnostics","Remote / Tunnel")}
        for name,page in self.pages.items(): self.tabs.add(page,text=name)
        self._build_overview(); self._build_usage(); self._build_productivity(); self._build_hardware(); self._build_logs(); self._build_local_ai(); self._build_chaos(); self._build_diagnostics(); self._build_remote()

    def _grid_cards(self,page:ttk.Frame,titles:list[str]) -> list[Card]:
        cards=[]
        for i,title in enumerate(titles):
            page.columnconfigure(i,weight=1,uniform="cards"); card=Card(page,title); card.grid(row=0,column=i,sticky="nsew",padx=(0 if i==0 else 6,0 if i==len(titles)-1 else 6)); cards.append(card)
        return cards

    def _build_overview(self) -> None:
        page=self.pages["Overview"]; self.overview_cards=self._grid_cards(page,["SYSTEM","PRODUCTIVITY","24H UPTIME","CODEX QUOTA"])
        body=ttk.Frame(page); body.grid(row=1,column=0,columnspan=4,sticky="nsew",pady=(14,0)); page.rowconfigure(1,weight=1); body.columnconfigure(0,weight=1); body.columnconfigure(1,weight=1); body.rowconfigure(1,weight=1)
        self.state_tree=ttk.Treeview(body,columns=("value",),show="tree headings",height=10); self.state_tree.heading("#0",text="Autonomy state"); self.state_tree.heading("value",text="Value"); self.state_tree.column("#0",width=190); self.state_tree.grid(row=0,column=0,sticky="nsew",padx=(0,7))
        self.report_tree=ttk.Treeview(body,columns=("value",),show="tree headings",height=10); self.report_tree.heading("#0",text="24h engineering report"); self.report_tree.heading("value",text="Value"); self.report_tree.column("#0",width=190); self.report_tree.grid(row=0,column=1,sticky="nsew",padx=(7,0))
        activity=ttk.Frame(body,style="Card.TFrame",padding=12); activity.grid(row=1,column=0,columnspan=2,sticky="nsew",pady=(14,0)); activity.rowconfigure(1,weight=1); activity.columnconfigure(0,weight=1)
        ttk.Label(activity,text="RECENT LOCAL ACTIVITY",style="CardTitle.TLabel").grid(row=0,column=0,sticky="w",pady=(0,8)); self.activity_text=tk.Text(activity,bg=PANEL,fg=FG,insertbackground=FG,relief="flat",wrap="word",height=12,font=("Cascadia Mono",9)); self.activity_text.grid(row=1,column=0,sticky="nsew")

    def _build_usage(self) -> None:
        page=self.pages["Provider Usage"]; page.columnconfigure(0,weight=1); page.columnconfigure(1,weight=1); page.rowconfigure(2,weight=1)
        self.quota_cards=self._grid_cards(page,["PRIMARY WINDOW","SECONDARY WINDOW","TURN SUCCESS","RATE LIMITS"])
        details=ttk.Frame(page,style="Card.TFrame",padding=14); details.grid(row=1,column=0,columnspan=4,sticky="ew",pady=(14,0)); details.columnconfigure(1,weight=1)
        ttk.Label(details,text="Quota telemetry",style="CardTitle.TLabel").grid(row=0,column=0,sticky="w",columnspan=2,pady=(0,8))
        self.quota_bars=[]; self.quota_labels=[]
        for row,label in enumerate(("Primary","Secondary"),start=1):
            ttk.Label(details,text=label,style="CardSub.TLabel").grid(row=row,column=0,sticky="w",padx=(0,12),pady=6); bar=ttk.Progressbar(details,maximum=100); bar.grid(row=row,column=1,sticky="ew",pady=6); value=ttk.Label(details,text="Not reported",style="CardSub.TLabel"); value.grid(row=row,column=2,sticky="e",padx=(12,0)); self.quota_bars.append(bar); self.quota_labels.append(value)
        self.usage_graph=UsageGraph(page); self.usage_graph.grid(row=2,column=0,columnspan=4,sticky="nsew",pady=(14,0))
        self.usage_note=ttk.Label(page,text="",style="Muted.TLabel",wraplength=1200); self.usage_note.grid(row=3,column=0,columnspan=4,sticky="w",pady=(10,0))

    def _build_productivity(self) -> None:
        page=self.pages["Productivity"]; self.product_cards=self._grid_cards(page,["USEFUL / OBSERVED TURNS","COMMITS / TURN","TESTS / TURN","GOVERNOR"])
        self.product_text=tk.Text(page,bg=PANEL,fg=FG,insertbackground=FG,relief="flat",wrap="word",font=("Cascadia Mono",9)); self.product_text.grid(row=1,column=0,columnspan=4,sticky="nsew",pady=(14,0)); page.rowconfigure(1,weight=1)

    def _build_hardware(self) -> None:
        page=self.pages["Hardware"]; self.hardware_cards=self._grid_cards(page,["GPU","MEMORY","DISK","NETWORK"])
        self.hardware_text=tk.Text(page,bg=PANEL,fg=FG,insertbackground=FG,relief="flat",wrap="word",font=("Cascadia Mono",9)); self.hardware_text.grid(row=1,column=0,columnspan=4,sticky="nsew",pady=(14,0)); page.rowconfigure(1,weight=1)

    def _build_logs(self) -> None:
        page=self.pages["Daily Logs"]; pane=ttk.Panedwindow(page,orient="horizontal"); pane.pack(fill="both",expand=True); left=ttk.Frame(pane); right=ttk.Frame(pane); pane.add(left,weight=1); pane.add(right,weight=5)
        ttk.Label(left,text="Days",style="CardTitle.TLabel").pack(anchor="w",pady=(0,7)); self.day_list=tk.Listbox(left,bg=PANEL,fg=FG,selectbackground=PANEL2,relief="flat",exportselection=False); self.day_list.pack(fill="both",expand=True); self.day_list.bind("<<ListboxSelect>>",self.on_day_select)
        ttk.Label(right,text="Simplified local activity log — no Codex/Claude usage",style="CardTitle.TLabel").pack(anchor="w",pady=(0,7)); self.log_text=tk.Text(right,bg=PANEL,fg=FG,insertbackground=FG,relief="flat",wrap="none",font=("Cascadia Mono",9)); self.log_text.pack(fill="both",expand=True)

    def _build_local_ai(self) -> None:
        page=self.pages["Local AI"]; page.columnconfigure(0,weight=1); page.rowconfigure(3,weight=1)
        self.local_ai_status=ttk.Label(page,text="Checking local Ollama…",font=("Segoe UI",14,"bold")); self.local_ai_status.grid(row=0,column=0,sticky="w")
        ttk.Label(page,text="Local AI is restricted to 127.0.0.1 Ollama. It can classify logs, cluster failures, choose runbooks and write daily summaries without cloud-token usage.",style="Muted.TLabel",wraplength=1100).grid(row=1,column=0,sticky="w",pady=(6,12))
        buttons=ttk.Frame(page); buttons.grid(row=2,column=0,sticky="w",pady=(0,10)); ttk.Button(buttons,text="Analyze Recent Logs",command=self.analyze_local).pack(side="left",padx=(0,7)); ttk.Button(buttons,text="Summarize Today Locally",command=self.summarize_today).pack(side="left")
        self.local_ai_text=tk.Text(page,bg=PANEL,fg=FG,insertbackground=FG,relief="flat",wrap="word",font=("Cascadia Mono",9)); self.local_ai_text.grid(row=3,column=0,sticky="nsew")

    def _build_chaos(self) -> None:
        page=self.pages["Chaos / Recovery"]; page.columnconfigure(0,weight=1); page.rowconfigure(2,weight=1)
        ttk.Label(page,text="Safe chaos testing",font=("Segoe UI",14,"bold")).grid(row=0,column=0,sticky="w"); ttk.Label(page,text="Runs deterministic local simulations for process death, malformed provider data, fake quota exhaustion, recovery gates and rollback primitives. It does not disable your real network or kill unrelated processes.",style="Muted.TLabel",wraplength=1100).grid(row=1,column=0,sticky="w",pady=(6,10))
        ttk.Button(page,text="Run Safe Chaos Suite",command=self.run_chaos).grid(row=1,column=0,sticky="e",pady=(6,10)); self.chaos_text=tk.Text(page,bg=PANEL,fg=FG,insertbackground=FG,relief="flat",wrap="word",font=("Cascadia Mono",9)); self.chaos_text.grid(row=2,column=0,sticky="nsew")

    def _build_diagnostics(self) -> None:
        page=self.pages["Diagnostics"]; page.columnconfigure(0,weight=1); page.rowconfigure(1,weight=1); ttk.Label(page,text="Raw local state",style="CardTitle.TLabel").grid(row=0,column=0,sticky="w",pady=(0,7)); self.diag_text=tk.Text(page,bg=PANEL,fg=FG,insertbackground=FG,relief="flat",wrap="none",font=("Cascadia Mono",9)); self.diag_text.grid(row=1,column=0,sticky="nsew")

    def _build_remote(self) -> None:
        page=self.pages["Remote / Tunnel"]; page.columnconfigure(0,weight=1); page.rowconfigure(5,weight=1); ttk.Label(page,text="Private remote telemetry",font=("Segoe UI",14,"bold")).grid(row=0,column=0,sticky="w"); ttk.Label(page,text="Tailscale Serve exposes only the localhost telemetry/control endpoint to your private tailnet. For full shell access use Windows OpenSSH over Tailscale; do not expose SSH to the public Internet.",style="Muted.TLabel",wraplength=1100).grid(row=1,column=0,sticky="w",pady=(6,10))
        self.remote_status=tk.StringVar(value="Checking Tailscale…"); ttk.Label(page,textvariable=self.remote_status).grid(row=2,column=0,sticky="w",pady=4); ttk.Label(page,text=f"Local endpoint: {LOCAL_URL}",style="Muted.TLabel").grid(row=3,column=0,sticky="w")
        buttons=ttk.Frame(page); buttons.grid(row=4,column=0,sticky="w",pady=10); ttk.Button(buttons,text="Enable Tailscale Serve",command=self.enable_tailscale).pack(side="left",padx=(0,7)); ttk.Button(buttons,text="Copy Control Token",command=self.copy_token).pack(side="left",padx=(0,7)); ttk.Button(buttons,text="Open Local Endpoint",command=lambda:webbrowser.open(LOCAL_URL)).pack(side="left")
        self.remote_output=tk.Text(page,bg=PANEL,fg=FG,insertbackground=FG,relief="flat",wrap="word",font=("Cascadia Mono",9)); self.remote_output.grid(row=5,column=0,sticky="nsew")

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
        folder=COTS/"telemetry"; folder.mkdir(parents=True,exist_ok=True); os.startfile(folder) if os.name=="nt" else webbrowser.open(folder.as_uri())  # type: ignore[attr-defined]
    def create_bundle(self) -> None:
        try:
            path=create_support_bundle(); os.startfile(path.parent) if os.name=="nt" else webbrowser.open(path.parent.as_uri())  # type: ignore[attr-defined]
            messagebox.showinfo("CotS 24x7",f"Support bundle created:\n{path}")
        except Exception as error: messagebox.showerror("CotS 24x7",str(error))
    def copy_token(self) -> None: self.clipboard_clear(); self.clipboard_append(self.token); self.update(); messagebox.showinfo("CotS 24x7","Control token copied.")

    def enable_tailscale(self) -> None:
        exe=shutil.which("tailscale")
        if not exe: messagebox.showinfo("Tailscale","Tailscale CLI not found."); return
        try:
            result=subprocess.run([exe,"serve","--bg","http://127.0.0.1:8765"],text=True,capture_output=True,timeout=30,check=False); self.remote_output.delete("1.0","end"); self.remote_output.insert("1.0",(result.stdout+"\n"+result.stderr).strip())
        except Exception as error: messagebox.showerror("Tailscale",str(error))

    def _background(self, func: Any, callback: Any) -> None:
        def worker() -> None:
            try: result=func()
            except Exception as error: result={"error":str(error)}
            self.after(0,lambda:callback(result))
        threading.Thread(target=worker,daemon=True).start()

    def analyze_local(self) -> None:
        days=self.telemetry.list_days(); text=self.telemetry.read_day(days[0])[-12000:] if days else "No logs yet"
        self.local_ai_text.delete("1.0","end"); self.local_ai_text.insert("1.0","Running local analysis…")
        self._background(lambda:self.local_ai.classify(text),lambda value:(self.local_ai_text.delete("1.0","end"),self.local_ai_text.insert("1.0",json.dumps(value,indent=2,default=str))))

    def summarize_today(self) -> None:
        days=self.telemetry.list_days()
        if not days: messagebox.showinfo("Local AI","No daily log exists yet."); return
        self._background(lambda:self.local_ai.summarize_day(days[0]),lambda path:messagebox.showinfo("Local AI",f"Local summary: {path}"))

    def run_chaos(self) -> None:
        self.chaos_text.delete("1.0","end"); self.chaos_text.insert("1.0","Running safe chaos suite…")
        def run() -> dict[str,Any]:
            result=subprocess.run([sys.executable,str(CHAOS)],cwd=REPO,text=True,capture_output=True,timeout=240,check=False); return {"exit_code":result.returncode,"stdout":result.stdout,"stderr":result.stderr}
        self._background(run,lambda value:(self.chaos_text.delete("1.0","end"),self.chaos_text.insert("1.0",json.dumps(value,indent=2))))

    def on_day_select(self,_event:object=None) -> None:
        selection=self.day_list.curselection()
        if selection:self.selected_day=self.day_list.get(selection[0]); self.refresh_log_text()
    def refresh_log_text(self) -> None:
        day=self.selected_day or (self.last_day_list[0] if self.last_day_list else None)
        if day:self.log_text.delete("1.0","end"); self.log_text.insert("1.0",self.telemetry.read_day(day)); self.log_text.see("end")

    @staticmethod
    def _fill_tree(tree:ttk.Treeview, values:list[tuple[str,str]]) -> None:
        for item in tree.get_children(): tree.delete(item)
        for key,value in values: tree.insert("", "end", text=key, values=(value,))

    def _refresh_overview(self,health:dict[str,Any],supervisor:dict[str,Any],usage:dict[str,Any],governor:dict[str,Any],report:dict[str,Any]) -> None:
        alive=bool(health.get("alive",pid_live(health.get("pid")))); productive=bool(health.get("productive")); self.overview_cards[0].set("ALIVE" if alive else "OFFLINE",f"Watchdog {health.get('state') or '—'} · factory {health.get('factory_state') or '—'}")
        self.overview_cards[1].set("PRODUCTIVE" if productive else "IDLE / RECOVERING",f"{governor.get('useful_turns',0)} useful turns · {governor.get('unproductive_turns',0)} current no-value streak")
        uptime=report.get("uptime_percent"); self.overview_cards[2].set(fmt_pct(uptime),f"{report.get('recoveries',0)} recoveries · {report.get('human_interventions',0)} human interventions")
        quota=usage.get("codex_quota") or {}; windows=quota.get("windows") or []; primary=windows[0] if windows else None
        if primary and isinstance(primary.get("used_percent"),(int,float)):
            used=float(primary["used_percent"]); self.overview_cards[3].set(f"{used:.0f}% used · {100-used:.0f}% left",format_reset(primary.get("reset_at")))
        elif quota.get("exhausted"): self.overview_cards[3].set("EXHAUSTED",quota.get("fallback_reset_text") or "Reset not reported")
        else:self.overview_cards[3].set("% NOT REPORTED",quota.get("fallback_reset_text") or "Waiting for provider rate-limit telemetry")
        self._fill_tree(self.state_tree,[("Watchdog",str(health.get("state") or "—")),("Factory",str(health.get("factory_state") or "—")),("Supervisor",str(health.get("supervisor_state") or supervisor.get("state") or "—")),("Task",str(health.get("task") or supervisor.get("task") or "—")),("Phase",str(health.get("phase") or supervisor.get("phase") or "—")),("Provider",str(health.get("active_agent") or supervisor.get("active_agent") or "none")),("Current action",str(health.get("current_action") or "—")),("Last progress",fmt_age(health.get("last_progress_at")))])
        self._fill_tree(self.report_tree,[("Uptime",fmt_pct(report.get("uptime_percent"))),("Useful turns",str(report.get("useful_turns",0))),("Commits",str(report.get("commits",0))),("Tests",str(report.get("tests",0))),("Acceptance proofs",str(report.get("acceptance_proofs",0))),("Recoveries",str(report.get("recoveries",0))),("Human interventions",str(report.get("human_interventions",0))), ("Productive time",fmt_pct(report.get("productive_percent")))])
        days=self.telemetry.list_days(); tail=self.telemetry.read_day(days[0])[-8000:] if days else "No local activity yet."
        if tail!=self._last_log_tail:self._last_log_tail=tail; self.activity_text.delete("1.0","end"); self.activity_text.insert("1.0","\n".join(tail.splitlines()[-16:])); self.activity_text.see("end")

    def _refresh_usage(self,usage:dict[str,Any],governor:dict[str,Any]) -> None:
        codex=usage.get("codex") or {}; quota=usage.get("codex_quota") or {}; windows=quota.get("windows") or []
        for i in range(2):
            window=windows[i] if i<len(windows) else None
            if window:
                used=window.get("used_percent"); reset=format_reset(window.get("reset_at")); label=window.get("label") or ("Primary" if i==0 else "Secondary")
                if isinstance(used,(int,float)):
                    self.quota_cards[i].set(f"{float(used):.1f}% used",f"{100-float(used):.1f}% remaining · resets {reset}"); self.quota_bars[i]["value"]=float(used); self.quota_labels[i].configure(text=f"{float(used):.1f}% · {reset}")
                else:self.quota_cards[i].set("Usage % not reported",f"Reset: {reset}"); self.quota_bars[i]["value"]=0; self.quota_labels[i].configure(text=f"Not reported · {reset}")
            else:
                fallback=quota.get("fallback_reset_text") if i==0 else "Not reported"; self.quota_cards[i].set("Not reported",str(fallback or "Waiting for provider telemetry")); self.quota_bars[i]["value"]=0; self.quota_labels[i].configure(text=str(fallback or "Not reported"))
        completed=int(codex.get("turns_completed") or 0); failed=int(codex.get("turns_failed") or 0); success=max(0,completed-failed); rate=(100*success/completed) if completed else None
        self.quota_cards[2].set(fmt_pct(rate),f"{success} successful · {failed} failed · {completed} completed")
        self.quota_cards[3].set(str(codex.get("usage_limit_hits") or 0),quota.get("last_usage_limit_message") or "No explicit rate-limit event recorded")
        self.usage_graph.set_rows(self.ledger.history(24))
        self.usage_note.configure(text="Exact plan remaining % is shown only when Codex reports it through account/rateLimits. If the provider omits it, the UI says 'Not reported' rather than inventing a number. Explicit usage-limit messages are still parsed locally for reset time.")

    def _refresh_productivity(self,governor:dict[str,Any]) -> None:
        observed=int(governor.get("observed_turns") or 0); useful=int(governor.get("useful_turns") or 0); commits=int(governor.get("commits") or 0); tests=int(governor.get("tests") or 0)
        self.product_cards[0].set(f"{useful} / {observed}",fmt_pct(100*useful/observed if observed else None))
        self.product_cards[1].set(f"{commits/observed:.2f}" if observed else "—",f"{commits} commits")
        self.product_cards[2].set(f"{tests/observed:.2f}" if observed else "—",f"{tests} test-evidence increments")
        streak=int(governor.get("unproductive_turns") or 0); threshold=int(governor.get("threshold") or 4); self.product_cards[3].set("PAUSED" if governor.get("tripped") else "ARMED",f"{streak}/{threshold} unproductive turns · trips {governor.get('trips',0)}")
        self.product_text.delete("1.0","end"); self.product_text.insert("1.0",json.dumps(governor,indent=2,default=str))

    def _refresh_hardware(self,hardware:dict[str,Any]) -> None:
        gpu=hardware.get("gpu") or {}; mem=hardware.get("memory") or {}; disk=hardware.get("disk") or {}; net=hardware.get("network") or {}; unreal=hardware.get("unreal") or {}; cpu=hardware.get("cpu") or {}
        self.hardware_cards[0].set(f"{gpu.get('temperature_c','—')} °C",f"GPU {fmt_pct(gpu.get('utilization_percent'))} · VRAM {gpu.get('vram_used_mb','—')}/{gpu.get('vram_total_mb','—')} MB")
        self.hardware_cards[1].set(fmt_pct(mem.get("used_percent")),f"{fmt_bytes(mem.get('free_bytes'))} free · CPU load {fmt_pct(cpu.get('load_percent'))}")
        self.hardware_cards[2].set(f"{float(disk.get('free_gb')):.1f} GB free" if isinstance(disk.get('free_gb'),(int,float)) else "—", "Factory pauses below 10 GB")
        self.hardware_cards[3].set("ONLINE" if net.get("online") else "OFFLINE",f"Probe {net.get('probe_ms','—')} ms · Unreal {unreal.get('processes',0)} process(es), {fmt_bytes(unreal.get('working_set_bytes'))}")
        self.hardware_text.delete("1.0","end"); self.hardware_text.insert("1.0",json.dumps(hardware,indent=2,default=str))

    def refresh(self) -> None:
        try:
            self.ledger.poll(); usage=self.ledger.snapshot(); health=read_json(HEALTH_PATH); supervisor=read_json(SUPERVISOR_STATE); factory=read_json(FACTORY_STATE); governor=read_json(GOVERNOR_STATE); hardware=read_json(HARDWARE_STATE); report=(health.get("report_24h") if isinstance(health.get("report_24h"),dict) else self.metrics.report())
            state=str(health.get("state") if pid_live(health.get("pid")) else "STOPPED"); badge_color=GOOD if state in {"RUNNING","ROADMAP_COMPLETE"} else WARN if any(k in state for k in ("PAUSED","COOLDOWN","REPAIR")) else BAD if state in {"HUMAN_REQUIRED","STOPPED"} else ACCENT; self.state_badge.configure(text=state,bg=badge_color,fg="#ffffff")
            self._refresh_overview(health,supervisor,usage,governor,report); self._refresh_usage(usage,governor); self._refresh_productivity(governor); self._refresh_hardware(hardware)
            self.local_ai_status.configure(text=f"Local AI: {'READY' if self.local_ai.available else 'NOT INSTALLED/NO MODEL'}" + (f" · {self.local_ai.model}" if self.local_ai.model else ""))
            days=self.telemetry.list_days()
            if days!=self.last_day_list:
                self.last_day_list=days; self.day_list.delete(0,"end"); [self.day_list.insert("end",day) for day in days]
                if self.selected_day not in days:self.selected_day=days[0] if days else None; self.day_list.selection_set(0) if days else None
            if self.tabs.tab(self.tabs.select(),"text")=="Daily Logs" and self.selected_day:self.refresh_log_text()
            raw={"watchdog":health,"factory":factory,"supervisor":supervisor,"usage":usage,"governor":governor,"hardware":hardware,"rollback":read_json(ROLLBACK_STATE)}; self.diag_text.delete("1.0","end"); self.diag_text.insert("1.0",json.dumps(raw,indent=2,default=str))
            chaos=read_json(CHAOS_STATE)
            if chaos and self.chaos_text.get("1.0","end").strip() in {"","Running safe chaos suite…"}: self.chaos_text.delete("1.0","end"); self.chaos_text.insert("1.0",json.dumps(chaos,indent=2,default=str))
            tailscale=shutil.which("tailscale")
            if tailscale:
                try:
                    result=subprocess.run([tailscale,"status","--json"],text=True,capture_output=True,timeout=4,check=False); info=json.loads(result.stdout) if result.stdout.strip().startswith("{") else {}; self.remote_status.set(f"Tailscale: {info.get('BackendState','installed')} · {((info.get('Self') or {}).get('DNSName') or '').rstrip('.') or 'no DNS name'}")
                except Exception:self.remote_status.set("Tailscale installed; status unavailable")
            else:self.remote_status.set("Tailscale CLI not found")
        except Exception as error:self.state_badge.configure(text=f"UI ERROR: {clean_text(error,100)}",bg=BAD)
        finally:self.after(1000,self.refresh)


if __name__=="__main__": ControlCenter().mainloop()
