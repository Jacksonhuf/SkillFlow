"""Network-level acquisition: learn JSON endpoints during Teach, read them during Run.

Everything here works on exchanges the browser already performed inside the user's authenticated
session. The runtime never issues its own HTTP requests to the target system.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from browser_skill.models import (
    AcquisitionSource,
    BrowserSnapshot,
    BrowserTemplate,
    FieldSpec,
    LearnedMapping,
    NetworkExchange,
    SourcePage,
)

_MAX_DEPTH = 5
_MAX_ARRAYS = 40
_MIN_MATCH_RATIO = 0.5
_ARRAY_SUFFIX = "[*]"


# --------------------------------------------------------------------------- parsing


def _parse_body(raw: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if isinstance(raw, str):
        text = raw.strip()
        if not text or text[0] not in "[{":
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None
    return None


def parse_exchanges(data: Any) -> list[NetworkExchange]:
    """Normalize adapter output (list of dicts with loose key names) into NetworkExchange."""
    if isinstance(data, dict):
        for key in ("requests", "exchanges", "entries", "items", "data"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if isinstance(data, str):
        data = _parse_body(data)
    if not isinstance(data, list):
        return []
    exchanges: list[NetworkExchange] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        entry: dict[str, Any] = item
        request: dict[str, Any] = entry["request"] if isinstance(entry.get("request"), dict) else {}
        response: dict[str, Any] = (
            entry["response"] if isinstance(entry.get("response"), dict) else {}
        )
        headers: dict[str, Any] = (
            response["headers"] if isinstance(response.get("headers"), dict) else {}
        )
        url = entry.get("url") or entry.get("request_url") or request.get("url")
        if not isinstance(url, str) or not url:
            continue
        content_type = str(
            entry.get("content_type")
            or entry.get("mime_type")
            or entry.get("mimeType")
            or response.get("content_type")
            or response.get("mimeType")
            or headers.get("content-type")
            or headers.get("Content-Type")
            or ""
        )
        body = _parse_body(
            entry.get("body")
            if "body" in entry
            else entry.get("response_body", response.get("body", response.get("content")))
        )
        try:
            status = int(entry.get("status", response.get("status", 200)) or 0)
        except (TypeError, ValueError):
            status = 0
        try:
            size = int(entry.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        try:
            exchanges.append(
                NetworkExchange(
                    url=url,
                    method=str(entry.get("method", request.get("method", "GET"))),
                    status=max(0, min(status, 999)),
                    content_type=content_type,
                    body=body,
                    size=max(0, size),
                )
            )
        except (TypeError, ValueError):
            continue
    return exchanges


def endpoint_of(url: str) -> str:
    parts = urlsplit(url)
    return parts.path or "/"


def host_allowed(url: str, template: BrowserTemplate) -> bool:
    host = (urlsplit(url).hostname or "").casefold()
    if not host:
        return False
    return any(
        host == allowed.casefold() or host.endswith("." + allowed.casefold())
        for allowed in template.system.allowed_hosts
    )


# --------------------------------------------------------------------------- key matching


def _normalize_key(value: str) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", text.casefold())


def _field_candidates(field: FieldSpec) -> set[str]:
    values = {field.key, field.name, *field.semantic, *field.aliases}
    return {_normalize_key(item) for item in values if item}


def match_field_key(field: FieldSpec, keys: list[str]) -> str | None:
    candidates = _field_candidates(field)
    normalized = {key: _normalize_key(key) for key in keys}
    for key, norm in normalized.items():
        if norm in candidates:
            return key
    for key, norm in normalized.items():
        if any(cand and (cand in norm or norm in cand) for cand in candidates if len(cand) >= 3):
            return key
    return None


# --------------------------------------------------------------------------- JSON walking


@dataclass(slots=True)
class RecordArray:
    path: str
    items: list[dict[str, Any]]

    @property
    def keys(self) -> list[str]:
        seen: dict[str, None] = {}
        for item in self.items[:50]:
            for key in item:
                seen.setdefault(str(key), None)
        return list(seen)


def find_record_arrays(body: Any) -> list[RecordArray]:
    found: list[RecordArray] = []

    def walk(node: Any, path: str, depth: int) -> None:
        if len(found) >= _MAX_ARRAYS or depth > _MAX_DEPTH:
            return
        if isinstance(node, list):
            dict_items = [item for item in node if isinstance(item, dict)]
            if dict_items and len(dict_items) == len(node):
                found.append(RecordArray(path=f"{path}{_ARRAY_SUFFIX}", items=dict_items))
            for item in node[:3]:
                if isinstance(item, (dict, list)):
                    walk(item, f"{path}{_ARRAY_SUFFIX}", depth + 1)
        elif isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, (dict, list)):
                    walk(value, f"{path}.{key}", depth + 1)

    walk(body, "$", 0)
    return found


def resolve_path(body: Any, path: str) -> list[dict[str, Any]]:
    """Resolve a json_path of the form ``$.a.b[*]`` (single array level) to dict items."""
    if not path.startswith("$"):
        return []
    trimmed = path[1:]
    if trimmed.endswith(_ARRAY_SUFFIX):
        trimmed = trimmed[: -len(_ARRAY_SUFFIX)]
    node: Any = body
    for segment in [part for part in trimmed.split(".") if part]:
        if isinstance(node, dict) and segment in node:
            node = node[segment]
        else:
            return []
    if isinstance(node, list):
        return [item for item in node if isinstance(item, dict)]
    return []


def split_field_path(json_path: str) -> tuple[str, str]:
    """``$.data.list[*].orderNo`` → (``$.data.list[*]``, ``orderNo``)."""
    marker = json_path.rfind(_ARRAY_SUFFIX + ".")
    if marker == -1:
        return json_path, ""
    return json_path[: marker + len(_ARRAY_SUFFIX)], json_path[marker + len(_ARRAY_SUFFIX) + 1 :]


# --------------------------------------------------------------------------- discovery


@dataclass(slots=True)
class NetworkDiscoveryResult:
    mappings: dict[str, LearnedMapping]
    endpoint: str | None = None
    array_path: str | None = None
    matched_fields: list[str] | None = None
    exchanges_considered: int = 0


class NetworkDiscovery:
    """Pick the JSON exchange whose record array best covers the template's list fields."""

    def discover(
        self, template: BrowserTemplate, exchanges: list[NetworkExchange]
    ) -> NetworkDiscoveryResult:
        list_fields = [f for f in template.target.fields if f.source == SourcePage.LIST]
        if not list_fields:
            return NetworkDiscoveryResult(mappings={})
        required = {f.key for f in list_fields if f.required}
        best: tuple[float, NetworkExchange, RecordArray, dict[str, str]] | None = None
        considered = 0
        for exchange in exchanges:
            if not exchange.is_json or exchange.body is None or exchange.status >= 400:
                continue
            if not host_allowed(exchange.url, template):
                continue
            considered += 1
            for array in find_record_arrays(exchange.body):
                keys = array.keys
                matched = {
                    field.key: key
                    for field in list_fields
                    if (key := match_field_key(field, keys)) is not None
                }
                if not matched or not required <= set(matched):
                    continue
                ratio = len(matched) / len(list_fields)
                if ratio < _MIN_MATCH_RATIO:
                    continue
                score = ratio + min(len(array.items), 100) / 1000
                if best is None or score > best[0]:
                    best = (score, exchange, array, matched)
        if best is None:
            return NetworkDiscoveryResult(mappings={}, exchanges_considered=considered)
        score, exchange, array, matched = best
        endpoint = endpoint_of(exchange.url)
        confidence = round(min(0.95, 0.6 + 0.35 * (len(matched) / len(list_fields))), 2)
        mappings = {
            field_key: LearnedMapping(
                page=SourcePage.LIST,
                strategy="semantic",
                hints=[json_key],
                confidence=confidence,
                preferred_source=AcquisitionSource.NETWORK,
                endpoint_hint=endpoint,
                json_path=f"{array.path}.{json_key}",
            )
            for field_key, json_key in matched.items()
        }
        return NetworkDiscoveryResult(
            mappings=mappings,
            endpoint=endpoint,
            array_path=array.path,
            matched_fields=sorted(matched),
            exchanges_considered=considered,
        )


# --------------------------------------------------------------------------- run-time source


def exchange_fingerprint(exchange: NetworkExchange) -> str:
    payload = json.dumps(
        {"url": exchange.url, "body": exchange.body},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class NetworkRecordSource:
    """Per-page record provider for ``RecordExtractor.collect``.

    Each call lists the browser's observed exchanges, keeps only the ones not seen on earlier
    pages, and extracts records through the learned endpoint mapping. Returning ``None`` lets the
    extractor fall back to DOM parsing for that page, so pagination keeps working even when a page
    was rendered without a fresh JSON response.
    """

    def __init__(self, adapter: Any, template: BrowserTemplate) -> None:
        self.adapter = adapter
        self.template = template
        self.extractor = NetworkExtractor()
        self._seen: set[str] = set()
        self.network_pages = 0
        self.dom_pages = 0
        self.listing_failures = 0

    async def __call__(self, _snapshot: BrowserSnapshot) -> list[dict[str, Any]] | None:
        result = await self.adapter.network_requests()
        if not result.ok:
            self.listing_failures += 1
            self.dom_pages += 1
            return None
        fresh: list[NetworkExchange] = []
        for exchange in parse_exchanges(result.data):
            fingerprint = exchange_fingerprint(exchange)
            if fingerprint in self._seen:
                continue
            self._seen.add(fingerprint)
            fresh.append(exchange)
        records = self.extractor.extract(self.template, fresh) if fresh else None
        if records is None:
            self.dom_pages += 1
            return None
        self.network_pages += 1
        return records


# --------------------------------------------------------------------------- extraction


class NetworkExtractor:
    """Read learned network mappings from observed exchanges; returns None when unusable."""

    @staticmethod
    def network_field_mappings(template: BrowserTemplate) -> dict[str, LearnedMapping]:
        return {
            key: mapping
            for key, mapping in template.learned.field_mappings.items()
            if mapping.preferred_source == AcquisitionSource.NETWORK
            and mapping.endpoint_hint
            and mapping.json_path
        }

    def extract(
        self, template: BrowserTemplate, exchanges: list[NetworkExchange]
    ) -> list[dict[str, Any]] | None:
        mappings = self.network_field_mappings(template)
        if not mappings:
            return None
        required = {f.key for f in template.target.fields if f.required and f.source == "list"}
        if not required <= set(mappings):
            return None
        by_endpoint: dict[tuple[str, str], dict[str, str]] = {}
        for field_key, mapping in mappings.items():
            array_path, json_key = split_field_path(mapping.json_path or "")
            if not json_key or mapping.endpoint_hint is None:
                return None
            by_endpoint.setdefault((mapping.endpoint_hint, array_path), {})[field_key] = json_key
        if len(by_endpoint) != 1:
            return None
        (endpoint, array_path), key_map = next(iter(by_endpoint.items()))
        candidates = [
            exchange
            for exchange in exchanges
            if exchange.is_json
            and exchange.body is not None
            and exchange.status < 400
            and host_allowed(exchange.url, template)
            and endpoint_of(exchange.url) == endpoint
        ]
        if not candidates:
            return None
        records: list[dict[str, Any]] = []
        for exchange in candidates:
            for item in resolve_path(exchange.body, array_path):
                record = {
                    field_key: item.get(json_key)
                    for field_key, json_key in key_map.items()
                    if json_key in item
                }
                if record:
                    records.append(record)
        return records if records else None
