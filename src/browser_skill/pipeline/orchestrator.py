from __future__ import annotations

from enum import StrEnum
from typing import Any

from browser_skill.models import RunContext, ValidationReport
from browser_skill.pipeline.analyze import apply_analysis
from browser_skill.pipeline.deliver import deliver
from browser_skill.pipeline.report import build_report_metadata, render_markdown_report


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
    """Run post-validation stages, persist report.md / pipeline.json, extend artifacts."""
    from browser_skill.outputs.writer import RunWorkspace

    template = context.template_snapshot
    workspace = RunWorkspace.existing(context.workspace)
    analysis = apply_analysis(template, context.records, validation_ok=report.ok)
    report_meta = build_report_metadata(template, context, report, artifacts)
    if template.report.enabled:
        markdown = render_markdown_report(template, context, report, artifacts)
        path = workspace.atomic_text("report.md", markdown)
        artifacts["report"] = path.relative_to(workspace.path).as_posix()
        report_meta["path"] = artifacts["report"]
    delivery = deliver(template, context, artifacts)
    payload = {
        "stages": {
            PipelineStage.PROCESS.value: {
                "applied": template.processing.enabled,
                "steps": [step.action for step in template.processing.steps],
            },
            PipelineStage.VALIDATE.value: report.model_dump(mode="json"),
            PipelineStage.ANALYZE.value: analysis,
            PipelineStage.REPORT.value: report_meta,
            PipelineStage.DELIVER.value: delivery,
        }
    }
    rel = workspace.atomic_json("pipeline.json", payload).relative_to(workspace.path).as_posix()
    artifacts["pipeline"] = rel
    return {"pipeline": payload, "pipeline_json": rel}
