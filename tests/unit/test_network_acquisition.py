from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from browser_skill.acquire.network import (
    NetworkDiscovery,
    NetworkExtractor,
    parse_exchanges,
    resolve_path,
    split_field_path,
)
from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.models import (
    AcquisitionSource,
    BrowserCapabilities,
    BrowserSnapshot,
    BrowserTemplate,
    CommandResult,
    LearnedMapping,
    RunState,
    SourcePage,
)
from browser_skill.runtime.runner import Runner

_API_BODY: dict[str, Any] = {
    "code": 0,
    "data": {
        "total": 2,
        "list": [
            {"sampleId": "S-1", "sn": "SN-1", "productModel": "P100", "owner": "张三"},
            {"sampleId": "S-2", "sn": "SN-2", "productModel": "P200", "owner": "李四"},
        ],
    },
}


def _exchanges_raw() -> list[dict[str, Any]]:
    return [
        {"url": "https://example.internal/static/app.js", "mimeType": "text/javascript"},
        {
            "url": "https://cdn.other.com/api/inventory/list",
            "content_type": "application/json",
            "body": _API_BODY,
        },
        {
            "url": "https://example.internal/api/inventory/list?date=2026-09-01",
            "method": "POST",
            "status": 200,
            "response": {"mimeType": "application/json", "body": json.dumps(_API_BODY)},
        },
    ]


def _template(
    template_data: dict[str, Any], learned: dict[str, Any] | None = None
) -> BrowserTemplate:
    data = deepcopy(template_data)
    data["target"]["attachments"] = []
    data["workflow"]["hints"] = []
    data["validation"]["min_records"] = 1
    if learned is not None:
        data["learned"] = learned
    return BrowserTemplate.model_validate(data)


def test_parse_exchanges_normalizes_loose_shapes() -> None:
    exchanges = parse_exchanges({"requests": _exchanges_raw()})
    assert len(exchanges) == 3
    json_ones = [item for item in exchanges if item.is_json]
    assert {item.url.split("?")[0] for item in json_ones} == {
        "https://cdn.other.com/api/inventory/list",
        "https://example.internal/api/inventory/list",
    }
    assert json_ones[1].body["data"]["total"] == 2
    assert json_ones[1].method == "POST"


def test_path_helpers() -> None:
    assert resolve_path(_API_BODY, "$.data.list[*]")[0]["sn"] == "SN-1"
    assert resolve_path(_API_BODY, "$.missing[*]") == []
    assert split_field_path("$.data.list[*].orderNo") == ("$.data.list[*]", "orderNo")


def test_discovery_learns_allowed_host_endpoint_and_maps_camel_case(template_data) -> None:
    template = _template(template_data)
    result = NetworkDiscovery().discover(template, parse_exchanges(_exchanges_raw()))
    assert result.endpoint == "/api/inventory/list"
    assert result.array_path == "$.data.list[*]"
    assert result.matched_fields == ["product_model", "sample_id", "sn"]
    mapping = result.mappings["sample_id"]
    assert mapping.preferred_source == AcquisitionSource.NETWORK
    assert mapping.json_path == "$.data.list[*].sampleId"
    assert mapping.hints == ["sampleId"]
    # the cdn.other.com response is ignored even though identical
    assert result.exchanges_considered == 1


def test_discovery_requires_required_fields(template_data) -> None:
    template = _template(template_data)
    body = {"rows": [{"productModel": "P100"}]}
    exchanges = parse_exchanges([{"url": "https://example.internal/api/x", "body": body}])
    assert NetworkDiscovery().discover(template, exchanges).mappings == {}


def _learned_network() -> dict[str, Any]:
    def mapping(key: str) -> dict[str, Any]:
        return LearnedMapping(
            page=SourcePage.LIST,
            strategy="semantic",
            hints=[key],
            confidence=0.9,
            preferred_source=AcquisitionSource.NETWORK,
            endpoint_hint="/api/inventory/list",
            json_path=f"$.data.list[*].{key}",
        ).model_dump(mode="json")

    return {
        "page_hints": [],
        "field_mappings": {
            "sample_id": mapping("sampleId"),
            "sn": mapping("sn"),
            "product_model": mapping("productModel"),
        },
        "attachment_mappings": {},
    }


def test_extractor_reads_learned_endpoint(template_data) -> None:
    template = _template(template_data, _learned_network())
    records = NetworkExtractor().extract(template, parse_exchanges(_exchanges_raw()))
    assert records == [
        {"sample_id": "S-1", "sn": "SN-1", "product_model": "P100"},
        {"sample_id": "S-2", "sn": "SN-2", "product_model": "P200"},
    ]


def test_extractor_returns_none_without_matching_exchange(template_data) -> None:
    template = _template(template_data, _learned_network())
    other = parse_exchanges([{"url": "https://example.internal/api/other", "body": _API_BODY}])
    assert NetworkExtractor().extract(template, other) is None
    assert NetworkExtractor().extract(_template(template_data), []) is None


def _adapter(network: list[Any] | None, *, capability: bool = True) -> FakeBrowserAdapter:
    script: dict[str, list[Any]] = {
        "snapshot": [
            BrowserSnapshot(
                url="https://example.internal/home",
                text="退出登录 样机盘点反馈",
                records=[{"sample_id": "DOM-1", "sn": "DOM-SN", "product_model": "DOM"}],
            )
        ],
        "capabilities": [
            BrowserCapabilities(
                snapshot=True,
                find=True,
                download=True,
                downloads=True,
                tabs=True,
                network=capability,
            )
        ],
    }
    if network is not None:
        script["network"] = network
    return FakeBrowserAdapter(script)


def test_runner_prefers_learned_network_source(tmp_path: Path, template_data) -> None:
    template = _template(template_data, _learned_network())
    adapter = _adapter([CommandResult(ok=True, operation="network", data=_exchanges_raw())])
    response = asyncio.run(Runner(adapter, tmp_path).run(template, {}))
    assert response.ok and response.state == RunState.COMPLETED
    run = json.loads((tmp_path / str(response.run_id) / "run.json").read_text(encoding="utf-8"))
    assert [record["sn"] for record in run["records"]] == ["SN-1", "SN-2"]
    events = (tmp_path / str(response.run_id) / "execution.jsonl").read_text(encoding="utf-8")
    assert '"event": "network_extraction"' in events
    assert ("network_requests", (), {}) in adapter.calls


def test_runner_falls_back_to_dom_when_network_has_no_match(tmp_path: Path, template_data) -> None:
    template = _template(template_data, _learned_network())
    adapter = _adapter([CommandResult(ok=True, operation="network", data=[])])
    response = asyncio.run(Runner(adapter, tmp_path).run(template, {}))
    assert response.ok
    run = json.loads((tmp_path / str(response.run_id) / "run.json").read_text(encoding="utf-8"))
    assert run["records"][0]["sn"] == "DOM-SN"
    events = (tmp_path / str(response.run_id) / "execution.jsonl").read_text(encoding="utf-8")
    assert "network_extraction_fallback" in events


def test_runner_skips_network_without_capability(tmp_path: Path, template_data) -> None:
    template = _template(template_data, _learned_network())
    adapter = _adapter(None, capability=False)
    response = asyncio.run(Runner(adapter, tmp_path).run(template, {}))
    assert response.ok
    assert ("network_requests", (), {}) not in adapter.calls
