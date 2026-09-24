from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

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
        # Per-run cache: absolute source URL → first saved file, so a document shared by many
        # records (e.g. a common contract template) is fetched once and copied afterwards.
        self._source_cache: dict[str, Path] = {}
        self._source_cache_workspace: Path | None = None

    def _cache_for(self, workspace: Path) -> dict[str, Path]:
        if self._source_cache_workspace != workspace:
            self._source_cache = {}
            self._source_cache_workspace = workspace
        return self._source_cache

    async def collect(
        self,
        adapter: BrowserAdapter,
        template: BrowserTemplate,
        snapshot: BrowserSnapshot,
        records: list[dict[str, Any]],
        workspace: Path,
        attachments: list[AttachmentSpec] | None = None,
    ) -> list[DownloadedFile]:
        attachment_timeout_ms = template.run.attachment_timeout_ms
        downloaded: list[DownloadedFile] = []
        for spec in attachments if attachments is not None else template.target.attachments:
            expected: list[tuple[str | None, dict[str, Any] | None]]
            if spec.per_record:
                expected = [(self._record_key(template, record), record) for record in records]
            else:
                expected = [(None, None)]
            if spec.max_count is not None:
                expected = expected[: spec.max_count]
            used_paths: set[Path] = set()
            for record_key, record in expected:
                targets = await self._resolve_download_targets(
                    adapter,
                    snapshot,
                    spec,
                    record_key,
                )
                if not targets:
                    downloaded.append(
                        DownloadedFile(
                            record_key=record_key,
                            attachment_key=spec.key,
                            relative_path="",
                            status=DownloadStatus.MISSING,
                        )
                    )
                    continue
                for target, element in targets:
                    downloaded.append(
                        await self._download_one(
                            adapter,
                            spec,
                            record_key,
                            record,
                            target,
                            element,
                            workspace,
                            used_paths,
                            source=self._source_url(snapshot, element),
                            attachment_timeout_ms=attachment_timeout_ms,
                        )
                    )
        return downloaded

    async def _download_one(
        self,
        adapter: BrowserAdapter,
        spec: AttachmentSpec,
        record_key: str | None,
        record: dict[str, Any] | None,
        target: str,
        element: dict[str, Any] | None,
        workspace: Path,
        used_paths: set[Path],
        *,
        source: str | None = None,
        attachment_timeout_ms: int = 45_000,
    ) -> DownloadedFile:
        original = safe_filename(
            self._original_name(element) or f"{spec.key}.bin", fallback=f"{spec.key}.bin"
        )
        values = {**(record or {}), "original_name": original}
        name = spec.filename_pattern
        for key, value in values.items():
            name = name.replace("{" + str(key) + "}", str(value))
        name = safe_filename(name, fallback=original)
        relative = self._unique_relative(
            Path(safe_relative_subdir(spec.destination_subdir)) / name, used_paths
        )
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        cache = self._cache_for(workspace)
        cached = cache.get(source) if source else None
        copied_from: str | None = None
        if cached is not None and cached.is_file() and cached != path:
            shutil.copy2(cached, path)
            copied_from = cached.relative_to(workspace).as_posix()
            complete = True
        else:
            result = await adapter.download(
                target, path, timeout_ms=attachment_timeout_ms
            )
            complete = await self._wait_for_file(adapter, path) if result.ok else False
        status = DownloadStatus.OK if complete else DownloadStatus.FAILED
        if (
            status == DownloadStatus.OK
            and spec.file_types
            and path.suffix.lower().lstrip(".") not in spec.file_types
        ):
            status = DownloadStatus.REJECTED
            path.unlink(missing_ok=True)
        if status == DownloadStatus.OK and source and copied_from is None:
            cache[source] = path
        return DownloadedFile(
            record_key=record_key,
            attachment_key=spec.key,
            relative_path=relative.as_posix() if path.exists() else "",
            original_name=original,
            size=path.stat().st_size if path.exists() else 0,
            sha256=file_sha256(path) if status == DownloadStatus.OK else None,
            status=status,
            copied_from=copied_from,
        )

    @staticmethod
    def _source_url(snapshot: BrowserSnapshot, element: dict[str, Any] | None) -> str | None:
        """Absolute document URL of a link element, or None when it cannot identify the bytes."""
        if not element:
            return None
        href = str(element.get("href") or "").strip()
        if not href or href.startswith(("javascript:", "#", "data:", "blob:")):
            return None
        absolute = urljoin(snapshot.url or "", href)
        return absolute if absolute.startswith(("http://", "https://")) else None

    @staticmethod
    def _unique_relative(relative: Path, used_paths: set[Path]) -> Path:
        """Avoid overwriting when several files of one attachment render the same name."""
        candidate = relative
        counter = 2
        while candidate in used_paths:
            candidate = relative.with_name(f"{relative.stem}_{counter}{relative.suffix}")
            counter += 1
        used_paths.add(candidate)
        return candidate

    async def _resolve_download_targets(
        self,
        adapter: BrowserAdapter,
        snapshot: BrowserSnapshot,
        spec: AttachmentSpec,
        record_key: str | None,
    ) -> list[tuple[str, dict[str, Any] | None]]:
        """Return ``(target, element)`` pairs; several when the spec allows multiple files."""
        elements = self._find_elements(snapshot, spec.semantic, record_key)
        if not spec.multiple:
            elements = elements[:1]
        elif spec.max_count is not None:
            elements = elements[: spec.max_count]
        targets: list[tuple[str, dict[str, Any] | None]] = []
        for element in elements:
            value = element.get("target") or element.get("ref") or element.get("text")
            if value:
                targets.append((str(value), element))
        if targets:
            return targets
        located = await self.locator.locate(
            adapter,
            snapshot,
            list(spec.semantic),
            record_key=record_key,
            required=False,
        )
        return [(located.target, None)] if located else []

    async def _wait_for_file(self, adapter: BrowserAdapter, path: Path) -> bool:
        for _ in range(self.completion_polls):
            if path.is_file() and path.stat().st_size > 0:
                return True
            await adapter.list_downloads()
            await asyncio.sleep(0.15)
        return path.is_file() and path.stat().st_size > 0

    @staticmethod
    def _original_name(element: dict[str, Any] | None) -> str | None:
        """Best-effort original filename: explicit ``filename``, else an href/text with a suffix."""
        if not element:
            return None
        if element.get("filename"):
            return str(element["filename"])
        for key in ("text", "name", "title", "href"):
            raw = str(element.get(key) or "").strip()
            if not raw:
                continue
            tail = raw.split("?", 1)[0].split("#", 1)[0].rstrip("/").rsplit("/", 1)[-1]
            if re.search(r"\.[A-Za-z0-9]{2,5}$", tail):
                return tail
        return None

    @staticmethod
    def _find_elements(
        snapshot: BrowserSnapshot, semantics: list[str], record_key: str | None
    ) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        for element in snapshot.elements:
            text = " ".join(str(value) for value in element.values()).casefold()
            if record_key and element.get("record_key") not in {None, record_key}:
                continue
            if any(semantic.casefold() in text for semantic in semantics):
                matches.append(element)
        return matches

    @staticmethod
    def _record_key(template: BrowserTemplate, record: dict[str, Any]) -> str | None:
        values = [str(record.get(key, "")) for key in template.target.record_key]
        return "|".join(values) if values and all(values) else None
