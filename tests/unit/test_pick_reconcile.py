from __future__ import annotations

from browser_skill.models import BrowserSnapshot
from browser_skill.runtime.pick_reconcile import reconcile_picks_with_snapshot


def test_reconcile_updates_ref_when_snapshot_text_matches() -> None:
    picks = [{"ref": "@e9", "text": "ACME Corp", "frame_index": 0}]
    snapshot = BrowserSnapshot(
        elements=[{"ref": "@e12", "text": "ACME Corp", "frame_index": 0}],
    )
    updated, count = reconcile_picks_with_snapshot(picks, snapshot)
    assert count == 1
    assert updated[0]["ref"] == "@e12"


def test_reconcile_keeps_ref_when_already_aligned() -> None:
    picks = [{"ref": "@e9", "text": "ACME", "frame_index": 0}]
    snapshot = BrowserSnapshot(elements=[{"ref": "@e9", "text": "ACME", "frame_index": 0}])
    updated, count = reconcile_picks_with_snapshot(picks, snapshot)
    assert count == 0
    assert updated[0]["ref"] == "@e9"
