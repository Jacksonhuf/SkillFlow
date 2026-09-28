from __future__ import annotations

from typing import Any

from browser_skill.models import RunState


def accepts_test_run_evidence(summary: dict[str, Any], *, expected_template: str) -> bool:
    """Return True when summary.json proves the exact template version passed Test Run."""
    if summary.get("template") != expected_template:
        return False
    state = summary.get("state")
    if state == RunState.COMPLETED.value:
        return True
    if state == RunState.PARTIAL.value:
        validation = summary.get("validation") or {}
        return bool(validation.get("ok"))
    return False
