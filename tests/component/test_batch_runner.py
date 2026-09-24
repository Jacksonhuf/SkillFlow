from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.models import BrowserSnapshot, BrowserTemplate, CommandResult, RunState
from browser_skill.runtime.runner import Runner

HOME = BrowserSnapshot(url="https://example.internal/home", text="退出登录 订单中心")
LOGIN = BrowserSnapshot(url="https://example.internal/login", text="用户名 登录")


def _batch_template(template_data: dict[str, Any], **run_overrides: Any) -> BrowserTemplate:
    data = deepcopy(template_data)
    data["schema_version"] = "2.0"
    data["system"]["url_template"] = "https://example.internal/orders/{order_no}"
    data["variables"] = {
        "order_no": {
            "type": "string",
            "required": True,
            "multiple": True,
            "prompt": "订单号",
            "validation": {"regex": r"ORD-\d{4}"},
        }
    }
    data["run"] = {
        "mode": "detail_batch",
        "driver_variable": "order_no",
        "per_item_delay_ms": 0,
        **run_overrides,
    }
    data["target"]["record_key"] = ["order_no"]
    data["target"]["fields"] = [
        {
            "key": "order_no",
            "name": "订单号",
            "type": "string",
            "required": True,
            "semantic": ["订单号"],
            "source": "detail",
        },
        {
            "key": "customer",
            "name": "客户",
            "type": "string",
            "required": True,
            "semantic": ["客户"],
            "source": "detail",
        },
        {
            "key": "amount",
            "name": "金额",
            "type": "string",
            "required": False,
            "semantic": ["金额"],
            "source": "detail",
        },
    ]
    data["target"]["attachments"][0]["filename_pattern"] = "{order_no}_{original_name}"
    data["workflow"]["hints"] = []
    data["output"]["columns"] = ["order_no", "customer", "amount"]
    data["output"]["filename_pattern"] = "orders"
    return BrowserTemplate.model_validate(data)


def _detail(
    order_no: str, *, customer: str | None = "ACME", attachment: bool = True
) -> BrowserSnapshot:
    record: dict[str, Any] = {"order_no": order_no, "amount": "100"}
    if customer is not None:
        record["customer"] = customer
    elements = []
    if attachment:
        elements.append({"text": "凭证附件", "ref": f"@dl-{order_no}", "filename": "invoice.pdf"})
    return BrowserSnapshot(
        url=f"https://example.internal/orders/{order_no}",
        text=f"订单详情 {order_no}",
        records=[record],
        elements=elements,
    )


def _opened_urls(adapter: FakeBrowserAdapter) -> list[str]:
    return [call[1][0] for call in adapter.calls if call[0] == "open"]


def test_batch_run_visits_every_value_and_downloads_named_attachments(
    tmp_path: Path, template_data: dict[str, Any]
) -> None:
    template = _batch_template(template_data)
    adapter = FakeBrowserAdapter(
        {"snapshot": [HOME, _detail("ORD-0001"), _detail("ORD-0002"), _detail("ORD-0003")]}
    )

    response = asyncio.run(
        Runner(adapter, tmp_path).run(template, {"order_no": "ORD-0001\nORD-0002, ORD-0003"})
    )

    assert response.ok is True
    assert response.state == RunState.COMPLETED
    assert response.data["items"] == {
        "total": 3,
        "pending": 0,
        "ok": 3,
        "partial": 0,
        "failed": 0,
        "failed_values": [],
    }
    assert _opened_urls(adapter) == [
        "https://example.internal/orders/ORD-0001",
        "https://example.internal/orders/ORD-0002",
        "https://example.internal/orders/ORD-0003",
    ]
    workspace = tmp_path / str(response.run_id)
    result = json.loads((workspace / "orders.json").read_text(encoding="utf-8"))
    assert [item["order_no"] for item in result["records"]] == ["ORD-0001", "ORD-0002", "ORD-0003"]
    assert [item["customer"] for item in result["records"]] == ["ACME"] * 3
    files = sorted(path.name for path in (workspace / "attachments" / "evidence").iterdir())
    assert files == ["ORD-0001_invoice.pdf", "ORD-0002_invoice.pdf", "ORD-0003_invoice.pdf"]
    batch = json.loads((workspace / "batch.json").read_text(encoding="utf-8"))
    assert batch["driver_variable"] == "order_no"
    assert [item["status"] for item in batch["items"]] == ["ok", "ok", "ok"]
    assert batch["stats"]["ok"] == 3
    summary = json.loads((workspace / "summary.json").read_text(encoding="utf-8"))
    assert summary["items"]["total"] == 3
    events = [
        json.loads(line)["event"]
        for line in (workspace / "execution.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events.count("item_started") == 3
    assert events.count("item_finished") == 3
    assert "batch_finished" in events


def test_failed_item_yields_partial_run_with_failed_values(
    tmp_path: Path, template_data: dict[str, Any]
) -> None:
    template = _batch_template(template_data)
    adapter = FakeBrowserAdapter(
        {
            "snapshot": [HOME, _detail("ORD-0001"), _detail("ORD-0003")],
            "open_result": [
                CommandResult(ok=True, operation="open"),
                CommandResult(ok=False, operation="open", safe_stderr="404"),
                CommandResult(ok=True, operation="open"),
            ],
        }
    )

    response = asyncio.run(
        Runner(adapter, tmp_path).run(template, {"order_no": ["ORD-0001", "ORD-0002", "ORD-0003"]})
    )

    assert response.ok is True
    assert response.state == RunState.PARTIAL
    assert response.data["items"]["failed_values"] == ["ORD-0002"]
    assert response.data["items"]["ok"] == 2
    assert response.data["validation"]["record_count"] == 2
    batch = json.loads((tmp_path / str(response.run_id) / "batch.json").read_text("utf-8"))
    failed = batch["items"][1]
    assert failed["status"] == "failed"
    assert failed["reason"] == "E_PAGE_NOT_FOUND"
    assert failed["error"]["code"] == "E_PAGE_NOT_FOUND"


def test_missing_required_field_fails_item_but_keeps_others(
    tmp_path: Path, template_data: dict[str, Any]
) -> None:
    template = _batch_template(template_data)
    adapter = FakeBrowserAdapter(
        {"snapshot": [HOME, _detail("ORD-0001", customer=None), _detail("ORD-0002")]}
    )

    response = asyncio.run(
        Runner(adapter, tmp_path).run(template, {"order_no": ["ORD-0001", "ORD-0002"]})
    )

    assert response.state == RunState.PARTIAL
    items = response.data["items"]
    assert items["failed_values"] == ["ORD-0001"]
    batch = json.loads((tmp_path / str(response.run_id) / "batch.json").read_text("utf-8"))
    assert batch["items"][0]["reason"] == "required_field_missing:customer"


def test_optional_attachment_missing_marks_item_partial(
    tmp_path: Path, template_data: dict[str, Any]
) -> None:
    template = _batch_template(template_data)
    adapter = FakeBrowserAdapter(
        {"snapshot": [HOME, _detail("ORD-0001", attachment=False), _detail("ORD-0002")]}
    )

    response = asyncio.run(
        Runner(adapter, tmp_path).run(template, {"order_no": ["ORD-0001", "ORD-0002"]})
    )

    assert response.state == RunState.PARTIAL
    assert response.data["items"]["partial"] == 1
    assert response.data["items"]["failed_values"] == []
    assert response.data["validation"]["record_count"] == 2


def test_on_item_error_stop_fails_run_at_first_failure(
    tmp_path: Path, template_data: dict[str, Any]
) -> None:
    template = _batch_template(template_data, on_item_error="stop")
    adapter = FakeBrowserAdapter(
        {
            "snapshot": [HOME, _detail("ORD-0001")],
            "open_result": [
                CommandResult(ok=True, operation="open"),
                CommandResult(ok=False, operation="open"),
            ],
        }
    )

    response = asyncio.run(
        Runner(adapter, tmp_path).run(template, {"order_no": ["ORD-0001", "ORD-0002", "ORD-0003"]})
    )

    assert response.state == RunState.FAILED
    assert response.data["error"]["code"] == "E_PAGE_NOT_FOUND"
    assert response.data["error"]["details"]["items"]["pending"] == 1
    assert len(_opened_urls(adapter)) == 2


def test_all_items_failing_is_a_failed_run(tmp_path: Path, template_data: dict[str, Any]) -> None:
    template = _batch_template(template_data)
    adapter = FakeBrowserAdapter(
        {
            "snapshot": [HOME],
            "open_result": [CommandResult(ok=False, operation="open")] * 2,
        }
    )

    response = asyncio.run(
        Runner(adapter, tmp_path).run(template, {"order_no": ["ORD-0001", "ORD-0002"]})
    )

    assert response.state == RunState.FAILED
    assert response.data["error"]["code"] == "E_VALIDATION_FAILED"
    assert response.data["error"]["details"]["items"]["failed_values"] == ["ORD-0001", "ORD-0002"]


def test_session_expiry_pauses_and_resume_skips_completed_items(
    tmp_path: Path, template_data: dict[str, Any]
) -> None:
    template = _batch_template(template_data)
    adapter = FakeBrowserAdapter(
        {
            "snapshot": [
                HOME,
                _detail("ORD-0001"),
                LOGIN,  # second detail page redirected to login
                HOME,  # resume: auth check
                _detail("ORD-0002"),
                _detail("ORD-0003"),
            ]
        }
    )
    runner = Runner(adapter, tmp_path)

    paused = asyncio.run(runner.run(template, {"order_no": ["ORD-0001", "ORD-0002", "ORD-0003"]}))

    assert paused.ok is False
    assert paused.state == RunState.WAIT_USER_AUTH
    assert paused.data["items"] == {
        "total": 3,
        "pending": 2,
        "ok": 1,
        "partial": 0,
        "failed": 0,
        "failed_values": [],
    }
    workspace = tmp_path / str(paused.run_id)
    batch = json.loads((workspace / "batch.json").read_text("utf-8"))
    assert [item["status"] for item in batch["items"]] == ["ok", "pending", "pending"]

    opened_before = len(_opened_urls(adapter))
    resumed = asyncio.run(runner.resume(workspace))

    assert resumed.ok is True
    assert resumed.state == RunState.COMPLETED
    assert resumed.data["items"]["ok"] == 3
    assert _opened_urls(adapter)[opened_before:] == [
        "https://example.internal/orders/ORD-0002",
        "https://example.internal/orders/ORD-0003",
    ]
    result = json.loads((workspace / "orders.json").read_text(encoding="utf-8"))
    assert [item["order_no"] for item in result["records"]] == ["ORD-0001", "ORD-0002", "ORD-0003"]
    assert len(result["attachments"]) == 3


def test_full_url_values_are_opened_directly(tmp_path: Path, template_data: dict[str, Any]) -> None:
    template = _batch_template(template_data)
    adapter = FakeBrowserAdapter({"snapshot": [HOME, _detail("ORD-0009")]})

    response = asyncio.run(
        Runner(adapter, tmp_path).run(
            template, {"order_no": "https://example.internal/orders/ORD-0009?tab=files"}
        )
    )

    assert response.state == RunState.COMPLETED
    assert _opened_urls(adapter) == ["https://example.internal/orders/ORD-0009?tab=files"]
    result = json.loads((tmp_path / str(response.run_id) / "orders.json").read_text("utf-8"))
    # the page's own order number wins over the URL that drove the visit
    assert result["records"][0]["order_no"] == "ORD-0009"


def test_redirect_outside_allowed_hosts_fails_only_that_item(
    tmp_path: Path, template_data: dict[str, Any]
) -> None:
    template = _batch_template(template_data)
    adapter = FakeBrowserAdapter(
        {
            "snapshot": [
                HOME,
                BrowserSnapshot(url="https://evil.example/phishing", text="订单"),
                _detail("ORD-0002"),
            ]
        }
    )

    response = asyncio.run(
        Runner(adapter, tmp_path).run(template, {"order_no": ["ORD-0001", "ORD-0002"]})
    )

    assert response.state == RunState.PARTIAL
    assert response.data["items"]["failed_values"] == ["ORD-0001"]
    batch = json.loads((tmp_path / str(response.run_id) / "batch.json").read_text("utf-8"))
    assert batch["items"][0]["reason"] == "E_ACTION_NOT_ALLOWED"
