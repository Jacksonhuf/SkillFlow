"""Universal attachment acquisition ladder (still browser-session scoped).

Order for each declared attachment:
1. Learned network JSON URL → session fetch
2. Captured network binary / Content-Disposition response
3. DOM control: session fetch when ``href`` is a stable http(s) URL
4. DOM control: click + browser download event
5. Heuristic network scan (URL / filename hints vs attachment semantics)
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

from browser_skill.acquire.network import (
    endpoint_matches,
    host_allowed,
    parse_exchanges,
    resolve_scalar,
)
from browser_skill.browser.base import BrowserAdapter
from browser_skill.models import (
    AttachmentSpec,
    BrowserSnapshot,
    BrowserTemplate,
    LearnedMapping,
    NetworkExchange,
)

_FILE_TYPE_HINTS = (
    "pdf",
    "octet-stream",
    "msword",
    "wordprocessingml",
    "spreadsheetml",
    "excel",
    "zip",
    "png",
    "jpeg",
    "gif",
)
_DOWNLOAD_WORDS = (
    "download",
    "attachment",
    "file",
    "pdf",
    "xlsx",
    "doc",
    "下载",
    "附件",
    "导出",
    "凭证",
    "合同",
    "发票",
)


def attachment_semantic_terms(spec: AttachmentSpec, template: BrowserTemplate) -> list[str]:
    terms = list(spec.semantic) + list(spec.aliases)
    learned = template.learned.attachment_mappings.get(spec.key)
    if learned:
        terms.extend(learned.hints)
    seen: set[str] = set()
    ordered: list[str] = []
    for item in terms:
        folded = item.casefold()
        if folded and folded not in seen:
            seen.add(folded)
            ordered.append(item)
    return ordered


def element_matches_record(
    element: dict[str, Any],
    *,
    record_key: str | None,
    record: dict[str, Any] | None,
    match_by: list[str],
) -> bool:
    if record_key and element.get("record_key") not in {None, record_key}:
        return False
    if not match_by or not record:
        return True
    haystack = " ".join(str(element.get(key, "")) for key in element.values()).casefold()
    if all(
        str(record.get(key, "")).casefold() in haystack for key in match_by if record.get(key)
    ):
        return True
    # Detail pages often expose one record without embedding driver ids in link text.
    return element.get("record_key") is None


def find_elements(
    snapshot: BrowserSnapshot,
    terms: list[str],
    *,
    record_key: str | None,
    record: dict[str, Any] | None,
    match_by: list[str],
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for element in snapshot.elements:
        if not element_matches_record(
            element, record_key=record_key, record=record, match_by=match_by
        ):
            continue
        text = " ".join(str(value) for value in element.values()).casefold()
        if any(term.casefold() in text for term in terms):
            matches.append(element)
    return matches


_FILE_EXTENSIONS = (
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".zip",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".txt",
    ".csv",
)


def is_fetchable_attachment_url(url: str, *, page_url: str = "") -> bool:
    """Return False for SPA hash routes and other non-file navigation URLs."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        return False
    path = parts.path or "/"
    lowered_path = path.casefold()
    if any(lowered_path.endswith(ext) for ext in _FILE_EXTENSIONS):
        return True
    if any(token in lowered_path for token in ("/download", "/file/", "/static/", "/attachment")):
        return True
    if parts.fragment and "#" in url:
        return False
    if page_url:
        page = urlsplit(page_url.strip())
        if (
            parts.scheme == page.scheme
            and parts.netloc == page.netloc
            and (parts.path or "/") == (page.path or "/")
        ):
            return False
    return False


def stable_http_url(snapshot: BrowserSnapshot, element: dict[str, Any] | None) -> str | None:
    if not element:
        return None
    href = str(element.get("href") or "").strip()
    if not href or href.startswith(("javascript:", "data:", "blob:")):
        return None
    if href.startswith("#"):
        return None
    absolute = urljoin(snapshot.url or "", href)
    if not absolute.startswith(("http://", "https://")):
        return None
    if not is_fetchable_attachment_url(absolute, page_url=snapshot.url or ""):
        return None
    return absolute


def _is_file_content_type(content_type: str) -> bool:
    folded = content_type.casefold()
    return any(hint in folded for hint in _FILE_TYPE_HINTS)


def _url_matches_attachment(url: str, terms: list[str]) -> bool:
    folded = url.casefold()
    return any(term.casefold() in folded for term in terms)


def _render_endpoint_hint(hint: str, record: dict[str, Any] | None) -> str:
    rendered = hint
    if record:
        for key, value in record.items():
            rendered = rendered.replace("{" + str(key) + "}", str(value))
    return rendered


def network_json_file_url(
    exchanges: list[NetworkExchange],
    mapping: LearnedMapping,
    record: dict[str, Any] | None,
) -> str | None:
    if not mapping.endpoint_hint or not mapping.json_path:
        return None
    hint = _render_endpoint_hint(mapping.endpoint_hint, record)
    for exchange in exchanges:
        if exchange.body is None or exchange.status >= 400:
            continue
        path = urlsplit(exchange.url).path or "/"
        if not endpoint_matches(hint, path):
            continue
        value = resolve_scalar(exchange.body, mapping.json_path)
        if (
            isinstance(value, str)
            and value.startswith(("http://", "https://"))
            and is_fetchable_attachment_url(value)
        ):
            return value
        if isinstance(value, str) and value.startswith("/"):
            parts = urlsplit(exchange.url)
            return f"{parts.scheme}://{parts.netloc}{value}"
    return None


def network_binary_match(
    exchanges: list[NetworkExchange],
    mapping: LearnedMapping | None,
    terms: list[str],
    template: BrowserTemplate,
) -> NetworkExchange | None:
    for exchange in reversed(exchanges):
        if exchange.status >= 400 or not exchange.body_base64:
            continue
        if not host_allowed(exchange.url, template):
            continue
        if mapping and mapping.endpoint_hint:
            hint = mapping.endpoint_hint
            if not endpoint_matches(hint, urlsplit(exchange.url).path or "/"):
                continue
        elif not (
            _is_file_content_type(exchange.content_type)
            or _url_matches_attachment(exchange.url, terms)
        ):
            continue
        if terms and not (
            _url_matches_attachment(exchange.url, terms)
            or _is_file_content_type(exchange.content_type)
        ):
            continue
        return exchange
    return None


def write_network_binary(exchange: NetworkExchange, path: Path) -> bool:
    if not exchange.body_base64:
        return False
    try:
        raw = base64.b64decode(exchange.body_base64, validate=True)
    except (ValueError, TypeError):
        return False
    if not raw:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path.stat().st_size > 0


async def session_fetch(
    adapter: BrowserAdapter,
    template: BrowserTemplate,
    url: str,
    path: Path,
    *,
    timeout_ms: int,
    page_url: str = "",
) -> bool:
    if not host_allowed(url, template):
        return False
    if not is_fetchable_attachment_url(url, page_url=page_url):
        return False
    result = await adapter.fetch_resource(url, path, timeout_ms=timeout_ms)
    return bool(result.ok and path.is_file() and path.stat().st_size > 0)


def guess_extension(content_type: str, url: str, path: Path) -> str:
    if path.suffix:
        return path.suffix.lstrip(".").lower()
    folded = content_type.casefold()
    if "pdf" in folded:
        return "pdf"
    if "spreadsheet" in folded or "excel" in folded:
        return "xlsx"
    if "word" in folded:
        return "docx"
    if "png" in folded:
        return "png"
    if "jpeg" in folded or "jpg" in folded:
        return "jpg"
    tail = urlsplit(url).path.rsplit("/", 1)[-1]
    if "." in tail:
        return tail.rsplit(".", 1)[-1].lower()
    return "bin"


def apply_filename_pattern(
    pattern: str,
    *,
    record: dict[str, Any] | None,
    original_name: str,
    index: int,
    ext: str,
) -> str:
    rendered = pattern.replace("{original_name}", original_name)
    rendered = rendered.replace("{index}", str(index))
    rendered = rendered.replace("{ext}", ext)
    if record:
        for key, value in record.items():
            rendered = rendered.replace("{" + str(key) + "}", str(value))
    return rendered


def scan_json_for_file_urls(body: Any, terms: list[str], base_url: str) -> list[str]:
    """Find http(s) URLs in JSON when keys/values match attachment semantics."""
    found: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                key_fold = str(key).casefold()
                child_path = f"{path}.{key}"
                if isinstance(value, str):
                    if any(
                        term.casefold() in key_fold or term.casefold() in value.casefold()
                        for term in terms
                    ):
                        if value.startswith(("http://", "https://")):
                            found.append(value)
                        elif value.startswith("/"):
                            parts = urlsplit(base_url)
                            found.append(f"{parts.scheme}://{parts.netloc}{value}")
                elif isinstance(value, (dict, list)):
                    walk(value, child_path)
        elif isinstance(node, list):
            for item in node[:20]:
                if isinstance(item, (dict, list)):
                    walk(item, f"{path}[*]")

    walk(body, "$")
    return found


__all__ = [
    "apply_filename_pattern",
    "attachment_semantic_terms",
    "element_matches_record",
    "find_elements",
    "guess_extension",
    "is_fetchable_attachment_url",
    "network_binary_match",
    "network_json_file_url",
    "parse_exchanges",
    "scan_json_for_file_urls",
    "session_fetch",
    "stable_http_url",
    "write_network_binary",
]
