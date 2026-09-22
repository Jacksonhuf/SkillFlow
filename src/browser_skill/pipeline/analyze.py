from __future__ import annotations

from typing import Any

from browser_skill.models import BrowserTemplate


def apply_analysis(
    template: BrowserTemplate,
    records: list[dict[str, Any]],
    *,
    validation_ok: bool,
) -> dict[str, Any]:
    spec = template.analysis
    if not spec.enabled:
        return {"skipped": True, "reason": "analysis disabled"}
    return {
        "skipped": False,
        "placeholder": True,
        "record_count": len(records),
        "validation_ok": validation_ok,
        "prompt_template": spec.prompt_template,
    }
