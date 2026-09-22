from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.models import BrowserSnapshot, BrowserTemplate, RunState
from browser_skill.pipeline.analyze import CallableAnalysisProvider
from browser_skill.runtime.runner import Runner


def _template(template_data: dict[str, Any], **analysis: Any) -> BrowserTemplate:
    data = deepcopy(template_data)
    data["schema_version"] = "2.0"
    data["target"]["attachments"] = []
    data["workflow"]["hints"] = []
    data["analysis"] = {"enabled": True, **analysis}
    data["report"] = {"enabled": True}
    return BrowserTemplate.model_validate(data)


def _adapter(records: list[dict[str, Any]]) -> FakeBrowserAdapter:
    return FakeBrowserAdapter(
        {
            "snapshot": [
                BrowserSnapshot(
                    url="https://example.internal/home",
                    text="退出登录 样机盘点反馈",
                    records=records,
                )
            ]
        }
    )


def _run(tmp_path: Path, template: BrowserTemplate, records: list[dict[str, Any]], **kw: Any):
    return asyncio.run(Runner(_adapter(records), tmp_path / "runs", **kw).run(template, {}))


def _analysis(tmp_path: Path, run_id: str) -> dict[str, Any]:
    payload = json.loads((tmp_path / "runs" / run_id / "pipeline.json").read_text("utf-8"))
    return payload["stages"]["analyze"]


def test_clean_run_has_no_findings_and_report_section(tmp_path: Path, template_data) -> None:
    template = _template(template_data)
    records = [{"sample_id": f"S-{i}", "sn": f"SN-{i}", "product_model": "P"} for i in range(4)]
    response = _run(tmp_path, template, records)
    assert response.ok and response.state == RunState.COMPLETED
    analysis = _analysis(tmp_path, str(response.run_id))
    assert analysis["skipped"] is False and analysis["severity"] == "ok"
    assert analysis["findings"] == [] and analysis["baseline"] is None
    assert "未发现异常" in analysis["summary"]
    report = (tmp_path / "runs" / str(response.run_id) / "report.md").read_text("utf-8")
    assert "## 分析（ok）" in report and "未发现异常" in report


def test_required_gap_and_record_drop_against_previous_run(tmp_path: Path, template_data) -> None:
    template = _template(template_data, record_change_threshold=0.3)
    first = _run(
        tmp_path,
        template,
        [{"sample_id": f"S-{i}", "sn": f"SN-{i}", "product_model": "P"} for i in range(10)],
    )
    assert first.ok
    second = _run(
        tmp_path,
        template,
        [
            {"sample_id": "S-1", "sn": "SN-1", "product_model": "P"},
            {"sample_id": "S-2", "sn": "SN-2", "product_model": ""},
        ],
    )
    analysis = _analysis(tmp_path, str(second.run_id))
    codes = {item["code"]: item for item in analysis["findings"]}
    assert analysis["baseline"]["run_id"] == first.run_id
    assert analysis["baseline"]["record_count"] == 10
    assert codes["record_count_change"]["details"]["delta_ratio"] == -0.8
    assert "减少 80%" in codes["record_count_change"]["message"]
    assert codes["optional_field_sparse"]["details"] == {
        "field": "product_model",
        "empty": 1,
        "total": 2,
    }
    assert analysis["severity"] == "warning"
    assert "上次完成运行" in analysis["summary"]


def test_validation_failure_becomes_error_finding(tmp_path: Path, template_data) -> None:
    template = _template(template_data)
    template.validation.min_records = 5
    response = _run(tmp_path, template, [{"sample_id": "S-1", "sn": "SN-1", "product_model": ""}])
    assert response.ok is False
    analysis = _analysis(tmp_path, str(response.run_id))
    assert analysis["severity"] == "error"
    assert any(item["code"] == "validation.min_records" for item in analysis["findings"])


def test_ai_provider_summary_is_attached_and_failures_are_contained(
    tmp_path: Path, template_data
) -> None:
    template = _template(template_data, prompt_template="请总结盘点异常")
    seen: list[dict[str, Any]] = []

    def summarize(payload: dict[str, Any]) -> str:
        seen.append(payload)
        return "  AI：一切正常。  "

    provider = CallableAnalysisProvider(summarize, name="fake-llm")
    response = _run(
        tmp_path,
        template,
        [{"sample_id": "S", "sn": "SN", "product_model": "P"}],
        analysis_provider=provider,
    )
    analysis = _analysis(tmp_path, str(response.run_id))
    assert analysis["provider"] == "fake-llm" and analysis["ai_summary"] == "AI：一切正常。"
    assert seen[0]["prompt_template"] == "请总结盘点异常" and seen[0]["record_count"] == 1
    report = (tmp_path / "runs" / str(response.run_id) / "report.md").read_text("utf-8")
    assert "AI：一切正常。" in report

    async def broken(_payload: dict[str, Any]) -> str | None:
        raise RuntimeError("model offline")

    response = _run(
        tmp_path,
        template,
        [{"sample_id": "S", "sn": "SN", "product_model": "P"}],
        analysis_provider=CallableAnalysisProvider(broken, name="broken"),
    )
    assert response.ok
    analysis = _analysis(tmp_path, str(response.run_id))
    assert analysis["provider"] == "rules" and "model offline" in analysis["provider_error"]


def test_analysis_disabled_is_skipped(tmp_path: Path, template_data) -> None:
    template = _template(template_data)
    template.analysis.enabled = False
    response = _run(tmp_path, template, [{"sample_id": "S", "sn": "SN", "product_model": "P"}])
    assert _analysis(tmp_path, str(response.run_id)) == {
        "skipped": True,
        "reason": "analysis disabled",
    }
