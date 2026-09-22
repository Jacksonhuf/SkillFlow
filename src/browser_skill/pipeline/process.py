from __future__ import annotations

from typing import Any

from browser_skill.models import BrowserTemplate, ProcessingSpec


def apply_processing(
    template: BrowserTemplate,
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    spec = template.processing
    if not spec.enabled or not spec.steps:
        return records
    result = [dict(record) for record in records]
    for step in spec.steps:
        if step.action == "rename_field":
            source = str(step.params.get("from", ""))
            target = str(step.params.get("to", ""))
            if not source or not target:
                continue
            for record in result:
                if source in record and target not in record:
                    record[target] = record.pop(source)
        elif step.action == "dedupe_records":
            key_fields = step.params.get("keys") or template.target.record_key
            if not isinstance(key_fields, list):
                continue
            seen: set[str] = set()
            deduped: list[dict[str, Any]] = []
            for record in result:
                fingerprint = "|".join(str(record.get(key, "")) for key in key_fields)
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
                deduped.append(record)
            result = deduped
    return result
