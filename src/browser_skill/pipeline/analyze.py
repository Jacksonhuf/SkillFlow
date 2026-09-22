"""Analyze stage: turn a finished run into findings a business user can act on.

Rules run locally and need no model: validation issues, empty results, required-field gaps,
attachment failures, incomplete pagination and record-count swings against the previous completed
run of the same template. A host may inject an ``AnalysisProvider`` (LLM) to rewrite the summary;
its output is attached alongside the rule-based text and never replaces the findings.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from browser_skill.models import BrowserTemplate, DownloadStatus, RunContext, ValidationReport

Severity = Literal["info", "warning", "error"]
_SEVERITY_RANK: dict[Severity, int] = {"info": 0, "warning": 1, "error": 2}
_MAX_SUMMARY_LINES = 6
_SPARSE_RATIO = 0.5


@dataclass(slots=True)
class Finding:
    code: str
    severity: Severity
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Baseline:
    run_id: str
    record_count: int
    finished_at: str | None = None


class AnalysisProvider(Protocol):
    """Host-injected summarizer (e.g. an LLM); receives the rule findings, returns prose."""

    name: str

    async def summarize(self, payload: dict[str, Any]) -> str | None: ...


SyncSummarizer = Callable[[dict[str, Any]], str | None]
AsyncSummarizer = Callable[[dict[str, Any]], Awaitable[str | None]]


class CallableAnalysisProvider:
    """Adapt a plain (sync or async) function into an AnalysisProvider."""

    def __init__(self, func: SyncSummarizer | AsyncSummarizer, *, name: str = "callable") -> None:
        self.func = func
        self.name = name

    async def summarize(self, payload: dict[str, Any]) -> str | None:
        result = self.func(payload)
        if isinstance(result, str) or result is None:
            return result
        return await result


def find_baseline(context: RunContext) -> Baseline | None:
    """Most recent completed run of the same template (other than this one) in the runs root."""
    runs_root = context.workspace.parent
    best: tuple[str, Baseline] | None = None
    if not runs_root.is_dir():
        return None
    for run_dir in runs_root.iterdir():
        if not run_dir.is_dir() or run_dir.name == context.run_id:
            continue
        run_file = run_dir / "run.json"
        if not run_file.is_file():
            continue
        try:
            payload = json.loads(run_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or payload.get("template_id") != context.template_id:
            continue
        if payload.get("state") != "COMPLETED":
            continue
        finished = str(payload.get("finished_at") or payload.get("started_at") or run_dir.name)
        if best is None or finished > best[0]:
            records = payload.get("records") or []
            best = (
                finished,
                Baseline(
                    run_id=str(payload.get("run_id", run_dir.name)),
                    record_count=len(records) if isinstance(records, list) else 0,
                    finished_at=payload.get("finished_at"),
                ),
            )
    return best[1] if best else None


def rule_findings(
    template: BrowserTemplate,
    context: RunContext,
    report: ValidationReport,
    baseline: Baseline | None,
    *,
    change_threshold: float,
) -> list[Finding]:
    findings: list[Finding] = []
    records = context.records
    for issue in report.issues:
        findings.append(
            Finding(
                code=f"validation.{issue.code}",
                severity="error" if issue.required else "warning",
                message=issue.message,
                details={"record_key": issue.record_key} if issue.record_key else {},
            )
        )
    if not records:
        findings.append(
            Finding(
                "no_records", "warning", "本次运行没有取到任何记录，请确认筛选条件或页面是否有数据"
            )
        )
    # Required-field gaps are already validation issues; here we flag optional fields that came
    # back mostly empty, which usually means the page layout changed or the mapping drifted.
    for spec in template.target.fields:
        if spec.required or not records:
            continue
        empty = sum(1 for record in records if record.get(spec.key) in (None, ""))
        if empty / len(records) >= _SPARSE_RATIO:
            findings.append(
                Finding(
                    "optional_field_sparse",
                    "warning",
                    f"字段「{spec.name}」有 {empty}/{len(records)} 条为空",
                    {"field": spec.key, "empty": empty, "total": len(records)},
                )
            )
    failed = [item for item in context.downloaded_files if item.status != DownloadStatus.OK]
    if failed:
        required_keys = {item.key for item in template.target.attachments if item.required}
        severity: Severity = (
            "error" if any(item.attachment_key in required_keys for item in failed) else "warning"
        )
        findings.append(
            Finding(
                "attachment_failures",
                severity,
                f"{len(failed)} 个附件下载失败",
                {"records": sorted({item.record_key or "" for item in failed})[:20]},
            )
        )
    if not context.pagination_complete:
        findings.append(Finding("pagination_incomplete", "warning", "分页未走完，结果可能不完整"))
    if baseline is not None and baseline.record_count:
        delta = (len(records) - baseline.record_count) / baseline.record_count
        if abs(delta) >= change_threshold:
            direction = "增加" if delta > 0 else "减少"
            findings.append(
                Finding(
                    "record_count_change",
                    "warning",
                    f"记录数较上次（{baseline.record_count}）{direction} {abs(delta):.0%}",
                    {
                        "baseline_run_id": baseline.run_id,
                        "baseline_count": baseline.record_count,
                        "current_count": len(records),
                        "delta_ratio": round(delta, 4),
                    },
                )
            )
    return findings


def overall_severity(findings: list[Finding]) -> Literal["ok", "info", "warning", "error"]:
    if not findings:
        return "ok"
    worst = max(findings, key=lambda item: _SEVERITY_RANK[item.severity])
    return worst.severity


def rule_summary(
    context: RunContext,
    report: ValidationReport,
    findings: list[Finding],
    baseline: Baseline | None,
) -> str:
    ok_files = sum(item.status == DownloadStatus.OK for item in context.downloaded_files)
    lines = [
        f"共 {len(context.records)} 条记录，附件 {ok_files}/{len(context.downloaded_files)}，"
        f"校验{'通过' if report.ok else '未通过'}。"
    ]
    if baseline is not None:
        lines.append(f"上次完成运行 {baseline.run_id} 有 {baseline.record_count} 条记录。")
    if not findings:
        lines.append("未发现异常。")
    for item in findings[: _MAX_SUMMARY_LINES - len(lines)]:
        lines.append(f"[{item.severity}] {item.message}")
    if len(findings) > _MAX_SUMMARY_LINES - 2:
        lines.append(f"…另有 {len(findings) - (_MAX_SUMMARY_LINES - 2)} 项，见 pipeline.json。")
    return "\n".join(lines)


async def apply_analysis(
    template: BrowserTemplate,
    context: RunContext,
    report: ValidationReport,
    *,
    provider: AnalysisProvider | None = None,
) -> dict[str, Any]:
    spec = template.analysis
    if not spec.enabled:
        return {"skipped": True, "reason": "analysis disabled"}
    baseline = find_baseline(context) if spec.compare_with_previous else None
    findings = rule_findings(
        template, context, report, baseline, change_threshold=spec.record_change_threshold
    )
    summary = rule_summary(context, report, findings, baseline)
    payload: dict[str, Any] = {
        "skipped": False,
        "severity": overall_severity(findings),
        "summary": summary,
        "findings": [asdict(item) for item in findings],
        "baseline": asdict(baseline) if baseline else None,
        "provider": "rules",
    }
    if provider is not None:
        prompt_payload = {
            "template": {"id": template.template_id, "name": template.name},
            "run_id": context.run_id,
            "variables": context.variables,
            "prompt_template": spec.prompt_template,
            "model_hint": spec.model_hint,
            "record_count": len(context.records),
            "validation": report.model_dump(mode="json"),
            "findings": payload["findings"],
            "rule_summary": summary,
        }
        try:
            text = await provider.summarize(prompt_payload)
        except Exception as exc:  # the AI layer must never fail the run
            payload["provider_error"] = f"{type(exc).__name__}: {exc}"[:500]
        else:
            if text:
                payload["ai_summary"] = text.strip()
                payload["provider"] = provider.name
    return payload


def analysis_path(workspace: Path) -> Path:
    return workspace / "pipeline.json"
