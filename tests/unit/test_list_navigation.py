from __future__ import annotations

import json
from typing import Any

from browser_skill.models import BrowserSnapshot, BrowserTemplate, RunMode
from browser_skill.runtime.list_navigation import (
    detail_link_target,
    list_navigation_active,
    reconcile_list_nav_steps_with_snapshot,
    ref_for_label_on_snapshot,
    snapshot_has_ref,
)
from browser_skill.runtime.url_batch import plan_batch_items


def _batch_template(template_data: dict[str, Any], **run: Any) -> BrowserTemplate:
    data = json.loads(json.dumps(template_data))
    data["schema_version"] = "2.0"
    data["system"]["url_template"] = None
    data["variables"] = {
        "order_no": {
            "type": "string",
            "required": True,
            "multiple": True,
            "prompt": "订单号",
        }
    }
    data["run"] = {
        "mode": "detail_batch",
        "driver_variable": "order_no",
        "accept_full_urls": True,
        "list_navigation": {"enabled": True, "list_url": "https://example.internal/orders"},
        **run,
    }
    data["target"]["fields"].append(
        {
            "key": "order_no",
            "name": "订单号",
            "type": "string",
            "required": True,
            "semantic": ["订单号"],
            "source": "detail",
        }
    )
    data["target"]["record_key"] = ["order_no"]
    return BrowserTemplate.model_validate(data)


def test_list_navigation_active_skips_full_urls(template_data: dict[str, Any]) -> None:
    template = _batch_template(template_data)
    assert list_navigation_active(template, "ORD-1") is True
    assert list_navigation_active(template, "https://example.internal/x") is False


def test_plan_batch_uses_list_url_for_business_ids(template_data: dict[str, Any]) -> None:
    template = _batch_template(template_data)
    items = plan_batch_items(template, {}, ["ORD-1", "https://example.internal/direct"])
    assert items[0].url == "https://example.internal/orders"
    assert items[1].url == "https://example.internal/direct"


def test_snapshot_has_ref() -> None:
    snapshot = BrowserSnapshot(elements=[{"ref": "@e3", "text": "x"}])
    assert snapshot_has_ref(snapshot, "@e3") is True
    assert snapshot_has_ref(snapshot, "@e9") is False


def test_reconcile_list_nav_steps_updates_refs() -> None:
    steps = [
        {"kind": "input", "label": "订单号", "ref": "@e3"},
        {"kind": "action", "label": "查询", "ref": "@e4"},
    ]
    snapshot = BrowserSnapshot(
        elements=[
            {"ref": "@e10", "placeholder": "订单号"},
            {"ref": "@e11", "text": "查询"},
        ],
    )
    updated, count = reconcile_list_nav_steps_with_snapshot(steps, snapshot)
    assert count == 2
    assert updated[0]["ref"] == "@e10"
    assert updated[1]["ref"] == "@e11"


def test_ref_for_label_when_ref_number_changed() -> None:
    snapshot = BrowserSnapshot(
        elements=[{"ref": "@e12", "text": "订单号", "role": "textbox"}],
    )
    assert ref_for_label_on_snapshot(snapshot, "订单号") == "@e12"


def test_detail_link_target_prefers_link_with_driver_text() -> None:
    snapshot = BrowserSnapshot(
        elements=[
            {"ref": "@e1", "role": "link", "text": "ORD-9", "href": "/detail/9"},
            {"ref": "@e2", "role": "button", "text": "详情", "record_key": "ORD-9"},
        ]
    )
    assert detail_link_target(snapshot, "ORD-9", ["详情"]) == "@e1"


def test_template_allows_list_nav_without_url_template(template_data: dict[str, Any]) -> None:
    template = _batch_template(template_data, accept_full_urls=False)
    assert template.run.mode == RunMode.DETAIL_BATCH
    assert template.system.url_template is None
