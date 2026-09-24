"""Per-item helpers for detail_batch runs (one detail page per driver value)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from browser_skill.models import (
    BatchItemState,
    BatchItemStatus,
    BatchProgress,
    BrowserSnapshot,
    BrowserTemplate,
    DownloadedFile,
    DownloadStatus,
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
        items=[BatchItemState(index=item.index, value=item.value, url=item.url) for item in items],
    )


def extract_item_records(
    template: BrowserTemplate,
    driver: str,
    value: str,
    snapshot: BrowserSnapshot,
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
        page_level = DetailCollector._extract_fields(fields, without_rows)
        keys = {item.key for item in fields}
        records = []
        for row in snapshot.records:
            merged = {**page_level, **{key: row[key] for key in row if key in keys}}
            merged.setdefault(driver, value)
            records.append(merged)
        return records
    record = DetailCollector._extract_fields(fields, snapshot)
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
