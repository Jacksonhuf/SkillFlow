from __future__ import annotations

import asyncio

import pytest

from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.errors import SkillError
from browser_skill.models import (
    AuthState,
    BrowserCapabilities,
    BrowserSnapshot,
    CommandResult,
    FieldType,
)
from browser_skill.runtime.url_probe import (
    UrlProber,
    analyze_url,
    generalize_endpoint,
    machine_key,
    render_template_suggestion,
)

SAMPLE_URL = "https://portal.example.com/orders/ORD-2024-0917/detail?tab=files"
DETAIL_TEXT = (
    "退出登录\n订单详情\n订单号：ORD-2024-0917\n客户名称：张三贸易\n金额：1200.00\n"
    "更新时间：2024-09-17\n"
)


def _detail_snapshot(**overrides: object) -> BrowserSnapshot:
    data: dict[str, object] = {
        "url": SAMPLE_URL,
        "title": "订单详情",
        "text": DETAIL_TEXT,
        "elements": [
            {"ref": "@a1", "role": "link", "text": "合同.pdf", "href": "/files/c1.pdf"},
            {"ref": "@a2", "role": "link", "text": "发票_1.pdf", "href": "/files/i1.pdf"},
            {"ref": "@a3", "role": "link", "text": "发票_2.jpg", "href": "/files/i2.jpg"},
            {"ref": "@b1", "role": "button", "text": "展开更多"},
            {
                "ref": "@l1",
                "role": "link",
                "text": "上一单",
                "href": "https://portal.example.com/orders/ORD-2024-0916/detail",
            },
        ],
    }
    data.update(overrides)
    return BrowserSnapshot.model_validate(data)


def test_analyze_url_marks_business_id_and_keeps_words_constant() -> None:
    analysis = analyze_url(SAMPLE_URL, _detail_snapshot())

    assert analysis.host == "portal.example.com"
    selected = [item for item in analysis.variables if item.selected]
    assert [item.name for item in selected] == ["order_no"]
    assert selected[0].sample == "ORD-2024-0917"
    assert selected[0].position == "path[1]"
    assert selected[0].confidence >= 0.8
    # "files" is a plain word in a common query key: never a variable
    assert not any(item.position == "query:tab" and item.selected for item in analysis.variables)
    assert (
        analysis.template_suggestion
        == "https://portal.example.com/orders/{order_no}/detail?tab=files"
    )


def test_analyze_url_without_page_uses_shape_only() -> None:
    analysis = analyze_url("https://example.internal/items/12345?lang=zh")

    ids = [item for item in analysis.variables if item.selected]
    assert [item.name for item in ids] == ["item_id"]
    assert ids[0].sample == "12345"
    assert analysis.template_suggestion == "https://example.internal/items/{item_id}?lang=zh"


def test_analyze_url_query_id_becomes_variable() -> None:
    analysis = analyze_url("https://example.internal/detail.do?id=A100&tab=x")

    selected = [item for item in analysis.variables if item.selected]
    assert [(item.name, item.sample) for item in selected] == [("id", "A100")]
    assert analysis.template_suggestion == "https://example.internal/detail.do?id={id}&tab=x"


def test_analyze_url_rejects_non_http() -> None:
    with pytest.raises(SkillError):
        analyze_url("ftp://example.internal/x")


def test_render_template_suggestion_respects_deselected_variables() -> None:
    analysis = analyze_url(SAMPLE_URL)
    for item in analysis.variables:
        item.selected = False

    assert render_template_suggestion(SAMPLE_URL, analysis.variables) == SAMPLE_URL


def test_machine_key_uses_glossary_and_stays_unique() -> None:
    used: set[str] = set()
    assert machine_key("订单号", fallback="f1", used=used) == "order_no"
    assert machine_key("订单号", fallback="f2", used=used) == "order_no_2"
    assert machine_key("客户名称", fallback="f3", used=used) == "customer_name"
    assert machine_key("totalAmount", fallback="f4", used=used) == "total_amount"
    assert machine_key("未知标签", fallback="field_5", used=used) == "field_5"


def test_generalize_endpoint_replaces_sample_segments() -> None:
    analysis = analyze_url(SAMPLE_URL)
    samples = {item.sample: item for item in analysis.variables if item.selected}

    assert generalize_endpoint("/api/orders/ORD-2024-0917", samples) == "/api/orders/{order_no}"
    assert generalize_endpoint("/api/me", samples) == "/api/me"


def test_probe_merges_dom_network_and_url_candidates() -> None:
    exchange = {
        "url": "https://portal.example.com/api/orders/ORD-2024-0917",
        "content_type": "application/json",
        "body": {
            "code": 0,
            "data": {
                "orderNo": "ORD-2024-0917",
                "customerName": "张三贸易",
                "amount": 1200.0,
                "tags": ["a", "b"],
                "lines": [{"sku": "X"}],
            },
        },
    }
    adapter = FakeBrowserAdapter(
        {
            "snapshot": [_detail_snapshot()],
            "network": [CommandResult(ok=True, operation="network", data=[exchange])],
        }
    )
    caps = BrowserCapabilities(snapshot=True, network=True)

    report = asyncio.run(UrlProber().probe(adapter, SAMPLE_URL, capabilities=caps))

    assert report.auth_state == AuthState.AUTHENTICATED
    assert report.page_title == "订单详情"
    assert report.network_exchanges == 1
    by_key = {item.key: item for item in report.fields}
    # URL variable is first and named after the page label that shows the same value
    assert report.fields[0].key == "order_no"
    assert report.fields[0].source == "url"
    assert report.fields[0].name == "订单号"
    # network value equal to a DOM pair merges into one candidate named by the page label
    customer = by_key["customer_name"]
    assert customer.source == "network"
    assert customer.name == "客户名称"
    assert customer.json_path == "$.data.customerName"
    assert customer.endpoint_hint == "/api/orders/{order_no}"
    assert customer.confidence > 0.9
    assert "customer_name" in customer.aliases or customer.aliases == []
    amount = by_key["amount"]
    assert amount.type == FieldType.NUMBER
    assert by_key["updated_at"].source == "dom"
    assert by_key["updated_at"].type == FieldType.DATE
    assert by_key["tags"].sample == "a, b"
    assert "lines" not in by_key  # arrays of objects are sub-records, out of P3 scope
    assert "code" not in by_key  # response-envelope keys are never offered
    # recommended = URL variable, colon pairs from the page, JSON values visible on the page
    assert {k for k, v in by_key.items() if v.recommended} == {
        "order_no",
        "customer_name",
        "amount",
        "updated_at",
    }
    assert by_key["tags"].recommended is False  # JSON-only value: folded into "more"
    # recommended candidates come first (after the URL variable), extras last
    recommended_flags = [item.recommended for item in report.fields]
    assert recommended_flags == sorted(recommended_flags, reverse=True)
    assert [item.name for item in report.attachments] == ["合同", "发票"]
    invoice = report.attachments[1]
    assert invoice.count == 2
    assert invoice.types == ["jpg", "pdf"]
    assert invoice.key == "invoice"
    assert any("展开" in warning for warning in report.warnings)


def test_probe_ignores_responses_that_do_not_belong_to_the_record() -> None:
    record = {
        "url": "https://portal.example.com/api/orders/ORD-2024-0917",
        "content_type": "application/json",
        "body": {"code": 0, "data": {"amount": 1200.0, "remark": "急单"}},
    }
    menu = {
        "url": "https://portal.example.com/api/menu",
        "content_type": "application/json",
        "body": {"code": 0, "data": {"menuName": "订单管理", "permission": "order:view"}},
    }
    me = {
        "url": "https://portal.example.com/api/me",
        "content_type": "application/json",
        "body": {"data": {"userName": "operator", "roleName": "财务"}, "traceId": "abc"},
    }
    adapter = FakeBrowserAdapter(
        {
            "snapshot": [_detail_snapshot()],
            "network": [CommandResult(ok=True, operation="network", data=[record, menu, me])],
        }
    )
    caps = BrowserCapabilities(snapshot=True, network=True)

    report = asyncio.run(UrlProber().probe(adapter, SAMPLE_URL, capabilities=caps))

    names = {item.name for item in report.fields}
    assert "remark" in names  # from the response that carries the order number
    assert not names & {"menu_name", "permission", "user_name", "role_name", "trace_id"}
    assert report.network_exchanges == 3  # counted, just not mined for fields


def test_probe_without_url_variable_keeps_every_response() -> None:
    body = {"data": {"menuName": "订单管理"}}
    exchange = {
        "url": "https://x.example/api/menu",
        "content_type": "application/json",
        "body": body,
    }
    snapshot = _detail_snapshot(url="https://x.example/detail", elements=[])
    adapter = FakeBrowserAdapter(
        {
            "snapshot": [snapshot],
            "network": [CommandResult(ok=True, operation="network", data=[exchange])],
        }
    )
    caps = BrowserCapabilities(snapshot=True, network=True)

    report = asyncio.run(UrlProber().probe(adapter, "https://x.example/detail", capabilities=caps))

    menu = next(item for item in report.fields if item.name == "menu_name")
    assert menu.recommended is False


def test_probe_without_network_capability_warns_and_uses_text() -> None:
    adapter = FakeBrowserAdapter({"snapshot": [_detail_snapshot()]})

    report = asyncio.run(
        UrlProber().probe(adapter, SAMPLE_URL, capabilities=BrowserCapabilities(snapshot=True))
    )

    assert any("网络响应" in warning for warning in report.warnings)
    assert {item.source for item in report.fields} == {"url", "dom"}
    assert not any(call[0] == "network_requests" for call in adapter.calls)


def test_probe_on_login_page_returns_auth_hint_without_candidates() -> None:
    adapter = FakeBrowserAdapter(
        {
            "snapshot": [
                BrowserSnapshot(
                    url="https://portal.example.com/login", text="用户名 密码 登录", title="登录"
                )
            ]
        }
    )

    report = asyncio.run(
        UrlProber().probe(adapter, SAMPLE_URL, capabilities=BrowserCapabilities(snapshot=True))
    )

    assert report.auth_state == AuthState.UNAUTHENTICATED
    assert report.fields == []
    assert report.attachments == []
    assert any("登录" in warning for warning in report.warnings)
    # the URL analysis still tells the wizard which variable to expect after login
    assert report.url_analysis.variables[0].name == "order_no"


def test_probe_open_failure_is_page_not_found() -> None:
    adapter = FakeBrowserAdapter(
        {"open_result": [CommandResult(ok=False, operation="open", safe_stderr="timeout")]}
    )

    with pytest.raises(SkillError) as raised:
        asyncio.run(
            UrlProber().probe(adapter, SAMPLE_URL, capabilities=BrowserCapabilities(snapshot=True))
        )

    assert raised.value.code.value == "E_PAGE_NOT_FOUND"
