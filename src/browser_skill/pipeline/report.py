from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from browser_skill.models import BrowserTemplate, DownloadStatus, RunContext, ValidationReport

_MAX_PREVIEW_ROWS = 20


def _render_title(template: BrowserTemplate, context: RunContext) -> str:
    title = template.report.title_pattern.replace("{template_id}", template.template_id)
    title = title.replace("{template_name}", template.name)
    for key, value in context.variables.items():
        title = title.replace("{" + key + "}", str(value))
    return title


def _markdown_table(columns: list[str], records: list[dict[str, Any]]) -> str:
    if not columns:
        return "_无字段_\n"
    header = "| " + " | ".join(columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    rows = [
        "| " + " | ".join(str(record.get(col, "")).replace("|", "\\|") for col in columns) + " |"
        for record in records[:_MAX_PREVIEW_ROWS]
    ]
    return "\n".join([header, divider, *rows]) + "\n"


def render_markdown_report(
    template: BrowserTemplate,
    context: RunContext,
    report: ValidationReport,
    artifacts: dict[str, str],
    *,
    analysis: dict[str, Any] | None = None,
) -> str:
    title = _render_title(template, context)
    ok_files = [item for item in context.downloaded_files if item.status == DownloadStatus.OK]
    columns = template.output.columns or [field.key for field in template.target.fields]
    lines = [
        f"# {title}",
        "",
        f"- 模板：`{template.template_id}@{template.version}`（{template.name}）",
        f"- 运行：`{context.run_id}`",
        f"- 生成时间：{datetime.now(UTC).isoformat(timespec='seconds')}",
        f"- 记录数：{len(context.records)}",
        f"- 附件（成功）：{len(ok_files)} / {len(context.downloaded_files)}",
        f"- 校验：{'通过' if report.ok else '未通过'}" + ("（部分结果）" if report.partial else ""),
        "",
        "## 变量",
        "",
    ]
    if context.variables:
        lines.extend(f"- {key}：{value}" for key, value in context.variables.items())
    else:
        lines.append("_无_")
    lines += ["", "## 数据预览", "", _markdown_table(columns, context.records)]
    if len(context.records) > _MAX_PREVIEW_ROWS:
        lines.append(f"_仅显示前 {_MAX_PREVIEW_ROWS} 条，完整数据见结果文件。_")
    if analysis and not analysis.get("skipped"):
        lines += ["", f"## 分析（{analysis.get('severity', 'ok')}）", ""]
        lines.append(str(analysis.get("ai_summary") or analysis.get("summary", "")).strip())
        findings = analysis.get("findings") or []
        if findings:
            lines += ["", "### 发现", ""]
            lines.extend(f"- [{item.get('severity')}] {item.get('message')}" for item in findings)
    if template.report.include_summary and report.issues:
        lines += ["", "## 校验问题", ""]
        lines.extend(
            f"- [{'必需' if issue.required else '可选'}] {issue.code}：{issue.message}"
            for issue in report.issues
        )
    if artifacts:
        lines += ["", "## 制品", ""]
        lines.extend(f"- {name}：`{path}`" for name, path in sorted(artifacts.items()))
    return "\n".join(lines) + "\n"


def build_report_metadata(
    template: BrowserTemplate,
    context: RunContext,
    report: ValidationReport,
    artifacts: dict[str, str],
) -> dict[str, Any]:
    spec = template.report
    if not spec.enabled:
        return {"enabled": False}
    payload: dict[str, Any] = {
        "enabled": True,
        "title": _render_title(template, context),
        "template": f"{template.template_id}@{template.version}",
        "run_id": context.run_id,
        "record_count": len(context.records),
        "validation_ok": report.ok,
        "artifacts": artifacts,
    }
    if spec.include_summary:
        payload["validation"] = report.model_dump(mode="json")
    return payload
