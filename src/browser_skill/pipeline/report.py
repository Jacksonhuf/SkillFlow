from __future__ import annotations

from typing import Any

from browser_skill.models import BrowserTemplate, ReportSpec, RunContext, ValidationReport


def build_report_metadata(
    template: BrowserTemplate,
    context: RunContext,
    report: ValidationReport,
    artifacts: dict[str, str],
) -> dict[str, Any]:
    spec = template.report
    if not spec.enabled:
        return {"enabled": False}
    title = spec.title_pattern.replace("{template_id}", template.template_id)
    for key, value in context.variables.items():
        title = title.replace("{" + key + "}", str(value))
    payload: dict[str, Any] = {
        "enabled": True,
        "title": title,
        "template": f"{template.template_id}@{template.version}",
        "run_id": context.run_id,
        "record_count": len(context.records),
        "validation_ok": report.ok,
        "artifacts": artifacts,
    }
    if spec.include_summary:
        payload["validation"] = report.model_dump(mode="json")
    return payload
