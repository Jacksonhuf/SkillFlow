"""Wizard flow: probe one URL → tick candidates → create draft → batch test-run."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from browser_skill.app import BrowserSkillApp
from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.models import (
    BrowserCapabilities,
    BrowserSnapshot,
    CommandResult,
    RunState,
    SkillRequest,
)
from browser_skill.templates.store import TemplateStore

SAMPLE_URL = "https://portal.example.com/orders/ORD-0001/detail?tab=files"
CAPS = BrowserCapabilities(
    snapshot=True, find=True, download=True, downloads=True, tabs=True, network=True
)


def _detail(order_no: str, customer: str, amount: str) -> BrowserSnapshot:
    return BrowserSnapshot(
        url=f"https://portal.example.com/orders/{order_no}/detail?tab=files",
        title="订单详情",
        text=f"退出登录\n订单号：{order_no}\n客户名称：{customer}\n金额：{amount}\n",
        elements=[
            {"ref": f"@c-{order_no}", "role": "link", "text": "合同.pdf", "href": "/f/c.pdf"},
            {"ref": f"@i1-{order_no}", "role": "link", "text": "发票_1.pdf", "href": "/f/i1.pdf"},
            {"ref": f"@i2-{order_no}", "role": "link", "text": "发票_2.pdf", "href": "/f/i2.pdf"},
        ],
    )


def _api(order_no: str, customer: str, amount: float) -> CommandResult:
    return CommandResult(
        ok=True,
        operation="network",
        data=[
            {
                "url": f"https://portal.example.com/api/orders/{order_no}",
                "content_type": "application/json",
                "body": {"data": {"orderNo": order_no, "customerName": customer, "amount": amount}},
            }
        ],
    )


def test_probe_create_and_batch_run(tmp_path: Path) -> None:
    adapter = FakeBrowserAdapter(
        {
            "capabilities": [CAPS] * 4,
            "snapshot": [
                _detail("ORD-0001", "张三贸易", "1200.00"),  # probe
                _detail("ORD-0001", "张三贸易", "1200.00"),  # run: entry auth check
                _detail("ORD-0001", "张三贸易", "1200.00"),  # item 1
                # item 2: page text lacks the amount → comes from the network response
                BrowserSnapshot(
                    url="https://portal.example.com/orders/ORD-0002/detail?tab=files",
                    text="退出登录\n订单号：ORD-0002\n客户名称：李四公司\n",
                    elements=[{"ref": "@c2", "role": "link", "text": "合同.pdf"}],
                ),
            ],
            "network": [
                _api("ORD-0001", "张三贸易", 1200.0),
                _api("ORD-0001", "张三贸易", 1200.0),
                _api("ORD-0002", "李四公司", 88.5),
            ],
        }
    )
    templates_root = tmp_path / "templates"
    app = BrowserSkillApp(templates_root, tmp_path / "runs", adapter)

    probed = asyncio.run(app.handle(SkillRequest(action="probe_url", url=SAMPLE_URL)))

    assert probed.ok is True, probed.message
    probe = probed.data["probe"]
    assert probe["url_analysis"]["template_suggestion"] == (
        "https://portal.example.com/orders/{order_no}/detail?tab=files"
    )
    assert probed.data["interaction"]["actions"][0] == "create_from_probe"
    by_key = {item["key"]: item for item in probe["fields"]}
    assert by_key["order_no"]["source"] == "url"
    assert by_key["customer_name"]["source"] == "network"
    assert by_key["amount"]["source"] == "network"
    attachments = {item["name"]: item for item in probe["attachments"]}
    assert attachments["合同"]["count"] == 1
    assert attachments["发票"]["count"] == 2

    # The wizard: user keeps order_no / customer_name / amount and both attachments
    created = asyncio.run(
        app.handle(
            SkillRequest(
                action="create_from_probe",
                probe_draft={
                    "template_id": "order_files",
                    "name": "订单附件",
                    "sample_url": SAMPLE_URL,
                    "url_template": probe["url_analysis"]["template_suggestion"],
                    "driver_variable": "order_no",
                    "fields": [by_key["order_no"], by_key["customer_name"], by_key["amount"]],
                    "attachments": probe["attachments"],
                    "required_keys": ["customer_name"],
                    "run": {"per_item_delay_ms": 0},
                },
            )
        )
    )

    assert created.ok is True, created.message
    assert created.data["version"] == 1
    assert created.data["url_template"].endswith("/orders/{order_no}/detail?tab=files")
    template = TemplateStore(templates_root).load("order_files", 1, require_published=False)
    assert template.run.driver_variable == "order_no"
    assert template.learned.field_mappings["amount"].endpoint_hint == "/api/orders/{order_no}"

    tested = asyncio.run(
        app.handle(
            SkillRequest(
                action="test",
                template_id="order_files",
                variables={"order_no": "ORD-0001\nORD-0002"},
            )
        )
    )

    assert tested.ok is True, tested.message
    # item 2 has no invoice link: optional attachment missing → partial, not failed
    assert tested.state == RunState.PARTIAL
    assert tested.data["items"]["ok"] == 1
    assert tested.data["items"]["partial"] == 1
    assert tested.data["items"]["failed"] == 0
    run_dir = tmp_path / "runs" / str(tested.run_id)
    result = json.loads((run_dir / "order_files.json").read_text(encoding="utf-8"))
    records = {item["order_no"]: item for item in result["records"]}
    assert records["ORD-0001"]["customer_name"] == "张三贸易"
    assert records["ORD-0001"]["amount"] == 1200.0  # network beats page text
    assert records["ORD-0002"]["customer_name"] == "李四公司"
    assert records["ORD-0002"]["amount"] == 88.5
    names = sorted(path.name for path in (run_dir / "attachments" / "contract").iterdir())
    assert names == ["ORD-0001_合同.pdf", "ORD-0002_合同.pdf"]
    assert template.target.attachments[1].multiple is True
    invoices = sorted(path.name for path in (run_dir / "attachments" / "invoice").iterdir())
    assert invoices == ["ORD-0001_发票_1.pdf", "ORD-0001_发票_2.pdf"]


def test_probe_url_requires_url_and_reports_login_page(tmp_path: Path) -> None:
    adapter = FakeBrowserAdapter(
        {
            "snapshot": [
                BrowserSnapshot(url="https://portal.example.com/login", text="用户名 密码 登录")
            ]
        }
    )
    app = BrowserSkillApp(tmp_path / "templates", tmp_path / "runs", adapter)

    missing = asyncio.run(app.handle(SkillRequest(action="probe_url")))
    assert missing.ok is False

    response = asyncio.run(app.handle(SkillRequest(action="probe_url", url=SAMPLE_URL)))

    assert response.ok is False
    assert "登录" in response.message
    assert response.data["probe"]["auth_state"] == "unauthenticated"
    assert response.data["interaction"]["actions"] == ["retry_probe_url", "cancel_template"]
