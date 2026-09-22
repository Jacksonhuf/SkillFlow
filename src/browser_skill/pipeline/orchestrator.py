from __future__ import annotations

from enum import StrEnum
from typing import Any

from browser_skill.models import RunContext, ValidationReport
from browser_skill.pipeline.analyze import apply_analysis
from browser_skill.pipeline.deliver import deliver
from browser_skill.pipeline.report import build_report_metadata


class PipelineStage(StrEnum):
    ACQUIRE = "acquire"
    NORMALIZE = "normalize"
    PROCESS = "process"
    VALIDATE = "validate"
    ANALYZE = "analyze"
    REPORT = "report"
    DELIVER = "deliver"


def finalize_pipeline(
    context: RunContext,
    report: ValidationReport,
    artifacts: dict[str, str],
) -> dict[str, Any]:
    """Run post-validation stages and persist pipeline.json."""
    template = context.template_snapshot
    analysis = apply_analysis(template, context.records, validation_ok=report.ok)
    report_meta = build_report_metadata(template, context, report, artifacts)
    delivery = deliver(template, context, artifacts)
    payload = {
        "stages": {
            "process": {"applied": template.processing.enabled},
            "validate": report.model_dump(mode="json"),
            "analyze": analysis,
            "report": report_meta,
            "deliver": delivery,
        }
    }
    from browser_skill.outputs.writer import RunWorkspace

    workspace = RunWorkspace.existing(context.workspace)
    rel = workspace.atomic_json("pipeline.json", payload).relative_to(workspace.path).as_posix()
    return {"pipeline": payload, "pipeline_json": rel}
