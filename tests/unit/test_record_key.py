from copy import deepcopy
from typing import Any

from browser_skill.models import BrowserTemplate
from browser_skill.runtime.record_key import record_key_for
from browser_skill.runtime.validator import ResultValidator


def test_record_key_fills_driver_when_business_key_empty(template_data: dict[str, Any]) -> None:
    data = deepcopy(template_data)
    data["run"] = {
        "mode": "detail_batch",
        "driver_variable": "order_no",
    }
    data["target"]["record_key"] = ["sn"]
    data["variables"] = {
        "order_no": {"type": "string", "required": True, "multiple": True, "prompt": "订单号"}
    }
    template = BrowserTemplate.model_validate(data)
    record = {"sample_id": "S1", "sn": "", "order_no": "ORD-0001"}
    assert record_key_for(template, record) == "ORD-0001"


def test_record_key_unique_across_pages_with_same_row_no(template_data: dict[str, Any]) -> None:
    data = deepcopy(template_data)
    data["run"] = {
        "mode": "detail_batch",
        "driver_variable": "page_url",
        "capture_tables": True,
    }
    data["target"]["fields"].append(
        {"key": "page_url", "name": "详情页", "type": "string", "required": True, "semantic": ["url"]}
    )
    data["target"]["fields"].append(
        {"key": "row_no", "name": "行号", "type": "integer", "required": True, "semantic": ["行号"]}
    )
    data["target"]["record_key"] = ["row_no", "page_url"]
    data["variables"] = {
        "page_url": {"type": "string", "required": True, "multiple": True, "prompt": "详情页"}
    }
    template = BrowserTemplate.model_validate(data)
    first = {"sample_id": "S1", "sn": "SN1", "row_no": "1", "page_url": "https://host/a"}
    second = {"sample_id": "S2", "sn": "SN2", "row_no": "1", "page_url": "https://host/b"}
    assert record_key_for(template, first) != record_key_for(template, second)


def test_duplicate_without_driver_still_fails(template) -> None:
    records = [
        {"sample_id": "S1", "sn": "same"},
        {"sample_id": "S2", "sn": "same"},
    ]
    report = ResultValidator().validate(template, records, [], pagination_complete=True)
    assert not report.ok
    assert any(issue.code == "record_key" for issue in report.issues)
