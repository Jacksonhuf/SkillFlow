"""Probe one example detail URL and propose URL variables, fields and attachments.

The probe only reads what the browser already shows or already fetched inside the user's
session: page text, interactive elements and captured JSON responses. It never issues its own
HTTP requests. Everything it returns is a *candidate* for the wizard; nothing is saved here.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from browser_skill.acquire.label_value import LabelValue, parse_label_values
from browser_skill.acquire.network import parse_exchanges
from browser_skill.acquire.tables import column_names, is_grid, tables_from_snapshot
from browser_skill.browser.base import BrowserAdapter
from browser_skill.errors import ErrorCode, SkillError
from browser_skill.models import (
    AuthSpec,
    AuthState,
    BrowserCapabilities,
    BrowserSnapshot,
    FieldType,
    LoginCheckSpec,
    NetworkExchange,
    ProbeAttachmentCandidate,
    ProbeFieldCandidate,
    ProbeTableCandidate,
    SignalSpec,
    UrlAnalysis,
    UrlProbeReport,
    UrlVariableSuggestion,
)
from browser_skill.runtime.auth import AuthClassifier
from browser_skill.runtime.sample_analyzer import SampleAnalyzer

VARIABLE_THRESHOLD = 0.6
_MAX_FIELDS = 60
_MAX_ATTACHMENTS = 30
_MAX_TABLES = 6
_PREVIEW_ROWS = 3
_MAX_JSON_DEPTH = 4
_MAX_KEYS_PER_EXCHANGE = 60

_ID_PATTERN = re.compile(r"^(?=.*\d)[A-Za-z0-9][A-Za-z0-9_\-]{2,}$")
_WORD_PATTERN = re.compile(r"^[A-Za-z]+$")
_COMMON_QUERY_KEYS = {"tab", "lang", "locale", "page", "size", "sort", "order", "view", "mode"}
_FILE_EXTENSIONS = ("pdf", "xlsx", "xls", "docx", "doc", "csv", "zip", "jpg", "jpeg", "png")
_DOWNLOAD_WORDS = ("下载", "附件", "凭证", "发票", "合同", "download", "attachment")
_EXPAND_WORDS = ("展开更多", "查看更多", "加载更多", "展开", "更多", "show more", "load more")
# Response-envelope / paging / tracing keys: never business data, so never offered as fields.
# Compared after camelCase→snake_case folding (``pageSize`` → ``page_size``).
_JSON_NOISE_KEYS = frozenset(
    {
        "code",
        "msg",
        "message",
        "success",
        "ok",
        "error",
        "errors",
        "err_code",
        "err_msg",
        "error_code",
        "error_msg",
        "result_code",
        "result_msg",
        "status_code",
        "total",
        "total_count",
        "total_pages",
        "total_page",
        "page",
        "page_no",
        "page_num",
        "page_number",
        "page_size",
        "page_index",
        "size",
        "current",
        "pages",
        "offset",
        "limit",
        "has_next",
        "has_more",
        "has_previous",
        "timestamp",
        "time_stamp",
        "server_time",
        "trace_id",
        "request_id",
        "req_id",
        "span_id",
        "token",
        "access_token",
        "refresh_token",
        "sign",
        "signature",
        "nonce",
        "version",
        "api_version",
        "cost",
        "elapsed",
        "duration_ms",
    }
)
# Recommended DOM pairs: colon/tab pairs only; "label line + value line" guesses (0.5) are not.
_RECOMMEND_DOM_CONFIDENCE = 0.8

_GLOSSARY: dict[str, str] = {
    "订单号": "order_no",
    "订单编号": "order_no",
    "订单": "order",
    "合同": "contract",
    "发票": "invoice",
    "凭证": "evidence",
    "附件": "attachment",
    "客户名称": "customer_name",
    "客户": "customer",
    "供应商": "supplier",
    "金额": "amount",
    "总金额": "total_amount",
    "单价": "unit_price",
    "数量": "quantity",
    "日期": "date",
    "时间": "time",
    "创建时间": "created_at",
    "更新时间": "updated_at",
    "状态": "status",
    "名称": "name",
    "编号": "no",
    "备注": "remark",
    "地址": "address",
    "电话": "phone",
    "联系人": "contact",
    "产品": "product",
    "型号": "model",
    "类型": "type",
    "序列号": "sn",
    "样机": "sample",
    "负责人": "owner",
    "部门": "department",
    # line-item / grid headers
    "序号": "seq_no",
    "行号": "row_no",
    "物料编码": "material_code",
    "物料名称": "material_name",
    "物料": "material",
    "商品名称": "product_name",
    "商品编码": "product_code",
    "商品": "product",
    "规格": "spec",
    "规格型号": "spec",
    "单位": "unit",
    "税率": "tax_rate",
    "税额": "tax_amount",
    "小计": "subtotal",
    "合计": "total",
    "折扣": "discount",
    "付款日期": "payment_date",
    "付款金额": "payment_amount",
    "方式": "method",
    "操作": "action",
    "操作人": "operator",
}


def default_probe_auth() -> AuthSpec:
    return AuthSpec(
        login_check=LoginCheckSpec(any=[SignalSpec(semantic_element="退出登录")]),
        unauthenticated_signals=[
            SignalSpec(semantic_element="登录"),
            SignalSpec(semantic_element="用户名"),
        ],
    )


# --------------------------------------------------------------------------- keys


def machine_key(name: str, *, fallback: str, used: set[str]) -> str:
    """ASCII snake_case key for a human label; Chinese labels go through a small glossary."""
    candidate = _GLOSSARY.get(name.strip())
    if candidate is None:
        translated = name
        for word, ascii_word in sorted(_GLOSSARY.items(), key=lambda item: -len(item[0])):
            translated = translated.replace(word, f" {ascii_word} ")
        translated = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", translated)
        normalized = re.sub(r"[^a-z0-9]+", "_", translated.casefold()).strip("_")
        candidate = normalized if normalized and normalized[0].isalpha() else ""
    if not candidate:
        candidate = fallback
    candidate = candidate[:64]
    unique = candidate
    suffix = 2
    while unique in used:
        tail = f"_{suffix}"
        unique = f"{candidate[: 64 - len(tail)]}{tail}"
        suffix += 1
    used.add(unique)
    return unique


def _singular(word: str) -> str:
    if len(word) > 3 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


# --------------------------------------------------------------------------- URL analysis


def _score_token(value: str, *, page_text: str, sibling_variation: bool) -> float:
    score = 0.3
    if _ID_PATTERN.match(value):
        score += 0.5
    if value and value.casefold() in page_text.casefold():
        score += 0.3
    if sibling_variation:
        score += 0.2
    if _WORD_PATTERN.match(value) or value.casefold() in _COMMON_QUERY_KEYS:
        score -= 0.6
    return max(0.0, min(1.0, round(score, 2)))


def _sibling_varies(url_parts: Any, index: int, links: list[str]) -> bool:
    """True when another same-site link differs from the URL only in path segment ``index``."""
    segments = url_parts.path.strip("/").split("/")
    for link in links:
        other = urlsplit(link)
        if (other.hostname or "").casefold() != (url_parts.hostname or "").casefold():
            continue
        other_segments = other.path.strip("/").split("/")
        if len(other_segments) != len(segments):
            continue
        if other_segments[index] == segments[index]:
            continue
        if all(
            a == b
            for i, (a, b) in enumerate(zip(segments, other_segments, strict=True))
            if i != index
        ):
            return True
    return False


def analyze_url(url: str, snapshot: BrowserSnapshot | None = None) -> UrlAnalysis:
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise SkillError(ErrorCode.VARIABLE_INVALID, "请提供完整的 http(s) 详情页地址")
    page_text = snapshot.text if snapshot else ""
    links = [
        str(element["href"])
        for element in (snapshot.elements if snapshot else [])
        if isinstance(element.get("href"), str)
    ]
    used: set[str] = set()
    variables: list[UrlVariableSuggestion] = []
    segments = parts.path.strip("/").split("/") if parts.path.strip("/") else []
    for index, segment in enumerate(segments):
        if not segment:
            continue
        score = _score_token(
            segment,
            page_text=page_text,
            sibling_variation=_sibling_varies(parts, index, links),
        )
        if score <= 0.0:
            continue
        previous = (
            segments[index - 1] if index > 0 and _WORD_PATTERN.match(segments[index - 1]) else ""
        )
        stem = _singular(previous.casefold()) if previous else "item"
        suffix = "_no" if re.search(r"[A-Za-z]", segment) and re.search(r"\d", segment) else "_id"
        name = machine_key(stem + suffix, fallback="item_id", used=used)
        variables.append(
            UrlVariableSuggestion(
                name=name,
                sample=segment,
                position=f"path[{index}]",
                confidence=score,
                selected=score >= VARIABLE_THRESHOLD,
            )
        )
    query = parse_qsl(parts.query, keep_blank_values=True)
    for key, value in query:
        if not value:
            continue
        score = _score_token(value, page_text=page_text, sibling_variation=False)
        if key.casefold() in _COMMON_QUERY_KEYS:
            score = max(0.0, score - 0.3)
        if score <= 0.0:
            continue
        name = machine_key(key, fallback="query_id", used=used)
        variables.append(
            UrlVariableSuggestion(
                name=name,
                sample=value,
                position=f"query:{key}",
                confidence=score,
                selected=score >= VARIABLE_THRESHOLD,
            )
        )
    variables.sort(key=lambda item: -item.confidence)
    return UrlAnalysis(
        url=url.strip(),
        host=parts.hostname,
        template_suggestion=render_template_suggestion(url, variables),
        variables=variables,
    )


def render_template_suggestion(url: str, variables: list[UrlVariableSuggestion]) -> str:
    """Rebuild ``url`` with ``{name}`` in place of every *selected* variable."""
    parts = urlsplit(url.strip())
    segments = parts.path.strip("/").split("/") if parts.path.strip("/") else []
    query = parse_qsl(parts.query, keep_blank_values=True)
    for variable in variables:
        if not variable.selected:
            continue
        if variable.position.startswith("path["):
            index = int(variable.position[5:-1])
            if 0 <= index < len(segments):
                segments[index] = "{" + variable.name + "}"
        elif variable.position.startswith("query:"):
            key = variable.position[6:]
            query = [(k, "{" + variable.name + "}" if k == key else v) for k, v in query]
    path = "/" + "/".join(segments) if segments else parts.path or "/"
    if parts.path.endswith("/") and segments:
        path += "/"
    rendered_query = urlencode(query, safe="{}") if query else ""
    return urlunsplit((parts.scheme, parts.netloc, path, rendered_query, ""))


# --------------------------------------------------------------------------- field candidates


def _flatten(node: Any, path: str, depth: int, out: list[tuple[str, Any]]) -> None:
    if len(out) >= _MAX_KEYS_PER_EXCHANGE or depth > _MAX_JSON_DEPTH:
        return
    if isinstance(node, dict):
        for key, value in node.items():
            _flatten(value, f"{path}.{key}", depth + 1, out)
    elif isinstance(node, list):
        # Arrays are sub-records (P3 scope: attachments only); scalars lists are joined
        if node and all(not isinstance(item, (dict, list)) for item in node):
            out.append((path, ", ".join(str(item) for item in node[:10])))
    elif node is not None and node != "":
        out.append((path, node))


def generalize_endpoint(path: str, samples: dict[str, UrlVariableSuggestion]) -> str:
    """``/api/orders/ORD-1`` → ``/api/orders/{order_no}`` so the hint matches every item."""
    segments = path.strip("/").split("/")
    rendered = [
        "{" + samples[segment].name + "}" if segment in samples else segment for segment in segments
    ]
    return "/" + "/".join(rendered)


def _comparable(value: Any) -> str:
    """Normalize a value so ``¥1,200.00`` (page) and ``1200.0`` (JSON) compare equal."""
    text = re.sub(r"[\s,，¥$€£%]", "", str(value)).casefold()
    try:
        return repr(float(text))
    except ValueError:
        return text


def _json_key_label(path: str) -> str:
    last = path.rsplit(".", 1)[-1]
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", last).casefold()


def _is_noise_path(path: str) -> bool:
    """``$.code`` / ``$.data.pageSize`` / ``$.meta.traceId`` are envelope keys, not fields."""
    return _json_key_label(path) in _JSON_NOISE_KEYS


def _mentions_sample(exchange: NetworkExchange, samples: dict[str, UrlVariableSuggestion]) -> bool:
    haystack = exchange.url + " " + str(exchange.body)
    return any(sample in haystack for sample in samples)


def relevant_exchanges(
    exchanges: list[NetworkExchange], samples: dict[str, UrlVariableSuggestion]
) -> list[NetworkExchange]:
    """Keep only the responses that belong to *this* record.

    A detail page also loads menus, permissions, the current user and dictionaries. When the
    URL carries a business id and at least one response mentions it (in the request URL or in
    the body), only those responses are used; the rest is noise. Without such a signal every
    response is kept so the user still sees something to pick from.
    """
    if not samples:
        return exchanges
    matching = [item for item in exchanges if _mentions_sample(item, samples)]
    return matching or exchanges


class UrlProber:
    """Open one detail URL and describe what could be extracted from it."""

    def __init__(self, *, auth: AuthClassifier | None = None) -> None:
        self.auth = auth or AuthClassifier()

    async def probe(
        self,
        adapter: BrowserAdapter,
        url: str,
        *,
        capabilities: BrowserCapabilities,
    ) -> UrlProbeReport:
        analyze_url(url)
        opened = await adapter.open(url.strip())
        if not opened.ok:
            raise SkillError(ErrorCode.PAGE_NOT_FOUND, "无法打开该地址，请检查 URL 是否可访问")
        snapshot = await adapter.snapshot(interactive=True)
        auth_state = self.auth.classify(default_probe_auth(), snapshot)
        analysis = analyze_url(url, snapshot)
        warnings: list[str] = []
        if auth_state == AuthState.UNAUTHENTICATED:
            warnings.append("页面显示为登录页：请先在 Chrome 中登录该系统，然后重新探测。")
            return UrlProbeReport(
                url_analysis=analysis,
                page_title=snapshot.title,
                auth_state=auth_state,
                warnings=warnings,
            )
        exchanges: list[NetworkExchange] = []
        if capabilities.network:
            listing = await adapter.network_requests()
            if listing.ok:
                exchanges = [
                    item
                    for item in parse_exchanges(listing.data)
                    if isinstance(item.body, (dict, list))
                    and 200 <= item.status < 300
                    and (urlsplit(item.url).hostname or "").casefold() == analysis.host.casefold()
                ]
        else:
            warnings.append("当前浏览器不支持读取网络响应，字段候选仅来自页面文字。")
        fields = self.field_candidates(analysis, snapshot, exchanges)
        attachments = self.attachment_candidates(snapshot)
        samples = {v.sample: v for v in analysis.variables if v.selected}
        tables = self.table_candidates(snapshot, samples)
        if not fields and not tables:
            warnings.append("未在页面上识别到字段候选，请确认页面已完全加载。")
        if any(
            str(element.get("text", "")).strip().casefold() in _EXPAND_WORDS
            for element in snapshot.elements
        ):
            warnings.append("页面存在「展开/更多」按钮，可能隐藏更多字段。")
        if not analysis.variables or not any(v.selected for v in analysis.variables):
            warnings.append("未能从 URL 中识别出业务编号，运行时需直接提供完整详情页地址。")
        return UrlProbeReport(
            url_analysis=analysis,
            page_title=snapshot.title,
            auth_state=auth_state,
            fields=fields,
            attachments=attachments,
            tables=tables,
            warnings=warnings,
            network_exchanges=len(exchanges),
        )

    # ------------------------------------------------------------------ fields

    def field_candidates(
        self,
        analysis: UrlAnalysis,
        snapshot: BrowserSnapshot,
        exchanges: list[NetworkExchange],
    ) -> list[ProbeFieldCandidate]:
        pairs = parse_label_values(snapshot.text)
        for element in snapshot.elements:
            label = element.get("label") or element.get("aria_label")
            value = element.get("value")
            if (
                isinstance(label, str)
                and value not in (None, "")
                and str(element.get("role", ""))
                in {
                    "textbox",
                    "combobox",
                    "",
                }
            ):
                pairs.append(LabelValue(label.strip(), str(value)[:200], 0.85))
        samples = {
            variable.sample: variable for variable in analysis.variables if variable.selected
        }
        used: set[str] = set()
        candidates: list[ProbeFieldCandidate] = []
        seen_names: dict[str, int] = {}

        def add(candidate: ProbeFieldCandidate) -> None:
            folded = candidate.name.casefold()
            existing = seen_names.get(folded)
            if existing is not None:
                current = candidates[existing]
                recommended = current.recommended or candidate.recommended
                if candidate.confidence > current.confidence:
                    used.discard(current.key)
                    candidates[existing] = candidate.model_copy(
                        update={"key": current.key, "recommended": recommended}
                    )
                elif recommended != current.recommended:
                    candidates[existing] = current.model_copy(update={"recommended": True})
                return
            seen_names[folded] = len(candidates)
            candidates.append(candidate)

        # URL variables first: the label whose value equals the sample names the variable
        for variable in analysis.variables:
            if not variable.selected:
                continue
            label = next((pair.label for pair in pairs if pair.value == variable.sample), None)
            used.add(variable.name)
            add(
                ProbeFieldCandidate(
                    key=variable.name,
                    name=label or variable.name,
                    sample=variable.sample,
                    source="url",
                    strategy="semantic",
                    type=SampleAnalyzer._infer_type([variable.sample]),
                    confidence=variable.confidence,
                    recommended=True,
                )
            )
        for pair in pairs:
            if pair.value in samples or len(pair.value) > 200:
                continue
            key = machine_key(pair.label, fallback=f"field_{len(candidates) + 1}", used=used)
            add(
                ProbeFieldCandidate(
                    key=key,
                    name=pair.label,
                    sample=pair.value,
                    source="dom",
                    strategy="label_value",
                    type=SampleAnalyzer._infer_type([pair.value]),
                    confidence=pair.confidence,
                    recommended=pair.confidence >= _RECOMMEND_DOM_CONFIDENCE,
                )
            )
        value_to_label = {_comparable(pair.value): pair.label for pair in pairs}
        for exchange in relevant_exchanges(exchanges, samples):
            flat: list[tuple[str, Any]] = []
            _flatten(exchange.body, "$", 0, flat)
            body_text = str(exchange.body)
            contains_sample = any(sample in body_text for sample in samples)
            endpoint_hint = generalize_endpoint(urlsplit(exchange.url).path or "/", samples)
            for path, raw in flat:
                text = str(raw)
                if not text or len(text) > 200 or text in samples or _is_noise_path(path):
                    continue
                label = value_to_label.get(_comparable(raw))
                json_label = _json_key_label(path)
                name = label or json_label
                key = machine_key(
                    json_label if label is None else label,
                    fallback=f"field_{len(candidates) + 1}",
                    used=used,
                )
                confidence = 0.6 + (0.3 if contains_sample else 0.0) + (0.05 if label else 0.0)
                add(
                    ProbeFieldCandidate(
                        key=key,
                        name=name,
                        sample=text,
                        source="network",
                        strategy="semantic",
                        type=SampleAnalyzer._infer_type([raw]),
                        confidence=min(1.0, round(confidence, 2)),
                        endpoint_hint=endpoint_hint,
                        json_path=path,
                        aliases=[json_label] if label and json_label != label else [],
                        # Only JSON values that are also visible on the page are recommended;
                        # the rest of the payload stays available under "more candidates".
                        recommended=label is not None,
                    )
                )
        candidates.sort(
            key=lambda item: (item.source != "url", not item.recommended, -item.confidence)
        )
        return candidates[:_MAX_FIELDS]

    # ------------------------------------------------------------------ tables

    def table_candidates(
        self, snapshot: BrowserSnapshot, samples: dict[str, UrlVariableSuggestion] | None = None
    ) -> list[ProbeTableCandidate]:
        """Every grid on the page (header row + data rows) as a possible source of records.

        Key/value tables are already read as page fields and are skipped here. A grid is
        *recommended* when it has real headers and more than one row: that is what line items,
        payments or logs look like. The first non-empty row supplies column samples.
        """
        out: list[ProbeTableCandidate] = []
        for table in tables_from_snapshot(snapshot):
            if not is_grid(table):
                continue
            names = column_names(table)
            first = next((row for row in table.rows if any(cell.strip() for cell in row)), [])
            used: set[str] = set(samples or {})
            columns: list[ProbeFieldCandidate] = []
            for position, name in enumerate(names):
                sample = first[position] if position < len(first) else ""
                key = machine_key(name, fallback=f"col_{position + 1}", used=used)
                columns.append(
                    ProbeFieldCandidate(
                        key=key,
                        name=name,
                        sample=sample[:200],
                        source="table",
                        strategy="table_header",
                        type=SampleAnalyzer._infer_type([sample]) if sample else FieldType.STRING,
                        confidence=0.9 if table.headers else 0.6,
                        recommended=True,
                        column=position,
                    )
                )
            has_headers = bool(table.headers) and any(item.strip() for item in table.headers)
            out.append(
                ProbeTableCandidate(
                    index=table.index,
                    title=table.title,
                    headers=names,
                    columns=columns,
                    row_count=len(table.rows),
                    preview=[row[: len(names)] for row in table.rows[:_PREVIEW_ROWS]],
                    recommended=has_headers and len(table.rows) >= 2,
                )
            )
        out.sort(key=lambda item: (not item.recommended, -item.row_count))
        return out[:_MAX_TABLES]

    # ------------------------------------------------------------------ attachments

    def attachment_candidates(self, snapshot: BrowserSnapshot) -> list[ProbeAttachmentCandidate]:
        groups: dict[str, dict[str, Any]] = {}
        for element in snapshot.elements:
            filename = str(element.get("filename") or "")
            href = str(element.get("href") or "")
            text = str(element.get("text") or element.get("name") or "").strip()
            extension = _extension_of(filename) or _extension_of(href) or _extension_of(text)
            semantic_hit = any(word in text.casefold() for word in _DOWNLOAD_WORDS)
            if not extension and not semantic_hit:
                continue
            base = filename or text or href.rsplit("/", 1)[-1]
            name = _attachment_group_name(base) or "附件"
            group = groups.setdefault(
                name,
                {"count": 0, "types": set(), "href": None, "confidence": 0.0},
            )
            group["count"] += 1
            if extension:
                group["types"].add(extension)
            if href and group["href"] is None:
                group["href"] = href
            group["confidence"] = max(group["confidence"], 0.8 if extension else 0.6)
        used: set[str] = set()
        candidates = [
            ProbeAttachmentCandidate(
                key=machine_key(name, fallback=f"attachment_{index}", used=used),
                name=name,
                count=data["count"],
                types=sorted(data["types"]),
                sample_href=data["href"],
                confidence=data["confidence"],
            )
            for index, (name, data) in enumerate(groups.items(), 1)
        ]
        candidates.sort(key=lambda item: -item.confidence)
        return candidates[:_MAX_ATTACHMENTS]


def _extension_of(value: str) -> str | None:
    match = re.search(r"\.([A-Za-z0-9]{2,5})(?:[?#].*)?$", value.strip())
    if not match:
        return None
    extension = match.group(1).casefold()
    return extension if extension in _FILE_EXTENSIONS else None


def _attachment_group_name(base: str) -> str:
    name = re.sub(r"[?#].*$", "", base.strip())
    name = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", name)
    name = re.sub(r"[\s_\-–—]*[\d（）()]+$", "", name).strip(" _-")
    return name[:40]
