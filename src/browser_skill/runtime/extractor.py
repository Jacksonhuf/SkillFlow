from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

from browser_skill.browser.base import BrowserAdapter
from browser_skill.models import BrowserSnapshot, BrowserTemplate, PaginationStrategy
from browser_skill.runtime.locator import LocatorService
from browser_skill.runtime.policy import ActionPolicy
from browser_skill.runtime.table_parser import SnapshotTableParser

RecordSource = Callable[[BrowserSnapshot], Awaitable[list[dict[str, Any]] | None]]
"""Optional per-page record provider; ``None`` means "use DOM/table parsing for this page"."""


class RecordExtractor:
    """Collect structured records from normalized snapshots with bounded pagination."""

    def __init__(
        self,
        table_parser: SnapshotTableParser | None = None,
        locator: LocatorService | None = None,
        policy: ActionPolicy | None = None,
    ) -> None:
        self.table_parser = table_parser or SnapshotTableParser()
        self.locator = locator or LocatorService()
        self.policy = policy or ActionPolicy()

    async def collect(
        self,
        adapter: BrowserAdapter,
        template: BrowserTemplate,
        first_snapshot: BrowserSnapshot,
        *,
        record_source: RecordSource | None = None,
    ) -> tuple[list[dict[str, Any]], bool, BrowserSnapshot]:
        pagination = template.target.pagination
        records: list[dict[str, Any]] = []
        seen_records: set[str] = set()
        seen_pages: set[str] = set()
        current = first_snapshot
        idle_rounds = 0
        for _ in range(pagination.max_pages):
            fingerprint = self._page_fingerprint(current)
            seen_pages.add(fingerprint)
            source_records = await self._page_records(template, current, record_source)
            for record in self._normalized(template, source_records):
                key = self._record_fingerprint(template, record)
                if key not in seen_records:
                    seen_records.add(key)
                    records.append(record)
            if pagination.strategy == PaginationStrategy.NONE:
                return records, True, current
            if pagination.strategy in {
                PaginationStrategy.NEXT_BUTTON,
                PaginationStrategy.LOAD_MORE,
            }:
                located = await self.locator.locate(
                    adapter,
                    current,
                    pagination.semantic,
                    required=False,
                )
                if located is None:
                    return records, True, current
                clicked = await adapter.click(located.target)
                if not clicked.ok:
                    return records, False, current
            elif pagination.strategy == PaginationStrategy.INFINITE_SCROLL:
                action = await adapter.do_action("page", "scroll_down")
                if not action.ok:
                    return records, True, current
            else:
                action = await adapter.do_action("pagination", "next_page")
                if not action.ok:
                    return records, True, current
            next_snapshot = await adapter.snapshot(interactive=True, diff=True)
            if next_snapshot.url:
                self.policy.require_url_allowed(next_snapshot.url, template)
            next_fingerprint = self._page_fingerprint(next_snapshot)
            if next_fingerprint == fingerprint:
                if pagination.strategy in {
                    PaginationStrategy.LOAD_MORE,
                    PaginationStrategy.INFINITE_SCROLL,
                }:
                    idle_rounds += 1
                    current = next_snapshot
                    if idle_rounds >= pagination.max_idle_rounds:
                        return records, True, current
                    continue
                current = next_snapshot
                return records, False, current
            idle_rounds = 0
            if next_fingerprint in seen_pages:
                return records, False, next_snapshot
            current = next_snapshot
        return records, False, current

    async def _page_records(
        self,
        template: BrowserTemplate,
        snapshot: BrowserSnapshot,
        record_source: RecordSource | None,
    ) -> list[dict[str, Any]]:
        if record_source is not None:
            provided = await record_source(snapshot)
            if provided is not None:
                return provided
        return snapshot.records or self.table_parser.parse(template, snapshot)

    @staticmethod
    def _normalized(
        template: BrowserTemplate, records: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        keys = {field.key for field in template.target.fields}
        return [{key: value for key, value in record.items() if key in keys} for record in records]

    @staticmethod
    def _record_fingerprint(template: BrowserTemplate, record: dict[str, Any]) -> str:
        if template.target.record_key:
            values = [str(record.get(key, "")) for key in template.target.record_key]
            if all(values):
                return "|".join(values)
        return hashlib.sha256(
            json.dumps(record, ensure_ascii=False, sort_keys=True, default=str).encode()
        ).hexdigest()

    @staticmethod
    def _page_fingerprint(snapshot: BrowserSnapshot) -> str:
        payload: Any = snapshot.records or [
            {
                key: element.get(key)
                for key in ("role", "row_index", "column_index", "text", "name", "value")
                if key in element
            }
            for element in snapshot.elements
        ]
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
        ).hexdigest()
