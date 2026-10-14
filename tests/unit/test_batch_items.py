from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from browser_skill.models import (
    BatchItemState,
    BatchItemStatus,
    BatchProgress,
    BrowserSnapshot,
    BrowserTemplate,
    DownloadedFile,
    DownloadStatus,
    TableData,
)
from browser_skill.runtime.batch import (
    apply_incremental_skip,
    classify_item,
    extract_item_records,
    previously_completed_values,
)


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


def test_dom_hint_pick_ref_reads_snapshot_element(template_data: dict[str, Any]) -> None:
    template = _template(template_data)
    data = template.model_dump(mode="json")
    data["target"]["fields"].append(
        {
            "key": "ref_e9",
            "name": "客户",
            "type": "string",
            "required": True,
            "semantic": ["客户"],
        }
    )
    data["learned"]["field_mappings"]["ref_e9"] = {
        "page": "detail",
        "strategy": "dom_hint",
        "hints": ["@e9"],
        "frame_index": 0,
        "confidence": 0.9,
    }
    template = BrowserTemplate.model_validate(data)
    snapshot = BrowserSnapshot(
        elements=[{"ref": "@e9", "text": "ACME Corp", "frame_index": 0}],
    )

    records = extract_item_records(template, "order_no", "ORD-0001", snapshot)

    assert records[0]["ref_e9"] == "ACME Corp"
    assert records[0]["order_no"] == "ORD-0001"


def test_dom_hint_pick_sample_fallback_when_ref_changes(template_data: dict[str, Any]) -> None:
    template = _template(template_data)
    data = template.model_dump(mode="json")
    data["target"]["fields"].append(
        {
            "key": "ref_e9",
            "name": "客户",
            "type": "string",
            "required": True,
            "semantic": ["客户"],
        }
    )
    data["learned"]["field_mappings"]["ref_e9"] = {
        "page": "detail",
        "strategy": "dom_hint",
        "hints": ["@e9"],
        "frame_index": 0,
        "pick_sample": "ACME Corp",
        "confidence": 0.9,
    }
    template = BrowserTemplate.model_validate(data)
    snapshot = BrowserSnapshot(
        elements=[{"ref": "@e12", "text": "ACME Corp", "frame_index": 0}],
    )

    records = extract_item_records(template, "order_no", "ORD-0001", snapshot)

    assert records[0]["ref_e9"] == "ACME Corp"


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


def _learned_table_template(template_data: dict[str, Any]) -> BrowserTemplate:
    template = _template(template_data, capture_tables=True)
    data = template.model_dump(mode="json")
    data["target"]["fields"] += [
        {"key": "material_code", "name": "物料编码", "semantic": ["物料编码"], "source": "detail"},
        {"key": "quantity", "name": "数量", "type": "integer", "semantic": ["数量"]},
        {
            "key": "row_no",
            "name": "行号",
            "type": "integer",
            "required": True,
            "semantic": ["行号"],
        },
    ]
    data["target"]["record_key"] = ["order_no", "row_no"]
    data["learned"]["table"] = {
        "index": 1,
        "title": "商品明细",
        "headers": ["序号", "物料编码", "物料名称", "数量"],
        "columns": {"material_code": 1, "quantity": 3},
    }
    return BrowserTemplate.model_validate(data)


def test_learned_table_rows_become_records_with_page_fields_copied(
    template_data: dict[str, Any],
) -> None:
    template = _learned_table_template(template_data)
    snapshot = BrowserSnapshot(
        text="客户：ACME\n",
        tables=[
            TableData(index=0, rows=[["客户", "ACME"], ["金额", "1"]]),
            # the taught table moved and gained a column: still found by its headers
            TableData(
                index=1,
                headers=["序号", "物料编码", "备注", "物料名称", "数量"],
                rows=[["1", "M-001", "", "螺栓", "200"], ["2", "M-002", "x", "垫片", "50"]],
            ),
        ],
    )

    records = extract_item_records(template, "order_no", "ORD-0001", snapshot)

    assert records == [
        {
            "customer": "ACME",
            "material_code": "M-001",
            "quantity": "200",
            "row_no": 1,
            "order_no": "ORD-0001",
        },
        {
            "customer": "ACME",
            "material_code": "M-002",
            "quantity": "50",
            "row_no": 2,
            "order_no": "ORD-0001",
        },
    ]


def test_learned_table_missing_on_page_falls_back_to_single_record(
    template_data: dict[str, Any],
) -> None:
    template = _learned_table_template(template_data)
    snapshot = BrowserSnapshot(
        text="客户：ACME\n",
        tables=[TableData(index=0, headers=["付款日期", "金额"], rows=[["2024-01-01", "1"]])],
    )

    records = extract_item_records(template, "order_no", "ORD-0001", snapshot)

    assert records == [{"customer": "ACME", "order_no": "ORD-0001"}]
    # ...which the classifier then reports as failed because row_no is required
    assert classify_item(template, records, []).status == BatchItemStatus.FAILED


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


def test_classify_empty_optional_pick_field_is_partial(template_data: dict[str, Any]) -> None:
    template = _template(template_data)
    data = template.model_dump(mode="json")
    data["target"]["fields"].append(
        {
            "key": "ref_e9",
            "name": "备注",
            "type": "string",
            "required": False,
            "semantic": ["备注"],
        }
    )
    data["learned"]["field_mappings"]["ref_e9"] = {
        "page": "detail",
        "strategy": "dom_hint",
        "hints": ["@e9"],
        "pick_sample": "note",
        "confidence": 0.9,
    }
    template = BrowserTemplate.model_validate(data)
    record = {"order_no": "ORD-0001", "customer": "ACME"}

    outcome = classify_item(template, [record], [])

    assert outcome.status == BatchItemStatus.PARTIAL
    assert outcome.reason == "pick_field_empty:ref_e9"
    assert outcome.records == [record]


def test_batch_stats_failure_groups(template_data: dict[str, Any]) -> None:
    batch = BatchProgress(
        driver_variable="order_no",
        items=[
            BatchItemState(
                index=0, value="A", url="u1", status=BatchItemStatus.FAILED, reason="auth_required"
            ),
            BatchItemState(
                index=1, value="B", url="u2", status=BatchItemStatus.FAILED, reason="auth_required"
            ),
            BatchItemState(
                index=2,
                value="C",
                url="u3",
                status=BatchItemStatus.PARTIAL,
                reason="pick_field_empty:ref_e9",
            ),
        ],
    )
    stats = batch.stats()
    groups = stats["failure_groups"]
    assert groups["auth_required"] == ["A", "B"]
    assert groups["pick_field_empty"] == ["C"]
    assert stats["pick_field_empty_values"] == ["C"]


def test_batch_stats_from_payload_recomputes_groups() -> None:
    from browser_skill.runtime.batch import batch_stats_from_payload

    payload = {
        "driver_variable": "order_no",
        "items": [
            {
                "index": 0,
                "value": "X",
                "url": "https://example/x",
                "status": "partial",
                "reason": "pick_field_empty:ref_e9",
            }
        ],
    }
    stats = batch_stats_from_payload(payload)
    assert stats["pick_field_empty_values"] == ["X"]


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


def _write_batch(runs_root: Path, run_id: str, template_id: str | None, items: list[dict]) -> None:
    (runs_root / run_id).mkdir(parents=True)
    payload = {"driver_variable": "order_no", "template_id": template_id, "items": items}
    (runs_root / run_id / "batch.json").write_text(json.dumps(payload), encoding="utf-8")


def test_previously_completed_values_reads_ok_items_of_same_template(tmp_path: Path) -> None:
    _write_batch(
        tmp_path,
        "run_20260101T000000Z_a",
        "orders",
        [
            {"value": "ORD-1", "status": "ok"},
            {"value": "ORD-2", "status": "failed"},
            {"value": "ORD-3", "status": "partial"},
        ],
    )
    _write_batch(tmp_path, "run_20260102T000000Z_b", "orders", [{"value": "ORD-1", "status": "ok"}])
    _write_batch(tmp_path, "run_20260103T000000Z_c", "other", [{"value": "ORD-9", "status": "ok"}])
    _write_batch(tmp_path, "run_20260104T000000Z_d", None, [{"value": "ORD-8", "status": "ok"}])
    (tmp_path / "run_20260105T000000Z_e").mkdir()
    (tmp_path / "run_20260105T000000Z_e" / "batch.json").write_text("{broken", encoding="utf-8")

    completed = previously_completed_values(tmp_path, "orders")

    # only ok counts; newest run wins; other templates, legacy and broken files are ignored
    assert completed == {"ORD-1": "run_20260102T000000Z_b"}
    assert previously_completed_values(tmp_path / "missing", "orders") == {}


def test_apply_incremental_skip_marks_only_pending_items() -> None:
    batch = BatchProgress(
        driver_variable="order_no",
        items=[
            BatchItemState(index=0, value="ORD-1", url="u1"),
            BatchItemState(index=1, value="ORD-2", url="u2"),
            BatchItemState(index=2, value="ORD-3", url="u3", status=BatchItemStatus.OK),
        ],
    )

    skipped = apply_incremental_skip(batch, {"ORD-1": "run_x", "ORD-3": "run_y"})

    assert skipped == 1
    assert batch.items[0].status == BatchItemStatus.SKIPPED
    assert batch.items[0].reason == "done_in:run_x"
    assert batch.items[0].done is True
    assert batch.items[1].status == BatchItemStatus.PENDING
    assert batch.items[2].status == BatchItemStatus.OK
    assert batch.stats()["skipped"] == 1
