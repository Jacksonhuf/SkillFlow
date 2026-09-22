from __future__ import annotations

from typing import Any

from browser_skill.models import BrowserTemplate, ProcessingStepSpec


def _coerce(value: Any, target_type: str) -> Any:
    if value is None or value == "":
        return value
    text = str(value).strip()
    try:
        if target_type == "integer":
            return int(float(text.replace(",", "")))
        if target_type == "number":
            return float(text.replace(",", ""))
        if target_type == "boolean":
            return text.casefold() in {"1", "true", "yes", "y", "是", "真"}
        if target_type == "string":
            return text
    except ValueError:
        return value
    return value


def _rename(records: list[dict[str, Any]], step: ProcessingStepSpec) -> None:
    source = str(step.params.get("from", ""))
    target = str(step.params.get("to", ""))
    if not source or not target:
        return
    for record in records:
        if source in record and target not in record:
            record[target] = record.pop(source)


def _coerce_type(records: list[dict[str, Any]], step: ProcessingStepSpec) -> None:
    field = str(step.params.get("field", ""))
    target_type = str(step.params.get("type", "string"))
    if not field:
        return
    for record in records:
        if field in record:
            record[field] = _coerce(record[field], target_type)


def _default_value(records: list[dict[str, Any]], step: ProcessingStepSpec) -> None:
    field = str(step.params.get("field", ""))
    if not field or "value" not in step.params:
        return
    default = step.params["value"]
    for record in records:
        if record.get(field) in (None, ""):
            record[field] = default


def _dedupe(
    records: list[dict[str, Any]], step: ProcessingStepSpec, template: BrowserTemplate
) -> list[dict[str, Any]]:
    key_fields = step.params.get("keys") or template.target.record_key
    if not isinstance(key_fields, list) or not key_fields:
        return records
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for record in records:
        fingerprint = "|".join(str(record.get(key, "")) for key in key_fields)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        deduped.append(record)
    return deduped


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
            _rename(result, step)
        elif step.action == "coerce_type":
            _coerce_type(result, step)
        elif step.action == "default_value":
            _default_value(result, step)
        elif step.action == "dedupe_records":
            result = _dedupe(result, step, template)
    return result
