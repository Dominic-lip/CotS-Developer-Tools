#!/usr/bin/env python3
"""Forward-compatible Codex App Server turn/item normalization."""
from __future__ import annotations

from typing import Any


def normalize_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        # Future protocol shapes may wrap the actual list.
        for key in ("items", "content", "results"):
            nested = value.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
        return [value]
    # Integer/null/scalar values are metadata/counts, never iterable items.
    return []


def activity_count(value: Any, completed_items: list[dict[str, Any]] | None = None) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float) and value.is_integer():
        return max(0, int(value))
    normalized = normalize_items(value)
    if normalized:
        return len(normalized)
    return len(completed_items or [])


def extract_text(turn: dict[str, Any], completed_items: list[dict[str, Any]] | None = None) -> str:
    items = normalize_items(turn.get("items"))
    if not items and completed_items:
        items = completed_items
    pieces: list[str] = []
    for item in items:
        if item.get("type") not in {"agentMessage", "message"}:
            continue
        value = item.get("text", item.get("content", ""))
        if isinstance(value, str):
            pieces.append(value)
        elif isinstance(value, list):
            for block in value:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    pieces.append(block["text"])
                elif isinstance(block, str):
                    pieces.append(block)
        elif value is not None:
            pieces.append(str(value))
    return "\n".join(piece for piece in pieces if piece)


def completed_item_from_notification(message: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    if message.get("method") != "item/completed":
        return None, None
    params = message.get("params")
    if not isinstance(params, dict):
        return None, None
    thread_id = params.get("threadId") or params.get("thread_id")
    item = params.get("item")
    return (str(thread_id) if thread_id else None, item if isinstance(item, dict) else None)
