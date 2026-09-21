from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from browser_skill.browser.base import BrowserAdapter
from browser_skill.models import (
    AttachmentSpec,
    BrowserSnapshot,
    BrowserTemplate,
    DownloadedFile,
    DownloadStatus,
)
from browser_skill.outputs.paths import safe_filename, safe_relative_subdir
from browser_skill.outputs.writer import file_sha256
from browser_skill.runtime.locator import LocatorService


class AttachmentDownloader:
    def __init__(
        self,
        *,
        completion_polls: int = 6,
        locator: LocatorService | None = None,
    ) -> None:
        self.completion_polls = max(1, completion_polls)
        self.locator = locator or LocatorService()

    async def collect(
        self,
        adapter: BrowserAdapter,
        template: BrowserTemplate,
        snapshot: BrowserSnapshot,
        records: list[dict[str, Any]],
        workspace: Path,
        attachments: list[AttachmentSpec] | None = None,
    ) -> list[DownloadedFile]:
        downloaded: list[DownloadedFile] = []
        for spec in attachments if attachments is not None else template.target.attachments:
            expected: list[tuple[str | None, dict[str, Any] | None]]
            if spec.per_record:
                expected = [(self._record_key(template, record), record) for record in records]
            else:
                expected = [(None, None)]
            if spec.max_count is not None:
                expected = expected[: spec.max_count]
            for record_key, record in expected:
                target = await self._resolve_download_target(
                    adapter,
                    snapshot,
                    spec,
                    record_key,
                )
                if target is None:
                    downloaded.append(
                        DownloadedFile(
                            record_key=record_key,
                            attachment_key=spec.key,
                            relative_path="",
                            status=DownloadStatus.MISSING,
                        )
                    )
                    continue
                original = safe_filename(f"{spec.key}.bin")
                element = self._find_element(snapshot, spec.semantic, record_key)
                if element and element.get("filename"):
                    original = safe_filename(str(element["filename"]))
                values = {**(record or {}), "original_name": original}
                name = spec.filename_pattern
                for key, value in values.items():
                    name = name.replace("{" + str(key) + "}", str(value))
                name = safe_filename(name, fallback=original)
                relative = Path(safe_relative_subdir(spec.destination_subdir)) / name
                path = workspace / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                result = await adapter.download(target, path)
                complete = await self._wait_for_file(adapter, path) if result.ok else False
                status = DownloadStatus.OK if complete else DownloadStatus.FAILED
                if (
                    status == DownloadStatus.OK
                    and spec.file_types
                    and path.suffix.lower().lstrip(".") not in spec.file_types
                ):
                    status = DownloadStatus.REJECTED
                    path.unlink(missing_ok=True)
                downloaded.append(
                    DownloadedFile(
                        record_key=record_key,
                        attachment_key=spec.key,
                        relative_path=relative.as_posix() if path.exists() else "",
                        original_name=original,
                        size=path.stat().st_size if path.exists() else 0,
                        sha256=file_sha256(path) if status == DownloadStatus.OK else None,
                        status=status,
                    )
                )
        return downloaded

    async def _resolve_download_target(
        self,
        adapter: BrowserAdapter,
        snapshot: BrowserSnapshot,
        spec: AttachmentSpec,
        record_key: str | None,
    ) -> str | None:
        element = self._find_element(snapshot, spec.semantic, record_key)
        if element is not None:
            value = element.get("target") or element.get("ref") or element.get("text")
            return str(value) if value else None
        located = await self.locator.locate(
            adapter,
            snapshot,
            list(spec.semantic),
            record_key=record_key,
            required=False,
        )
        return located.target if located else None

    async def _wait_for_file(self, adapter: BrowserAdapter, path: Path) -> bool:
        for _ in range(self.completion_polls):
            if path.is_file() and path.stat().st_size > 0:
                return True
            await adapter.list_downloads()
            await asyncio.sleep(0.15)
        return path.is_file() and path.stat().st_size > 0

    @staticmethod
    def _find_element(
        snapshot: BrowserSnapshot, semantics: list[str], record_key: str | None
    ) -> dict[str, Any] | None:
        for element in snapshot.elements:
            text = " ".join(str(value) for value in element.values()).casefold()
            if record_key and element.get("record_key") not in {None, record_key}:
                continue
            if any(semantic.casefold() in text for semantic in semantics):
                return element
        return None

    @staticmethod
    def _record_key(template: BrowserTemplate, record: dict[str, Any]) -> str | None:
        values = [str(record.get(key, "")) for key in template.target.record_key]
        return "|".join(values) if values and all(values) else None
