from __future__ import annotations

from pathlib import Path

from browser_skill.models import (
    BatchItemState,
    BatchItemStatus,
    BatchProgress,
    BrowserTemplate,
    RunContext,
    RunState,
)
from browser_skill.pipeline.deliver import build_webhook_payload


def test_webhook_payload_includes_batch_stats(template_data: dict) -> None:
    template = BrowserTemplate.model_validate(template_data)
    batch = BatchProgress(
        driver_variable="order_no",
        items=[
            BatchItemState(
                index=0,
                value="ORD-1",
                url="https://example.internal/list",
                status=BatchItemStatus.FAILED,
                reason="list_navigation:element_not_found",
            ),
        ],
    )
    context = RunContext(
        run_id="run-batch-1",
        template_id=template.template_id,
        template_version=1,
        template_snapshot=template,
        workspace=Path("/tmp/runs/run-batch-1"),
        state=RunState.PARTIAL,
        batch=batch,
    )
    payload = build_webhook_payload(context, {"json": "result.json"}, None)
    assert payload["batch"]["driver_variable"] == "order_no"
    stats = payload["batch"]["stats"]
    assert stats["list_navigation_failure_values"] == ["ORD-1"]
    assert "list_navigation" in stats["failure_groups"]
    retry = payload["batch"]["retry_suggestions"]
    assert retry == [
        {
            "action": "retry_batch",
            "run_id": "run-batch-1",
            "failure_bucket": "list_navigation",
            "value_count": 1,
            "values_sample": ["ORD-1"],
            "cli": "browser-skill retry-batch run-batch-1 --bucket list_navigation",
        },
        {
            "action": "retry_batch",
            "run_id": "run-batch-1",
            "failure_bucket": "failed",
            "value_count": 1,
            "values_sample": ["ORD-1"],
            "cli": "browser-skill retry-batch run-batch-1 --bucket failed",
        },
    ]


def test_webhook_payload_omits_batch_when_not_batch_run(template_data: dict) -> None:
    template = BrowserTemplate.model_validate(template_data)
    context = RunContext(
        run_id="run-1",
        template_id=template.template_id,
        template_version=1,
        template_snapshot=template,
        workspace=Path("/tmp/runs/run-1"),
        state=RunState.COMPLETED,
    )
    payload = build_webhook_payload(context, {}, None)
    assert "batch" not in payload
