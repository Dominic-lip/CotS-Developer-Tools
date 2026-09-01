#!/usr/bin/env python3
"""Optional local-only AI helper for CotS 24x7.

This module talks only to an Ollama server bound to localhost.  It is used for
log classification, duplicate-error clustering, daily summaries and runbook
selection.  If Ollama is absent, deterministic local heuristics remain in use.
No cloud provider fallback exists by design.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from CotS24x7Common import COTS, DailyTelemetry, clean_text

OLLAMA = os.environ.get("COTS_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
PREFERRED_MODELS = (
    os.environ.get("COTS_LOCAL_AI_MODEL", "").strip(),
    "qwen2.5-coder:14b", "qwen2.5-coder:7b", "qwen2.5-coder:7b-instruct",
    "llama3.1:8b", "mistral:7b",
)
SUMMARY_DIR = COTS / "telemetry"


def _request(path: str, payload: dict[str, Any] | None = None, timeout: float = 45.0) -> Any:
    url = OLLAMA + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def available_models() -> list[str]:
    try:
        value = _request("/api/tags", timeout=2.0)
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return []
    models = value.get("models") if isinstance(value, dict) else []
    result: list[str] = []
    for item in models if isinstance(models, list) else []:
        if isinstance(item, dict):
            name = item.get("name") or item.get("model")
            if isinstance(name, str): result.append(name)
    return result


def choose_model() -> str | None:
    installed = available_models()
    if not installed: return None
    lower = {name.lower(): name for name in installed}
    for preferred in PREFERRED_MODELS:
        if not preferred: continue
        if preferred.lower() in lower: return lower[preferred.lower()]
        stem = preferred.split(":", 1)[0].lower()
        match = next((name for name in installed if name.lower().split(":", 1)[0] == stem), None)
        if match: return match
    return installed[0]


def deterministic_classify(text: str) -> dict[str, Any]:
    lower = text.lower()
    categories = []
    mapping = {
        "provider_quota": ("usage limit", "rate limit", "usage_exhausted"),
        "authentication": ("authentication required", "login required", "mfa", "2fa"),
        "process_lifecycle": ("invalid_pid", "open_process_failed", "process exited", "dead"),
        "schema_or_protocol": ("typeerror", "json", "protocol", "not iterable"),
        "build": ("compile", "build failed", "automation test", "unrealbuildtool"),
        "network": ("network", "timeout", "connection", "dns"),
    }
    for category, needles in mapping.items():
        if any(needle in lower for needle in needles): categories.append(category)
    return {
        "source": "heuristic", "categories": categories or ["unknown"],
        "cloud_wake_recommended": not any(c in categories for c in ("provider_quota", "authentication", "process_lifecycle")),
        "summary": clean_text(text, 600),
    }


class LocalAI:
    def __init__(self) -> None:
        self.model = choose_model()
        self.telemetry = DailyTelemetry()

    @property
    def available(self) -> bool: return bool(self.model)

    def generate(self, prompt: str, timeout: float = 120.0) -> str | None:
        if not self.model: return None
        try:
            value = _request("/api/generate", {
                "model": self.model, "prompt": prompt, "stream": False,
                "options": {"temperature": 0.1, "num_ctx": 8192},
            }, timeout=timeout)
            text = value.get("response") if isinstance(value, dict) else None
            return clean_text(text, 12000) if isinstance(text, str) else None
        except Exception as error:
            self.telemetry.emit("LOCAL_AI_ERROR", f"Local Ollama analysis failed safely: {error}", model=self.model)
            return None

    def classify(self, text: str) -> dict[str, Any]:
        fallback = deterministic_classify(text)
        if not self.model: return fallback
        prompt = (
            "You are a local operations classifier. Analyze this CotS autonomous-development log excerpt. "
            "Return JSON only with keys: categories (array), duplicate_signature (short string), "
            "recommended_runbook (short string), cloud_wake_recommended (boolean), summary (one sentence). "
            "Prefer local recovery for process, telemetry, quota, network and hardware faults.\n\nLOG:\n" + text[-10000:]
        )
        response = self.generate(prompt, 90)
        if not response: return fallback
        match = re.search(r"\{.*\}", response, re.DOTALL)
        try:
            value = json.loads(match.group(0) if match else response)
            if isinstance(value, dict):
                value["source"] = "ollama"; value["model"] = self.model; return value
        except json.JSONDecodeError:
            pass
        return fallback

    def should_wake_cloud(self, text: str) -> tuple[bool, dict[str, Any]]:
        analysis = self.classify(text)
        return bool(analysis.get("cloud_wake_recommended")), analysis

    def summarize_day(self, day: str) -> Path | None:
        log_path = SUMMARY_DIR / f"{day}.log"
        if not log_path.exists(): return None
        text = log_path.read_text(encoding="utf-8", errors="replace")[-80000:]
        if self.model:
            prompt = (
                "Summarize this autonomous software-development activity log locally. Be concise and factual. "
                "Include: useful work completed, failures/recoveries, provider usage concerns, tests/commits, and next likely action. "
                "Do not invent missing facts.\n\n" + text
            )
            summary = self.generate(prompt, 180)
        else:
            lines = [line for line in text.splitlines() if any(key in line for key in ("FACTORY_EXIT", "SUPERVISOR", "HUMAN", "BACKOFF", "STATE"))]
            summary = "Local AI unavailable; deterministic event digest:\n" + "\n".join(lines[-60:])
        if not summary: return None
        path = SUMMARY_DIR / f"{day}.local-summary.md"
        path.write_text(f"# CotS local summary — {day}\n\n{summary}\n", encoding="utf-8")
        return path


if __name__ == "__main__":
    ai = LocalAI()
    print(json.dumps({"available": ai.available, "model": ai.model, "models": available_models()}, indent=2))
