"""Per-item helpers for detail_batch runs (one detail page per driver value)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from browser_skill.acquire.label_value import find_label_value, parse_label_values
from browser_skill.models import (
    AcquisitionSource,
    BatchItemState,
    BatchItemStatus,
    BatchProgress,
    BrowserSnapshot,
    BrowserTemplate,
    DownloadedFile,
    DownloadStatus,
    FieldSpec,
    LearnedMapping,
    NetworkExchange,
)
from browser_skill.runtime.detail import DetailCollector
from browser_skill.runtime.url_batch import BatchItem


@dataclass(slots=True)
class ItemOutcome:
    """Result of visiting one detail page; only kept records/files reach the run output."""

    status: BatchItemStatus
    records: list[dict[str, Any]] = field(default_factory=list)
    files: list[DownloadedFile] = field(default_factory=list)
    reason: str | None = None
    error: dict[str, Any] | None = None


def build_progress(template: BrowserTemplate, items: list[BatchItem]) -> BatchProgress:
    driver = template.run.driver_variable
    assert driver is not None
    return BatchProgress(
        driver_variable=driver,
        template_id=template.template_id,
        items=[BatchItemState(index=item.index, value=item.value, url=item.url) for item in items],
    )


def previously_completed_values(runs_root: Path, template_id: str) -> dict[str, str]:
    """Map driver value → run_id for items that finished ``ok`` in earlier runs of a template.

    Reads ``runs/*/batch.json``; the newest run wins when a value appears more than once.
    Malformed or foreign files are ignored so a broken run can never block a new one.
    """
    completed: dict[str, str] = {}
    if not runs_root.is_dir():
        return completed
    for batch_file in sorted(runs_root.glob("run_*/batch.json")):
        try:
            payload = json.loads(batch_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict) or payload.get("template_id") != template_id:
            continue
        for item in payload.get("items") or []:
            if isinstance(item, dict) and item.get("status") == BatchItemStatus.OK.value:
                completed[str(item.get("value"))] = batch_file.parent.name
    return completed


def apply_incremental_skip(batch: BatchProgress, completed: dict[str, str]) -> int:
    """Mark pending items whose value already completed earlier as ``skipped``."""
    skipped = 0
    for item in batch.items:
        run_id = completed.get(item.value)
        if item.status == BatchItemStatus.PENDING and run_id:
            item.status = BatchItemStatus.SKIPPED
            item.reason = f"done_in:{run_id}"
            skipped += 1
    return skipped


def endpoint_matches(hint: str, path: str) -> bool:
    """``/api/orders/{order_no}`` matches ``/api/orders/ORD-1``; plain hints must be equal."""
    hint_parts = hint.strip("/").split("/")
    path_parts = path.strip("/").split("/")
    if len(hint_parts) != len(path_parts):
        return False
    return all(
        "{" in expected or expected == actual
        for expected, actual in zip(hint_parts, path_parts, strict=True)
    )


def resolve_scalar(body: Any, json_path: str) -> Any:
    """Resolve ``$.a.b`` on a JSON body to a scalar; scalar lists are joined with ``, ``."""
    if not json_path.startswith("$"):
        return None
    node: Any = body
    for segment in [part for part in json_path[1:].split(".") if part]:
        if isinstance(node, dict) and segment in node:
            node = node[segment]
        else:
            return None
    if isinstance(node, list):
        if node and all(not isinstance(item, (dict, list)) for item in node):
            return ", ".join(str(item) for item in node)
        return None
    if isinstance(node, dict):
        return None
    return node


def _network_value(exchanges: Sequence[NetworkExchange], mapping: LearnedMapping) -> Any:
    if not mapping.endpoint_hint or not mapping.json_path:
        return None
    for exchange in exchanges:
        if exchange.body is None or exchange.status >= 400:
            continue
        if not endpoint_matches(mapping.endpoint_hint, urlsplit(exchange.url).path or "/"):
            continue
        value = resolve_scalar(exchange.body, mapping.json_path)
        if value not in (None, ""):
            return value
    return None


def page_field_values(
    template: BrowserTemplate,
    fields: list[FieldSpec],
    snapshot: BrowserSnapshot,
    exchanges: Sequence[NetworkExchange] = (),
) -> dict[str, Any]:
    """Acquisition ladder for one detail page: structured elements → network JSON → text pairs."""
    values = DetailCollector._extract_fields(fields, snapshot)
    missing = [item for item in fields if values.get(item.key) in (None, "")]
    if not missing:
        return values
    pairs = parse_label_values(snapshot.text)
    for item in missing:
        mapping = template.learned.field_mappings.get(item.key)
        if mapping is not None and mapping.preferred_source == AcquisitionSource.NETWORK:
            found = _network_value(exchanges, mapping)
            if found is not None:
                values[item.key] = found
                continue
        hints = [item.name, *item.semantic, *item.aliases, *(mapping.hints if mapping else [])]
        text_value = find_label_value(pairs, hints)
        if text_value is not None:
            values[item.key] = text_value
    return values


def extract_item_records(
    template: BrowserTemplate,
    driver: str,
    value: str,
    snapshot: BrowserSnapshot,
    exchanges: Sequence[NetworkExchange] = (),
) -> list[dict[str, Any]]:
    """Turn one detail page into records.

    A detail page is one record by default. With ``run.capture_tables`` every table row on the
    page becomes a record; label/value fields found outside the table are copied onto each row.
    The driver value is always stamped on the record so record keys and attachment names can
    reference it even when the page does not display it.
    """
    fields = list(template.target.fields)
    if template.run.capture_tables and snapshot.records:
        without_rows = snapshot.model_copy(update={"records": []})
        page_level = page_field_values(template, fields, without_rows, exchanges)
        keys = {item.key for item in fields}
        records = []
        for row in snapshot.records:
            merged = {**page_level, **{key: row[key] for key in row if key in keys}}
            merged.setdefault(driver, value)
            records.append(merged)
        return records
    record = page_field_values(template, fields, snapshot, exchanges)
    record.setdefault(driver, value)
    return [record]


def classify_item(
    template: BrowserTemplate,
    records: list[dict[str, Any]],
    files: list[DownloadedFile],
) -> ItemOutcome:
    """Decide an item's status using the same required/optional semantics as the validator.

    Records lacking a required field, and items whose required attachment did not download,
    are excluded from the run output and reported as ``failed`` so the caller can retry only
    those driver values. Missing optional data downgrades the item to ``partial``.
    """
    required = [item.key for item in template.target.fields if item.required]
    kept: list[dict[str, Any]] = []
    missing: set[str] = set()
    for record in records:
        gaps = [key for key in required if record.get(key) in {None, ""}]
        if gaps:
            missing.update(gaps)
            continue
        kept.append(record)
    if not kept:
        reason = "required_field_missing:" + ",".join(sorted(missing)) if missing else "no_record"
        return ItemOutcome(status=BatchItemStatus.FAILED, reason=reason)

    required_attachments = {item.key for item in template.target.attachments if item.required}
    failed_required = sorted(
        {
            item.attachment_key
            for item in files
            if item.attachment_key in required_attachments and item.status != DownloadStatus.OK
        }
    )
    if failed_required:
        return ItemOutcome(
            status=BatchItemStatus.FAILED,
            reason="required_attachment_missing:" + ",".join(failed_required),
        )
    optional_failed = any(item.status != DownloadStatus.OK for item in files)
    dropped = len(records) - len(kept)
    if optional_failed or dropped:
        reason = "attachment_missing" if optional_failed else f"rows_dropped:{dropped}"
        return ItemOutcome(status=BatchItemStatus.PARTIAL, records=kept, files=files, reason=reason)
    return ItemOutcome(status=BatchItemStatus.OK, records=kept, files=files)
