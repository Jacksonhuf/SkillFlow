from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path
from typing import Any

from browser_skill.browser.base import BrowserAdapter
from browser_skill.errors import ErrorCode, SkillError
from browser_skill.models import (
    AttachmentSpec,
    BrowserSnapshot,
    BrowserTemplate,
    DownloadedFile,
    DownloadStatus,
    FieldSpec,
    SourcePage,
)
from browser_skill.runtime.downloader import AttachmentDownloader


@dataclass(slots=True)
class DetailCollectionResult:
    records: list[dict[str, Any]]
    files: list[DownloadedFile] = dc_field(default_factory=list)
    snapshot: BrowserSnapshot = dc_field(default_factory=BrowserSnapshot)
    failed_record_keys: list[str] = dc_field(default_factory=list)


class DetailCollector:
    """Visit list records one-by-one, merge detail fields, download files, and return to list."""

    def __init__(self, downloader: AttachmentDownloader | None = None) -> None:
        self.downloader = downloader or AttachmentDownloader()

    async def collect(
        self,
        adapter: BrowserAdapter,
        template: BrowserTemplate,
        list_snapshot: BrowserSnapshot,
        records: list[dict[str, Any]],
        workspace: Path,
    ) -> DetailCollectionResult:
        detail_fields = [
            field for field in template.target.fields if field.source == SourcePage.DETAIL
        ]
        detail_attachments = [
            item for item in template.target.attachments if item.source == SourcePage.DETAIL
        ]
        if not detail_fields and not detail_attachments:
            return DetailCollectionResult(records=records, snapshot=list_snapshot)
        if not template.target.record_key:
            raise SkillError(
                ErrorCode.TEMPLATE_INVALID,
                "Detail processing requires target.record_key",
                stage="detail",
            )
        current = list_snapshot
        merged_records: list[dict[str, Any]] = []
        files: list[DownloadedFile] = []
        failed: list[str] = []
        for record in records:
            record_key = self._record_key(template, record)
            target = self._detail_target(template, current, record_key)
            if target is None:
                found = await adapter.find(
                    f"{record_key} {template.workflow.detail_link_semantic[0]}"
                )
                target = self._target(found.data) if found.ok else None
            if target is None:
                merged_records.append(dict(record))
                failed.append(record_key)
                files.extend(self._missing_files(detail_attachments, record_key))
                continue
            clicked = await adapter.click(target, observe=True)
            if not clicked.ok:
                merged_records.append(dict(record))
                failed.append(record_key)
                files.extend(self._missing_files(detail_attachments, record_key))
                continue
            detail = await adapter.snapshot(interactive=True, diff=True)
            if not self._detail_matches_record(template, detail, record):
                await self._return_to_list(adapter, template)
                current = await adapter.snapshot(interactive=True)
                merged_records.append(dict(record))
                failed.append(record_key)
                files.extend(self._missing_files(detail_attachments, record_key))
                continue
            enriched = {**record, **self._extract_fields(detail_fields, detail)}
            merged_records.append(enriched)
            if detail_attachments:
                files.extend(
                    await self.downloader.collect(
                        adapter,
                        template,
                        detail,
                        [enriched],
                        workspace,
                        attachments=detail_attachments,
                    )
                )
            await self._return_to_list(adapter, template)
            current = await adapter.snapshot(interactive=True)
        return DetailCollectionResult(
            records=merged_records,
            files=files,
            snapshot=current,
            failed_record_keys=failed,
        )

    @staticmethod
    def _record_key(template: BrowserTemplate, record: dict[str, Any]) -> str:
        values = [str(record.get(key, "")) for key in template.target.record_key]
        return "|".join(values)

    def _detail_target(
        self, template: BrowserTemplate, snapshot: BrowserSnapshot, record_key: str
    ) -> str | None:
        for element in snapshot.elements:
            if str(element.get("record_key", "")) != record_key:
                continue
            safe_text = " ".join(
                str(element.get(key, "")) for key in ("text", "name", "label", "aria_label")
            ).casefold()
            if any(item.casefold() in safe_text for item in template.workflow.detail_link_semantic):
                return self._target(element)
        return None

    @staticmethod
    def _target(data: Any) -> str | None:
        if isinstance(data, dict):
            value = data.get("target") or data.get("ref")
            return str(value) if value else None
        return str(data) if data else None

    @staticmethod
    def _extract_fields(fields: list[FieldSpec], snapshot: BrowserSnapshot) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for record in snapshot.records[:1]:
            for field in fields:
                if field.key in record:
                    values[field.key] = record[field.key]
        for field in fields:
            if field.key in values:
                continue
            for element in snapshot.elements:
                label = " ".join(
                    str(element.get(key, "")) for key in ("field_key", "label", "name", "text")
                ).casefold()
                if (
                    element.get("field_key") == field.key
                    or any(semantic.casefold() in label for semantic in field.semantic)
                ) and "value" in element:
                    values[field.key] = element["value"]
                    break
        return values

    @staticmethod
    def _detail_matches_record(
        template: BrowserTemplate,
        snapshot: BrowserSnapshot,
        record: dict[str, Any],
    ) -> bool:
        expected = [str(record.get(key, "")) for key in template.target.record_key]
        haystack = (
            snapshot.text.casefold()
            + " "
            + " ".join(
                str(value).casefold() for item in snapshot.records for value in item.values()
            )
        )
        return all(value and value.casefold() in haystack for value in expected)

    async def _return_to_list(self, adapter: BrowserAdapter, template: BrowserTemplate) -> None:
        if template.workflow.return_to_list_action == "semantic":
            for semantic in template.workflow.return_to_list_semantic:
                found = await adapter.find(semantic)
                if found.ok:
                    clicked = await adapter.click(self._target(found.data) or semantic)
                    if clicked.ok:
                        return
        result = await adapter.do_action("page", "back")
        if not result.ok:
            raise SkillError(
                ErrorCode.NAVIGATION_FAILED,
                "Unable to return from detail page to list",
                stage="detail",
                retryable=True,
            )

    @staticmethod
    def _missing_files(attachments: list[AttachmentSpec], record_key: str) -> list[DownloadedFile]:
        return [
            DownloadedFile(
                record_key=record_key,
                attachment_key=item.key,
                relative_path="",
                status=DownloadStatus.MISSING,
            )
            for item in attachments
        ]
