from __future__ import annotations

from typing import Any

from browser_skill.models import BrowserTemplate, RunMode


def record_key_for(
    template: BrowserTemplate,
    record: dict[str, Any],
    *,
    fallback: str | None = None,
) -> str | None:
    """Stable key for a record used in validation, attachments, and deduplication."""
    keys = template.target.record_key
    if not keys:
        return fallback
    filled = [str(record.get(key, "")).strip() for key in keys]
    if all(filled):
        return "|".join(filled)
    driver = template.run.driver_variable
    if template.run.mode != RunMode.DETAIL_BATCH or not driver:
        return fallback
    driver_val = str(record.get(driver, "")).strip()
    if not driver_val:
        return fallback
    if driver in keys:
        idx = keys.index(driver)
        if not filled[idx]:
            filled[idx] = driver_val
        if all(filled):
            return "|".join(filled)
        return fallback
    partial = [value for value in filled if value]
    return "|".join([*partial, driver_val]) if partial else driver_val
