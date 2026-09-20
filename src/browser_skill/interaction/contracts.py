from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from browser_skill.models import RunState, StrictModel


class InteractionKind(StrEnum):
    TEMPLATE_MENU = "template_menu"
    VARIABLE_FORM = "variable_form"
    AUTH_REQUIRED = "auth_required"
    PROGRESS = "progress"
    RUN_RESULT = "run_result"
    CONFIRMATION = "confirmation"
    TEMPLATE_REVIEW = "template_review"
    TARGET_REVIEW = "target_review"
    MAPPING_REVIEW = "mapping_review"
    METRICS = "metrics"
    ERROR = "error"


class InteractionChoice(StrictModel):
    id: str
    title: str
    description: str = ""
    value: str


class InteractionField(StrictModel):
    name: str
    label: str
    type: str = "string"
    required: bool = False
    default: Any | None = None
    options: list[str] = Field(default_factory=list)
    sensitive: bool = False


class SkillInteraction(StrictModel):
    """UI-framework-neutral contract rendered by the host Agent platform."""

    kind: InteractionKind
    title: str
    text: str
    choices: list[InteractionChoice] = Field(default_factory=list)
    fields: list[InteractionField] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    run_id: str | None = None
    state: RunState | None = None
    data: dict[str, Any] = Field(default_factory=dict)


def template_menu_interaction(templates: list[Any]) -> SkillInteraction:
    choices = [
        InteractionChoice(
            id=item.template_id,
            title=item.name,
            description=item.description,
            value=item.template_id,
        )
        for item in templates
    ]
    choices.append(
        InteractionChoice(
            id="create_template",
            title="创建新模板",
            description="进入 Teach 模式",
            value="create_template",
        )
    )
    if templates:
        lines = ["可用模板："] + [
            f"{index}. {item.name} — {item.description or '无说明'}"
            for index, item in enumerate(templates, 1)
        ]
        lines.append(f"{len(templates) + 1}. 创建新模板")
    else:
        lines = ["当前没有可用模板。请选择“创建新模板”。"]
    return SkillInteraction(
        kind=InteractionKind.TEMPLATE_MENU,
        title="请选择任务模板",
        text="\n".join(lines),
        choices=choices,
        actions=["select_template", "create_template"],
    )


def auth_required_interaction(run_id: str, auth_state: str) -> SkillInteraction:
    return SkillInteraction(
        kind=InteractionKind.AUTH_REQUIRED,
        title="需要在 Chrome 中完成登录",
        text=(
            "请直接在当前 Chrome 中完成 SSO、扫码、MFA、验证码或硬件认证。"
            "完成后选择“继续任务”，无需向 Agent 提供密码或验证码。"
        ),
        actions=["resume_run", "cancel_run"],
        run_id=run_id,
        state=RunState.WAIT_USER_AUTH,
        data={"auth_state": auth_state},
    )


def variable_form_interaction(template: Any, missing: list[str]) -> SkillInteraction:
    fields = [
        InteractionField(
            name=name,
            label=template.variables[name].prompt,
            type=template.variables[name].type.value,
            required=True,
            default=template.variables[name].default,
            options=template.variables[name].options,
            sensitive=template.variables[name].sensitive,
        )
        for name in missing
    ]
    labels = "、".join(field.label for field in fields)
    return SkillInteraction(
        kind=InteractionKind.VARIABLE_FORM,
        title="请补充运行条件",
        text=f"还需要以下必填信息：{labels}",
        fields=fields,
        actions=["submit_variables", "cancel_run"],
        data={"template_id": template.template_id},
    )


def run_result_interaction(
    *,
    run_id: str,
    state: RunState,
    message: str,
    data: dict[str, Any],
) -> SkillInteraction:
    return SkillInteraction(
        kind=InteractionKind.RUN_RESULT if state != RunState.FAILED else InteractionKind.ERROR,
        title="任务结果" if state != RunState.FAILED else "任务未完成",
        text=f"{message}\nRun ID: {run_id}\n状态: {state.value}",
        run_id=run_id,
        state=state,
        data=data,
    )


def template_review_interaction(template: Any, *, mode: str) -> SkillInteraction:
    field_names = "、".join(field.name for field in template.target.fields) or "无"
    attachment_names = "、".join(item.name for item in template.target.attachments) or "无"
    return SkillInteraction(
        kind=InteractionKind.TEMPLATE_REVIEW,
        title="请检查模板草稿" if mode == "teach" else "请检查 Repair 候选",
        text=(
            f"模板：{template.name}\n"
            f"版本：{template.version}\n"
            f"字段：{field_names}\n"
            f"附件：{attachment_names}\n"
            "必须完成 Test Run 并通过后才能发布。"
        ),
        actions=["test_template", "cancel_template"],
        data={
            "mode": mode,
            "template_id": template.template_id,
            "version": template.version,
            "status": template.status.value,
        },
    )


def error_interaction(
    message: str, *, code: str, details: dict[str, Any] | None = None
) -> SkillInteraction:
    return SkillInteraction(
        kind=InteractionKind.ERROR,
        title="无法完成请求",
        text=f"{message}\n错误码：{code}",
        actions=["retry", "cancel"],
        data={"error_code": code, "details": details or {}},
    )


def sample_review_interaction(inference: Any) -> SkillInteraction:
    fields = "、".join(field.name for field in inference.fields)
    attachments = "、".join(inference.attachment_columns) or "未识别"
    variables = "、".join(inference.variable_candidates) or "未识别"
    return SkillInteraction(
        kind=InteractionKind.TARGET_REVIEW,
        title="请确认样例推导结果",
        text=(
            f"识别到 {len(inference.fields)} 个字段、{inference.sample_record_count} 条样例记录。\n"
            f"字段：{fields}\n附件候选：{attachments}\n变量候选：{variables}\n"
            "这些结果只是候选，创建模板前可以修改。"
        ),
        actions=["accept_sample_inference", "edit_sample_inference", "cancel_template"],
        data=inference.model_dump(mode="json"),
    )


def mapping_review_interaction(report: Any, *, candidate_version: int | None) -> SkillInteraction:
    missing = report.missing_required_fields + report.missing_required_attachments
    if missing:
        title = "需要继续探索页面"
        actions = ["continue_discovery", "edit_target", "cancel_template"]
        result = f"仍缺少必填目标：{'、'.join(missing)}"
    else:
        title = "Mapping 候选已生成"
        actions = ["test_template", "review_mapping", "cancel_template"]
        result = "所有必填目标均已找到，必须通过 Test Run 后才能发布。"
    return SkillInteraction(
        kind=InteractionKind.MAPPING_REVIEW,
        title=title,
        text=(
            f"字段匹配：{len(report.matched_fields)}；"
            f"附件匹配：{len(report.matched_attachments)}。\n{result}"
        ),
        actions=actions,
        data={
            "candidate_version": candidate_version,
            "matched_fields": report.matched_fields,
            "missing_required_fields": report.missing_required_fields,
            "matched_attachments": report.matched_attachments,
            "missing_required_attachments": report.missing_required_attachments,
            "page_url": report.page_url,
        },
    )


def run_status_interaction(context: Any) -> SkillInteraction:
    terminal = context.state in {
        RunState.COMPLETED,
        RunState.PARTIAL,
        RunState.FAILED,
        RunState.CANCELLED,
    }
    return SkillInteraction(
        kind=InteractionKind.RUN_RESULT if terminal else InteractionKind.PROGRESS,
        title="任务状态",
        text=(
            f"Run ID: {context.run_id}\n状态: {context.state.value}\n"
            f"已抓取记录: {len(context.records)}；已处理附件: {len(context.downloaded_files)}"
        ),
        actions=[] if terminal else ["refresh_status", "cancel_run"],
        run_id=context.run_id,
        state=context.state,
        data={
            "record_count": len(context.records),
            "download_count": len(context.downloaded_files),
            "repair_attempts": context.repair_attempts,
        },
    )


def metrics_interaction(report: Any) -> SkillInteraction:
    completed = report.state_counts.get("COMPLETED", 0)
    failed = report.state_counts.get("FAILED", 0)
    return SkillInteraction(
        kind=InteractionKind.METRICS,
        title="Browser Skill 运行指标",
        text=(
            f"已汇总 {report.scanned_runs} 个 Run；忽略 {report.ignored_runs} 个无效摘要。\n"
            f"完成: {completed}；失败: {failed}；记录: {report.total_records}；"
            f"下载: {report.total_downloads}。\n"
            f"字段完整率: {report.average_field_completeness:.1%}；"
            f"下载成功率: {report.average_download_success_rate:.1%}。"
        ),
        actions=["refresh_metrics"],
        data=report.model_dump(mode="json"),
    )
