from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path
from typing import Any

from browser_skill.acquire import attachments as attach
from browser_skill.browser.base import BrowserAdapter
from browser_skill.models import (
    AttachmentSpec,
    BrowserSnapshot,
    BrowserTemplate,
    DownloadedFile,
    DownloadStatus,
    NetworkExchange,
)
from browser_skill.outputs.paths import (
    attachment_basename,
    looks_like_url,
    safe_filename,
    safe_relative_subdir,
)
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
        exchanges: list[NetworkExchange] | None = None,
    ) -> list[DownloadedFile]:
        attachment_timeout_ms = template.run.attachment_timeout_ms
        captured = list(exchanges or [])
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
                files = await self._acquire_for_record(
                    adapter,
                    template,
                    spec,
                    snapshot,
                    captured,
                    record_key,
                    record,
                    workspace,
                    used_paths,
                    attachment_timeout_ms=attachment_timeout_ms,
                )
                downloaded.extend(files)
        return downloaded

    async def _acquire_for_record(
        self,
        adapter: BrowserAdapter,
        template: BrowserTemplate,
        spec: AttachmentSpec,
        snapshot: BrowserSnapshot,
        exchanges: list[NetworkExchange],
        record_key: str | None,
        record: dict[str, Any] | None,
        workspace: Path,
        used_paths: set[Path],
        *,
        attachment_timeout_ms: int,
    ) -> list[DownloadedFile]:
        terms = attach.attachment_semantic_terms(spec, template)
        mapping = template.learned.attachment_mappings.get(spec.key)
        targets = await self._resolve_download_targets(
            adapter, template, snapshot, spec, record_key, record, terms
        )
        if not targets and not exchanges and mapping is None:
            return [
                DownloadedFile(
                    record_key=record_key,
                    attachment_key=spec.key,
                    relative_path="",
                    status=DownloadStatus.MISSING,
                )
            ]

        attempts: list[tuple[str, dict[str, Any] | None]] = list(targets)
        if not attempts:
            attempts = [("", None)]

        results: list[DownloadedFile] = []
        for index, (target, element) in enumerate(attempts, start=1):
            if spec.multiple is False and results:
                break
            if spec.max_count is not None and len(results) >= spec.max_count:
                break
            item = await self._download_one(
                adapter,
                template,
                spec,
                snapshot,
                exchanges,
                record_key,
                record,
                target,
                element,
                workspace,
                used_paths,
                attachment_timeout_ms=attachment_timeout_ms,
                file_index=index,
                terms=terms,
                mapping=mapping,
            )
            results.append(item)
            if item.status == DownloadStatus.OK and not spec.multiple:
                break
        if not results:
            results.append(
                DownloadedFile(
                    record_key=record_key,
                    attachment_key=spec.key,
                    relative_path="",
                    status=DownloadStatus.MISSING,
                )
            )
        return results

    async def _download_one(
        self,
        adapter: BrowserAdapter,
        template: BrowserTemplate,
        spec: AttachmentSpec,
        snapshot: BrowserSnapshot,
        exchanges: list[NetworkExchange],
        record_key: str | None,
        record: dict[str, Any] | None,
        target: str,
        element: dict[str, Any] | None,
        workspace: Path,
        used_paths: set[Path],
        *,
        attachment_timeout_ms: int = 45_000,
        file_index: int = 1,
        terms: list[str],
        mapping: Any,
    ) -> DownloadedFile:
        original = attachment_basename(
            self._original_name(element),
            fallback=f"{spec.key}.bin",
            max_length=64,
        )
        ext = "bin"
        relative = self._build_relative(
            spec, record, original, ext=ext, index=file_index, used_paths=used_paths
        )
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)

        async def finalize(
            *,
            content_type: str = "",
            source_url: str | None = None,
            copied_from: str | None = None,
        ) -> DownloadedFile:
            nonlocal path, relative
            ext_final = attach.guess_extension(content_type, source_url or "", path)
            if "{ext}" in spec.filename_pattern and ext_final != ext:
                relative_final = self._build_relative(
                    spec, record, original, ext=ext_final, index=file_index, used_paths=used_paths
                )
                final_path = workspace / relative_final
                if path.exists() and final_path != path:
                    final_path.parent.mkdir(parents=True, exist_ok=True)
                    path.replace(final_path)
                    path = final_path
                    relative = relative_final
            status = (
                DownloadStatus.OK
                if path.is_file() and path.stat().st_size > 0
                else DownloadStatus.FAILED
            )
            if status == DownloadStatus.OK and spec.file_types:
                suffix = path.suffix.lower().lstrip(".")
                if suffix not in spec.file_types:
                    status = DownloadStatus.REJECTED
                    path.unlink(missing_ok=True)
            if (
                status == DownloadStatus.OK
                and spec.min_size_bytes is not None
                and path.stat().st_size < spec.min_size_bytes
            ):
                status = DownloadStatus.FAILED
            if (
                status == DownloadStatus.OK
                and spec.max_size_bytes is not None
                and path.stat().st_size > spec.max_size_bytes
            ):
                status = DownloadStatus.REJECTED
                path.unlink(missing_ok=True)
            cache = self._cache_for(workspace)
            if status == DownloadStatus.OK and source_url:
                cache.setdefault(source_url, path)
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

        # 1) Learned network JSON → file URL
        if mapping and exchanges:
            file_url = attach.network_json_file_url(exchanges, mapping, record)
            if file_url:
                ok, copied = await self._cached_or_fetch(
                    adapter,
                    template,
                    file_url,
                    path,
                    workspace,
                    attachment_timeout_ms,
                    page_url=snapshot.url or "",
                )
                if ok:
                    return await finalize(source_url=file_url, copied_from=copied)

        # 2) Captured binary response
        binary = attach.network_binary_match(exchanges, mapping, terms, template)
        if binary and attach.write_network_binary(binary, path):
            return await finalize(content_type=binary.content_type, source_url=binary.url)

        # 3) JSON bodies mentioning attachment-like URLs
        for exchange in exchanges:
            if exchange.body is None or exchange.status >= 400:
                continue
            for file_url in attach.scan_json_for_file_urls(exchange.body, terms, exchange.url):
                if not attach.is_fetchable_attachment_url(file_url, page_url=snapshot.url or ""):
                    continue
                ok, copied = await self._cached_or_fetch(
                    adapter,
                    template,
                    file_url,
                    path,
                    workspace,
                    attachment_timeout_ms,
                    page_url=snapshot.url or "",
                )
                if ok:
                    return await finalize(source_url=file_url, copied_from=copied)

        source = attach.stable_http_url(snapshot, element)
        if source:
            ok, copied = await self._cached_or_fetch(
                adapter,
                template,
                source,
                path,
                workspace,
                attachment_timeout_ms,
                page_url=snapshot.url or "",
            )
            if ok:
                return await finalize(source_url=source, copied_from=copied)

        if target:
            result = await adapter.download(target, path, timeout_ms=attachment_timeout_ms)
            complete = await self._wait_for_file(adapter, path) if result.ok else False
            if complete:
                return await finalize(source_url=source)

        if not target:
            binary = attach.network_binary_match(exchanges, None, terms, template)
            if binary and attach.write_network_binary(binary, path):
                return await finalize(content_type=binary.content_type, source_url=binary.url)

        return await finalize()

    async def _cached_or_fetch(
        self,
        adapter: BrowserAdapter,
        template: BrowserTemplate,
        url: str,
        path: Path,
        workspace: Path,
        timeout_ms: int,
        *,
        page_url: str = "",
    ) -> tuple[bool, str | None]:
        cache = self._cache_for(workspace)
        cached = cache.get(url)
        if cached is not None and cached.is_file() and cached != path:
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cached, path)
            return True, cached.relative_to(workspace).as_posix()
        path.parent.mkdir(parents=True, exist_ok=True)
        if await attach.session_fetch(
            adapter, template, url, path, timeout_ms=timeout_ms, page_url=page_url
        ):
            cache[url] = path
            return True, None
        return False, None

    def _build_relative(
        self,
        spec: AttachmentSpec,
        record: dict[str, Any] | None,
        original_name: str,
        *,
        ext: str,
        index: int,
        used_paths: set[Path],
    ) -> Path:
        rendered = attach.apply_filename_pattern(
            spec.filename_pattern,
            record=record,
            original_name=original_name,
            index=index,
            ext=ext,
        )
        name = safe_filename(rendered, fallback=original_name, max_length=64)
        relative = self._unique_relative(
            Path(safe_relative_subdir(spec.destination_subdir)) / name, used_paths
        )
        return relative

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
        template: BrowserTemplate,
        snapshot: BrowserSnapshot,
        spec: AttachmentSpec,
        record_key: str | None,
        record: dict[str, Any] | None,
        terms: list[str],
    ) -> list[tuple[str, dict[str, Any] | None]]:
        """Return ``(target, element)`` pairs; several when the spec allows multiple files."""
        elements = attach.find_elements(
            snapshot,
            terms,
            record_key=record_key,
            record=record,
            match_by=list(spec.match_by),
        )
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
            terms,
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
            if looks_like_url(raw):
                continue
            tail = raw.split("?", 1)[0].split("#", 1)[0].rstrip("/").rsplit("/", 1)[-1]
            if re.search(r"\.[A-Za-z0-9]{2,5}$", tail):
                return tail
        return None

    @staticmethod
    def _record_key(template: BrowserTemplate, record: dict[str, Any]) -> str | None:
        values = [str(record.get(key, "")) for key in template.target.record_key]
        return "|".join(values) if values and all(values) else None
