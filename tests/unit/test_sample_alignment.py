from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from browser_skill.app import BrowserSkillApp
from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.models import BrowserSnapshot, BrowserTemplate, SkillRequest
from browser_skill.runtime.sample_alignment import (
    SampleAligner,
    classify_shape,
    dominant_shape,
    match_column,
)
from browser_skill.templates.store import TemplateStore


def _template(template_data: dict[str, Any]) -> BrowserTemplate:
    data = deepcopy(template_data)
    data["target"]["attachments"] = []
    data["workflow"]["hints"] = []
    return BrowserTemplate.model_validate(data)


def test_shape_classifier_handles_common_business_values() -> None:
    assert classify_shape("1,200") == "integer"
    assert classify_shape("12.5%") == "number"
    assert classify_shape("2026-09-01") == "date"
    assert classify_shape("2026/09/01 08:30") == "datetime"
    assert classify_shape("2026年9月1日") == "date"
    assert classify_shape("是") == "boolean"
    assert classify_shape("  ") == "empty"
    assert classify_shape("SN-1") == "text"
    assert dominant_shape(["", None, "3", "4", "x"]) == "integer"


def test_column_matching_uses_key_name_semantic_alias_and_normalization(template_data) -> None:
    template = _template(template_data)
    template.target.fields[1].aliases = ["序列号(SN)"]
    fields = template.target.fields
    assert match_column("sn", fields)[1] == "key"
    assert match_column("样机ID", fields)[1] == "name"
    assert match_column("设备ID", fields)[1] == "semantic"
    assert match_column("序列号(SN)", fields)[1] == "alias"
    assert match_column("产品 型号", fields)[1] == "normalized"
    assert match_column("仓库", fields) is None


def test_alignment_reports_coverage_shape_and_missing_values(tmp_path: Path, template_data) -> None:
    template = _template(template_data)
    sample = tmp_path / "sample.csv"
    sample.write_text(
        "样机ID,SN,产品型号,仓库\nS-1,SN-1,100,华东\nS-2,SN-2,200,华南\n", encoding="utf-8"
    )
    records = [
        {"sample_id": "S-1", "sn": "SN-1", "product_model": "P100"},
        {"sample_id": "S-2", "sn": "SN-2", "product_model": ""},
    ]

    report = SampleAligner().align(template, sample, records)

    assert report.sample_record_count == 2 and report.run_record_count == 2
    assert [item.field_key for item in report.columns] == ["sample_id", "sn", "product_model"]
    assert report.unmatched_sample_columns == ["仓库"]
    assert report.coverage == 0.75
    model = next(item for item in report.columns if item.field_key == "product_model")
    assert model.sample_shape == "integer" and model.run_shape == "text"
    assert model.shape_match is False and model.run_fill_rate == 0.5
    assert model.sample_examples == ["100", "200"] and model.run_examples == ["P100"]
    assert report.aligned is False
    assert any("仓库" in issue for issue in report.issues)
    assert any("product_model" in issue and "integer" in issue for issue in report.issues)


def test_alignment_is_clean_when_sample_matches_run(tmp_path: Path, template_data) -> None:
    template = _template(template_data)
    sample = tmp_path / "sample.json"
    sample.write_text(
        json.dumps([{"sample_id": "S-9", "sn": "SN-9", "product_model": "P9"}]),
        encoding="utf-8",
    )
    records = [{"sample_id": "S-1", "sn": "SN-1", "product_model": "P1"}]
    report = SampleAligner().align(template, sample, records)
    assert report.aligned is True and report.issues == [] and report.coverage == 1.0
    assert report.fields_without_sample_column == []


def test_unsupported_sample_type_yields_no_records_issue(tmp_path: Path, template_data) -> None:
    sample = tmp_path / "sample.xlsx"
    sample.write_bytes(b"PK")
    report = SampleAligner().align(_template(template_data), sample, [])
    assert report.sample_record_count == 0 and report.coverage == 0.0
    assert any("样例文件没有记录" in issue for issue in report.issues)


def test_teach_test_with_sample_attaches_alignment(tmp_path: Path, template_data) -> None:
    store = TemplateStore(tmp_path / "templates")
    store.save(_template(template_data))
    runs_root = tmp_path / "runs"
    app = BrowserSkillApp(
        tmp_path / "templates", runs_root, FakeBrowserAdapter(), samples_root=tmp_path / "uploads"
    )
    (tmp_path / "uploads" / "want.csv").write_text(
        "样机ID,SN,产品型号,仓库\nS-1,SN-1,P100,华东\n", encoding="utf-8"
    )
    app.adapter.script["snapshot"].append(
        BrowserSnapshot(
            url="https://example.internal/home",
            text="退出登录 样机盘点反馈",
            records=[{"sample_id": "S-1", "sn": "SN-1", "product_model": "P100"}],
        )
    )

    response = asyncio.run(
        app.handle(
            SkillRequest(
                action="test",
                template_id="inventory_feedback",
                variables={},
                sample_path=Path("want.csv"),
            )
        )
    )

    assert response.ok, response.message
    alignment = response.data["sample_alignment"]
    assert alignment["coverage"] == 0.75 and alignment["unmatched_sample_columns"] == ["仓库"]
    assert alignment["aligned"] is False and "样例比对" in response.message
    saved = runs_root / str(response.run_id) / "sample_alignment.json"
    assert json.loads(saved.read_text(encoding="utf-8"))["coverage"] == 0.75
