"""Helpers for webhook consumers that auto-trigger ``retry_batch`` from delivery payloads."""

from __future__ import annotations

from typing import Any


def extract_webhook_retry_suggestions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return ``retry_batch`` entries from a ``run_finished`` webhook body."""
    if str(payload.get("event") or "") != "run_finished":
        return []
    batch = payload.get("batch")
    if not isinstance(batch, dict):
        return []
    raw = batch.get("retry_suggestions")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        if str(item.get("action") or "") != "retry_batch":
            continue
        run_id = str(item.get("run_id") or "").strip()
        if not run_id:
            continue
        out.append(item)
    return out


def filter_retry_buckets(
    suggestions: list[dict[str, Any]],
    *,
    allowed_buckets: set[str] | None = None,
) -> list[dict[str, Any]]:
    if not allowed_buckets:
        return suggestions
    return [
        item
        for item in suggestions
        if str(item.get("failure_bucket") or "failed").strip() in allowed_buckets
    ]
