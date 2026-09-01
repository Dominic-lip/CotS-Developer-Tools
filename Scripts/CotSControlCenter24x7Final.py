#!/usr/bin/env python3
"""Production entry point for the enhanced CotS 24x7 Control Center."""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk
from typing import Any

import CotSControlCenter24x7Enhanced as enhanced
from CotSUsageLedgerSafe import ReadMostlyProviderUsageLedger

# The GUI never waits behind the watchdog's writer lease. If the watchdog is
# polling quota, the UI displays the latest persisted snapshot instead.
enhanced.ProviderUsageLedger = ReadMostlyProviderUsageLedger
# Any Control Center fallback launch must start the production watchdog, not
# the intermediate enhanced entry point.
enhanced.WATCHDOG = enhanced.SCRIPTS / "CotSWatchdog24x7Final.py"


class QuotaGraph(tk.Canvas):
    """Two reported Codex quota windows over time; never invents missing data."""
    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, bg=enhanced.PANEL, highlightthickness=0, height=175)
        self.rows: list[dict[str, Any]] = []
        self.bind("<Configure>", lambda _event: self.redraw())

    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows; self.redraw()

    def redraw(self) -> None:
        self.delete("all"); width=max(100,self.winfo_width()); height=max(100,self.winfo_height())
        left,top,right,bottom=48,18,width-18,height-28
        self.create_rectangle(left,top,right,bottom,outline="#30363d")
        for pct in (0,25,50,75,100):
            y=bottom-(bottom-top)*pct/100; self.create_line(left,y,right,y,fill="#21262d"); self.create_text(left-8,y,text=str(pct),fill=enhanced.MUTED,anchor="e",font=("Segoe UI",8))
        if not self.rows:
            self.create_text((left+right)/2,(top+bottom)/2,text="Waiting for Codex quota samples",fill=enhanced.MUTED,font=("Segoe UI",10)); return
        times=[float(row.get("ts") or 0) for row in self.rows]; lo=min(times); hi=max(times); span=max(1.0,hi-lo)
        series: list[tuple[str,str,list[tuple[float,float]]]]=[]
        latest_windows=self.rows[-1].get("windows") if isinstance(self.rows[-1].get("windows"),list) else []
        for index,color in ((0,enhanced.ACCENT),(1,enhanced.PURPLE)):
            label=str((latest_windows[index] if index < len(latest_windows) else {}).get("label") or ("Primary" if index==0 else "Secondary"))
            pts=[]
            for row in self.rows:
                windows=row.get("windows") if isinstance(row.get("windows"),list) else []
                if index>=len(windows): continue
                used=windows[index].get("used_percent")
                if not isinstance(used,(int,float)): continue
                x=left+(right-left)*(float(row.get("ts") or lo)-lo)/span; y=bottom-(bottom-top)*max(0,min(100,float(used)))/100; pts.append((x,y))
            series.append((label,color,pts))
        for label,color,pts in series:
            if len(pts)>=2:self.create_line(*[c for p in pts for c in p],fill=color,width=2,smooth=True)
            elif pts:self.create_oval(pts[0][0]-2,pts[0][1]-2,pts[0][0]+2,pts[0][1]+2,fill=color,outline=color)
        legend_x=max(left+20,right-250)
        for offset,(label,color,_pts) in enumerate(series):
            self.create_text(legend_x+offset*120,top+8,text=label,fill=color,anchor="w",font=("Segoe UI",9,"bold"))
        self.create_text(left,height-12,text="Reported quota used % — last 24h",fill=enhanced.MUTED,anchor="w",font=("Segoe UI",9))


class TurnGraph(tk.Canvas):
    """Cumulative successful and failed provider turns from local protocol logs."""
    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, bg=enhanced.PANEL, highlightthickness=0, height=175)
        self.rows: list[dict[str, Any]]=[]; self.bind("<Configure>",lambda _event:self.redraw())
    def set_rows(self,rows:list[dict[str,Any]])->None:self.rows=rows; self.redraw()
    def redraw(self)->None:
        self.delete("all"); width=max(100,self.winfo_width()); height=max(100,self.winfo_height()); left,top,right,bottom=48,18,width-18,height-28
        self.create_rectangle(left,top,right,bottom,outline="#30363d")
        if not self.rows:
            self.create_text((left+right)/2,(top+bottom)/2,text="Waiting for provider turn samples",fill=enhanced.MUTED,font=("Segoe UI",10)); return
        times=[float(row.get("ts") or 0) for row in self.rows]; lo=min(times); hi=max(times); span=max(1.0,hi-lo)
        values=[]
        for row in self.rows:
            completed=int(row.get("turns_completed") or 0); failed=int(row.get("turns_failed") or 0); values.append((float(row.get("ts") or lo),max(0,completed-failed),max(0,failed)))
        ymax=max(1,max(max(success,failed) for _,success,failed in values))
        for fraction in (0,.25,.5,.75,1):
            y=bottom-(bottom-top)*fraction; self.create_line(left,y,right,y,fill="#21262d"); self.create_text(left-8,y,text=str(int(round(ymax*fraction))),fill=enhanced.MUTED,anchor="e",font=("Segoe UI",8))
        for index,color,label in ((1,enhanced.GOOD,"Successful"),(2,enhanced.BAD,"Failed")):
            pts=[]
            for ts,success,failed in values:
                value=(success,failed)[index-1]; x=left+(right-left)*(ts-lo)/span; y=bottom-(bottom-top)*value/ymax; pts.append((x,y))
            if len(pts)>=2:self.create_line(*[c for p in pts for c in p],fill=color,width=2,smooth=True)
            elif pts:self.create_oval(pts[0][0]-2,pts[0][1]-2,pts[0][0]+2,pts[0][1]+2,fill=color,outline=color)
            self.create_text(right-(170 if index==1 else 85),top+8,text=label,fill=color,anchor="w",font=("Segoe UI",9,"bold"))
        self.create_text(left,height-12,text="Provider turns — cumulative last 24h",fill=enhanced.MUTED,anchor="w",font=("Segoe UI",9))


def _recent_burn_rate(rows:list[dict[str,Any]],index:int=0)->float|None:
    samples=[]
    for row in rows:
        windows=row.get("windows") if isinstance(row.get("windows"),list) else []
        if index>=len(windows):continue
        used=windows[index].get("used_percent"); ts=row.get("ts")
        if isinstance(used,(int,float)) and isinstance(ts,(int,float)):samples.append((float(ts),float(used)))
    if len(samples)<2:return None
    start=0
    for i in range(1,len(samples)):
        if samples[i][1]+1 < samples[i-1][1]:start=i
    segment=samples[start:]
    if len(segment)<2:return None
    hours=(segment[-1][0]-segment[0][0])/3600
    if hours<=0.02:return None
    return max(0.0,(segment[-1][1]-segment[0][1])/hours)


def build_usage(self: Any) -> None:
    page=self.pages["Provider Usage"]
    for i in range(4): page.columnconfigure(i,weight=1,uniform="usage")
    page.rowconfigure(2,weight=1); page.rowconfigure(3,weight=1)
    self.quota_cards=self._grid_cards(page,["PRIMARY WINDOW","SECONDARY WINDOW","TURN SUCCESS","RATE LIMIT EVENTS"])
    details=ttk.Frame(page,style="Card.TFrame",padding=14); details.grid(row=1,column=0,columnspan=4,sticky="ew",pady=(14,0)); details.columnconfigure(1,weight=1)
    ttk.Label(details,text="CODEX QUOTA",style="CardTitle.TLabel").grid(row=0,column=0,sticky="w",columnspan=3,pady=(0,8))
    self.quota_bars=[]; self.quota_labels=[]
    for row,label in enumerate(("Primary","Secondary"),start=1):
        ttk.Label(details,text=label,style="CardSub.TLabel").grid(row=row,column=0,sticky="w",padx=(0,12),pady=5); bar=ttk.Progressbar(details,maximum=100); bar.grid(row=row,column=1,sticky="ew",pady=5); value=ttk.Label(details,text="Not reported",style="CardSub.TLabel"); value.grid(row=row,column=2,sticky="e",padx=(12,0)); self.quota_bars.append(bar); self.quota_labels.append(value)
    self.usage_graph=QuotaGraph(page); self.usage_graph.grid(row=2,column=0,columnspan=2,sticky="nsew",padx=(0,7),pady=(14,0))
    self.turn_graph=TurnGraph(page); self.turn_graph.grid(row=2,column=2,columnspan=2,sticky="nsew",padx=(7,0),pady=(14,0))
    self.usage_note=ttk.Label(page,text="",style="Muted.TLabel",wraplength=1300); self.usage_note.grid(row=3,column=0,columnspan=4,sticky="nw",pady=(12,0))


def refresh_usage(self: Any,usage:dict[str,Any],governor:dict[str,Any])->None:
    codex=usage.get("codex") or {}; quota=usage.get("codex_quota") or {}; windows=quota.get("windows") or []
    for i in range(2):
        window=windows[i] if i<len(windows) else None
        if window:
            used=window.get("used_percent"); reset=enhanced.format_reset(window.get("reset_at")); label=window.get("label") or ("Primary" if i==0 else "Secondary")
            if isinstance(used,(int,float)):
                self.quota_cards[i].set(f"{float(used):.1f}% used",f"{100-float(used):.1f}% left · {label} resets {reset}"); self.quota_bars[i]["value"]=float(used); self.quota_labels[i].configure(text=f"{float(used):.1f}% used · {100-float(used):.1f}% left · {reset}")
            else:
                self.quota_cards[i].set("Usage % not reported",f"{label} reset: {reset}"); self.quota_bars[i]["value"]=0; self.quota_labels[i].configure(text=f"Not reported · reset {reset}")
        else:
            fallback=quota.get("fallback_reset_text") if i==0 else "Not reported"; self.quota_cards[i].set("Not reported",str(fallback or "Waiting for provider telemetry")); self.quota_bars[i]["value"]=0; self.quota_labels[i].configure(text=str(fallback or "Not reported"))
    completed=int(codex.get("turns_completed") or 0); failed=int(codex.get("turns_failed") or 0); success=max(0,completed-failed); rate=(100*success/completed) if completed else None
    self.quota_cards[2].set(enhanced.fmt_pct(rate),f"{success} successful · {failed} failed · {completed} completed")
    self.quota_cards[3].set(str(codex.get("usage_limit_hits") or 0),quota.get("last_usage_limit_message") or "No explicit limit event recorded")
    rows=self.ledger.history(24); self.usage_graph.set_rows(rows); self.turn_graph.set_rows(rows)
    burn=_recent_burn_rate(rows,0)
    burn_text=f"Recent reported primary-window burn: ~{burn:.1f} percentage points/hour." if burn is not None else "Recent quota burn rate: insufficient reported samples."
    source=quota.get("last_rate_limits_source") or "provider protocol"
    self.usage_note.configure(text=f"{burn_text} Quota source: {source}. Exact used/remaining percentages appear only when Codex reports that bucket; missing buckets remain 'Not reported'. The quota probe reads account/rateLimits locally and does not start a model turn.")


enhanced.ControlCenter._build_usage = build_usage
enhanced.ControlCenter._refresh_usage = refresh_usage

if __name__ == "__main__":
    enhanced.ControlCenter().mainloop()
