from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
from typing import Any

from browser_skill.app import BrowserSkillApp
from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.models import (
    AcquisitionSource,
    BrowserCapabilities,
    BrowserSnapshot,
    BrowserTemplate,
    CommandResult,
    RunState,
    SkillRequest,
)
from browser_skill.templates.store import TemplateStore

_LIST_API = {
    "url": "https://example.internal/api/inventory/list?date=2026-09-01",
    "content_type": "application/json",
    "body": {
        "data": {
            "list": [
                {"sampleId": "S-1", "sn": "SN-1", "productModel": "P100"},
                {"sampleId": "S-2", "sn": "SN-2", "productModel": "P200"},
            ]
        }
    },
}

_CAPS = BrowserCapabilities(
    snapshot=True, find=True, download=True, downloads=True, tabs=True, network=True
)


def _home(records: list[dict[str, Any]] | None = None) -> BrowserSnapshot:
    return BrowserSnapshot(
        url="https://example.internal/home",
        title="盘点反馈",
        text="退出登录 样机盘点反馈",
        elements=[{"text": "样机ID"}, {"text": "SN"}, {"text": "产品型号"}, {"text": "凭证"}],
        records=records or [],
    )


def test_discover_learns_network_endpoint_and_run_uses_it(
    tmp_path: Path, template_data: dict[str, object]
) -> None:
    data = deepcopy(template_data)
    data["schema_version"] = "2.0"
    data["workflow"]["hints"] = []  # type: ignore[index]
    data["target"]["attachments"] = []  # type: ignore[index]
    templates_root = tmp_path / "templates"
    store = TemplateStore(templates_root)
    store.save(BrowserTemplate.model_validate(data))
    adapter = FakeBrowserAdapter(
        {
            "snapshot": [_home()],
            "capabilities": [_CAPS],
            "network": [CommandResult(ok=True, operation="network", data=[_LIST_API])],
        }
    )
    app = BrowserSkillApp(templates_root, tmp_path / "runs", adapter)

    response = asyncio.run(
        app.handle(SkillRequest(action="discover", template_id="inventory_feedback", version=1))
    )
    assert response.ok is True
    assert response.data["network"]["learned"] is True
    assert response.data["network"]["endpoint"] == "/api/inventory/list"
    assert response.data["candidate_version"] == 2

    candidate = store.load("inventory_feedback", 2, require_published=False)
    mapping = candidate.learned.field_mappings["sn"]
    assert mapping.preferred_source == AcquisitionSource.NETWORK
    assert mapping.json_path == "$.data.list[*].sn"
    # 2.0 keeps the business contract file free of learned internals
    business_yaml = (templates_root / "inventory_feedback" / "2.yaml").read_text(encoding="utf-8")
    assert "/api/inventory/list" not in business_yaml
    assert (templates_root / "inventory_feedback" / "learned" / "2.yaml").is_file()

    # The learned endpoint drives the next Test Run; DOM records are not needed.
    adapter.script["snapshot"].append(_home())
    adapter.script["capabilities"].append(_CAPS)
    adapter.script["network"].append(
        CommandResult(ok=True, operation="network", data=[_LIST_API])
    )
    tested = asyncio.run(
        app.handle(
            SkillRequest(action="test", template_id="inventory_feedback", variables={})
        )
    )
    assert tested.ok is True
    assert tested.state == RunState.COMPLETED
    assert tested.data["validation"]["record_count"] == 2


def test_discover_without_network_capability_reports_reason(
    tmp_path: Path, template_data: dict[str, object]
) -> None:
    templates_root = tmp_path / "templates"
    TemplateStore(templates_root).save(BrowserTemplate.model_validate(template_data))
    adapter = FakeBrowserAdapter({"snapshot": [_home()]})
    app = BrowserSkillApp(templates_root, tmp_path / "runs", adapter)
    response = asyncio.run(
        app.handle(SkillRequest(action="discover", template_id="inventory_feedback", version=1))
    )
    assert response.ok is True
    assert response.data["network"] == {"enabled": False, "reason": "network capture unsupported"}
    assert ("network_requests", (), {}) not in adapter.calls
