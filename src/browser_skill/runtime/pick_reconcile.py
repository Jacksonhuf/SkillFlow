"""Align Pick Mode refs with a fresh page snapshot after teach-time clicks."""

from __future__ import annotations

from typing import Any

from browser_skill.models import BrowserSnapshot
from browser_skill.runtime.batch import _pick_sample_matches


def _element_display(element: dict[str, Any]) -> str:
    raw = element.get("value")
    if raw in (None, ""):
        raw = element.get("text")
    if raw in (None, ""):
        return ""
    return str(raw).strip()


def ref_for_pick_in_snapshot(
    snapshot: BrowserSnapshot,
    *,
    text: str,
    frame_index: int | None,
) -> str | None:
    sample = text.strip()
    if not sample:
        return None
    for element in snapshot.elements:
        if frame_index is not None and element.get("frame_index") != frame_index:
            continue
        display = _element_display(element)
        if display and _pick_sample_matches(display, sample):
            ref = element.get("ref") or element.get("target")
            if ref:
                return str(ref)
    return None


def reconcile_picks_with_snapshot(
    picks: list[dict[str, Any]],
    snapshot: BrowserSnapshot,
) -> tuple[list[dict[str, Any]], int]:
    """Return picks with ``ref`` updated when the snapshot maps the same text to a new @eN."""
    realigned = 0
    out: list[dict[str, Any]] = []
    for pick in picks:
        updated = dict(pick)
        old_ref = str(updated.get("ref") or "").strip()
        text = str(updated.get("text") or "").strip()
        frame_raw = updated.get("frame_index")
        frame = frame_raw if isinstance(frame_raw, int) and frame_raw >= 0 else None
        new_ref = ref_for_pick_in_snapshot(snapshot, text=text, frame_index=frame)
        if new_ref and new_ref != old_ref:
            updated["ref"] = new_ref
            realigned += 1
        out.append(updated)
    return out, realigned
