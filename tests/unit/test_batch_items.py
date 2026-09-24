from __future__ import annotations

from copy import deepcopy
from typing import Any

from browser_skill.models import (
    BatchItemStatus,
    BrowserSnapshot,
    BrowserTemplate,
    DownloadedFile,
    DownloadStatus,
)
from browser_skill.runtime.batch import classify_item, extract_item_records


def _template(template_data: dict[str, Any], **run_overrides: Any) -> BrowserTemplate:
    data = deepcopy(template_data)
    data["system"]["url_template"] = "https://example.internal/orders/{order_no}"
    data["variables"] = {
        "order_no": {"type": "string", "required": True, "multiple": True, "prompt": "订单号"}
    }
    data["run"] = {"mode": "detail_batch", "driver_variable": "order_no", **run_overrides}
    data["target"]["record_key"] = ["order_no"]
    data["target"]["fields"] = [
        {
            "key": "order_no",
            "name": "订单号",
            "type": "string",
            "required": True,
            "semantic": ["订单号"],
        },
        {
            "key": "customer",
            "name": "客户",
            "type": "string",
            "required": True,
            "semantic": ["客户"],
        },
        {"key": "line", "name": "行项", "type": "string", "required": False, "semantic": ["行项"]},
    ]
    data["workflow"]["hints"] = []
    data["output"]["columns"] = []
    return BrowserTemplate.model_validate(data)


def test_single_page_record_is_stamped_with_driver_value(template_data: dict[str, Any]) -> None:
    template = _template(template_data)
    snapshot = BrowserSnapshot(elements=[{"label": "客户", "value": "ACME"}])

    records = extract_item_records(template, "order_no", "ORD-0001", snapshot)

    assert records == [{"customer": "ACME", "order_no": "ORD-0001"}]


def test_capture_tables_turns_each_row_into_a_record(template_data: dict[str, Any]) -> None:
    template = _template(template_data, capture_tables=True)
    snapshot = BrowserSnapshot(
        elements=[{"label": "客户", "value": "ACME"}],
        records=[{"line": "1", "ignored": "x"}, {"line": "2"}],
    )

    records = extract_item_records(template, "order_no", "ORD-0001", snapshot)

    assert records == [
        {"customer": "ACME", "line": "1", "order_no": "ORD-0001"},
        {"customer": "ACME", "line": "2", "order_no": "ORD-0001"},
    ]


def test_capture_tables_without_rows_falls_back_to_single_record(
    template_data: dict[str, Any],
) -> None:
    template = _template(template_data, capture_tables=True)
    snapshot = BrowserSnapshot(records=[{"order_no": "ORD-0002", "customer": "B"}])

    records = extract_item_records(template, "order_no", "ORD-0002", snapshot)

    assert records == [{"order_no": "ORD-0002", "customer": "B"}]


def test_classify_required_field_gap_fails_item(template_data: dict[str, Any]) -> None:
    template = _template(template_data)

    outcome = classify_item(template, [{"order_no": "ORD-0001"}], [])

    assert outcome.status == BatchItemStatus.FAILED
    assert outcome.reason == "required_field_missing:customer"
    assert outcome.records == []


def test_classify_required_attachment_failure_fails_item(template_data: dict[str, Any]) -> None:
    template = _template(template_data)
    template.target.attachments[0].required = True
    record = {"order_no": "ORD-0001", "customer": "ACME"}
    files = [
        DownloadedFile(
            record_key="ORD-0001",
            attachment_key="inventory_evidence",
            relative_path="",
            status=DownloadStatus.MISSING,
        )
    ]

    outcome = classify_item(template, [record], files)

    assert outcome.status == BatchItemStatus.FAILED
    assert outcome.reason == "required_attachment_missing:inventory_evidence"


def test_classify_optional_attachment_failure_is_partial(template_data: dict[str, Any]) -> None:
    template = _template(template_data)
    record = {"order_no": "ORD-0001", "customer": "ACME"}
    files = [
        DownloadedFile(
            record_key="ORD-0001",
            attachment_key="inventory_evidence",
            relative_path="",
            status=DownloadStatus.FAILED,
        )
    ]

    outcome = classify_item(template, [record], files)

    assert outcome.status == BatchItemStatus.PARTIAL
    assert outcome.reason == "attachment_missing"
    assert outcome.records == [record]
    assert outcome.files == files


def test_classify_dropped_rows_is_partial(template_data: dict[str, Any]) -> None:
    template = _template(template_data, capture_tables=True)
    good = {"order_no": "ORD-0001", "customer": "ACME", "line": "1"}
    bad = {"order_no": "ORD-0001", "line": "2"}

    outcome = classify_item(template, [good, bad], [])

    assert outcome.status == BatchItemStatus.PARTIAL
    assert outcome.reason == "rows_dropped:1"
    assert outcome.records == [good]


def test_classify_clean_item_is_ok(template_data: dict[str, Any]) -> None:
    template = _template(template_data)
    record = {"order_no": "ORD-0001", "customer": "ACME"}
    files = [
        DownloadedFile(
            record_key="ORD-0001",
            attachment_key="inventory_evidence",
            relative_path="attachments/evidence/ORD-0001_a.pdf",
            size=10,
            status=DownloadStatus.OK,
        )
    ]

    outcome = classify_item(template, [record], files)

    assert outcome.status == BatchItemStatus.OK
    assert outcome.reason is None
