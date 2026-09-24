"""Compile the wizard's ticked probe candidates into a detail_batch draft template."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from pydantic import ValidationError

from browser_skill.errors import ErrorCode, SkillError
from browser_skill.models import (
    AcquisitionSource,
    AttachmentSpec,
    AuthSpec,
    BrowserTemplate,
    FieldSpec,
    FieldType,
    LearnedMapping,
    LearnedSpec,
    LearnedTable,
    LoginCheckSpec,
    OutputSpec,
    ProbeDraftInput,
    RunMode,
    RunSpec,
    SignalSpec,
    SourcePage,
    SystemSpec,
    TargetSpec,
    TemplateStatus,
    ValidationSpec,
    VariableSpec,
    VariableType,
    VariableValidation,
)

_PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")
# Stamped on every table row so (driver, row_no) identifies a record even when rows repeat
ROW_NO_KEY = "row_no"
_ALLOWED_RUN_KEYS = {
    "concurrency",
    "per_item_delay_ms",
    "on_item_error",
    "dedupe_values",
    "max_items",
    "accept_full_urls",
    "capture_tables",
    "skip_if_exists",
}


class ProbeDraftCompiler:
    def compile(self, draft: ProbeDraftInput, *, version: int) -> BrowserTemplate:
        try:
            return self._compile(draft, version=version)
        except (ValidationError, ValueError) as exc:
            raise SkillError(
                ErrorCode.TEMPLATE_INVALID,
                f"无法根据探测结果生成模板：{exc}",
                stage="create_from_probe",
            ) from exc

    def _compile(self, draft: ProbeDraftInput, *, version: int) -> BrowserTemplate:
        driver = draft.driver_variable
        host = draft.sample_url.host or ""
        record_key = list(draft.record_key) or [driver]
        required = set(draft.required_keys) | set(record_key)

        fields: list[FieldSpec] = []
        learned = LearnedSpec()
        seen: set[str] = set()
        for candidate in draft.fields:
            if candidate.key in seen:
                continue
            seen.add(candidate.key)
            semantic = _unique([candidate.name, *candidate.aliases])
            fields.append(
                FieldSpec(
                    key=candidate.key,
                    name=candidate.name,
                    type=candidate.type,
                    required=candidate.key in required,
                    semantic=semantic,
                    source=SourcePage.DETAIL,
                )
            )
            if candidate.source == "network" and candidate.json_path:
                learned.field_mappings[candidate.key] = LearnedMapping(
                    page=SourcePage.DETAIL,
                    strategy="semantic",
                    hints=semantic,
                    confidence=candidate.confidence,
                    preferred_source=AcquisitionSource.NETWORK,
                    endpoint_hint=candidate.endpoint_hint,
                    json_path=candidate.json_path,
                )
            elif candidate.source in {"dom", "table"}:
                learned.field_mappings[candidate.key] = LearnedMapping(
                    page=SourcePage.DETAIL,
                    strategy="label_value" if candidate.source == "dom" else "table_header",
                    hints=semantic,
                    confidence=candidate.confidence,
                )
        if driver not in seen:
            # The driver value is stamped on every record by the runner; declare it so it can
            # be the record key and appear in the output.
            fields.insert(
                0,
                FieldSpec(
                    key=driver,
                    name=draft.driver_prompt or driver,
                    required=True,
                    semantic=[draft.driver_prompt or driver],
                    source=SourcePage.DETAIL,
                ),
            )
            seen.add(driver)

        learned_table: LearnedTable | None = None
        if draft.table is not None:
            # Row fields: one record per table row; page fields above are copied onto each row.
            columns: dict[str, int] = {}
            for position, candidate in enumerate(draft.table.columns):
                if candidate.key in seen:
                    raise ValueError(f"表格列 {candidate.key} 与页面字段重名，请改名后再创建")
                seen.add(candidate.key)
                fields.append(
                    FieldSpec(
                        key=candidate.key,
                        name=candidate.name,
                        type=candidate.type,
                        required=candidate.key in required,
                        semantic=_unique([candidate.name, *candidate.aliases]),
                        source=SourcePage.DETAIL,
                    )
                )
                learned.field_mappings[candidate.key] = LearnedMapping(
                    page=SourcePage.DETAIL,
                    strategy="table_header",
                    hints=_unique([candidate.name, *candidate.aliases]),
                    confidence=candidate.confidence,
                )
                columns[candidate.key] = (
                    candidate.column if candidate.column is not None else position
                )
            if ROW_NO_KEY not in seen:
                fields.append(
                    FieldSpec(
                        key=ROW_NO_KEY,
                        name="行号",
                        type=FieldType.INTEGER,
                        required=True,
                        semantic=["行号", "序号"],
                        source=SourcePage.DETAIL,
                    )
                )
                seen.add(ROW_NO_KEY)
            if ROW_NO_KEY not in record_key:
                record_key.append(ROW_NO_KEY)
            learned_table = LearnedTable(
                index=draft.table.index,
                title=draft.table.title[:100],
                headers=list(draft.table.headers),
                columns=columns,
            )
        missing_keys = [key for key in record_key if key not in {field.key for field in fields}]
        if missing_keys:
            raise ValueError(f"record_key 引用了未选择的字段：{', '.join(missing_keys)}")

        attachments: list[AttachmentSpec] = []
        for item in draft.attachments:
            attachments.append(
                AttachmentSpec(
                    key=item.key,
                    name=item.name,
                    required=False,
                    semantic=[item.name],
                    source=SourcePage.DETAIL,
                    per_record=True,
                    multiple=item.count > 1,
                    match_by=record_key,
                    file_types=list(item.types),
                    filename_pattern="{" + driver + "}_{original_name}",
                    destination_subdir=f"attachments/{item.key}",
                )
            )
            learned.attachment_mappings[item.key] = LearnedMapping(
                page=SourcePage.DETAIL,
                strategy="semantic",
                hints=[item.name],
                confidence=item.confidence,
            )

        url_template = (draft.url_template or "").strip() or None
        if url_template and driver not in _PLACEHOLDER.findall(url_template):
            raise ValueError(f"url_template 必须包含 {{{driver}}} 占位符")

        run_overrides = {k: v for k, v in draft.run.items() if k in _ALLOWED_RUN_KEYS}
        if draft.table is not None:
            run_overrides["capture_tables"] = True
        run = RunSpec(mode=RunMode.DETAIL_BATCH, driver_variable=driver, **run_overrides)

        first_segment = urlsplit(str(draft.sample_url)).path.strip("/").split("/")[0]
        login_signals = [SignalSpec(semantic_element="退出登录")]
        if first_segment and not _PLACEHOLDER.search(first_segment):
            login_signals.append(SignalSpec(url_contains=f"/{first_segment}"))

        prompt = (
            draft.driver_prompt
            or f"请输入{fields[0].name}（多个值用换行分隔，或直接粘贴详情页地址）"
        )
        variable = VariableSpec(
            type=VariableType.STRING,
            required=True,
            multiple=True,
            prompt=prompt[:200],
            validation=VariableValidation(regex=draft.driver_regex) if draft.driver_regex else None,
        )
        return BrowserTemplate(
            schema_version="2.0",
            template_id=draft.template_id,
            name=draft.name,
            description=draft.description,
            status=TemplateStatus.DRAFT,
            version=version,
            system=SystemSpec(
                entry_url=draft.sample_url,
                allowed_hosts=[host],
                url_template=url_template,
            ),
            auth=AuthSpec(
                login_check=LoginCheckSpec(any=login_signals),
                unauthenticated_signals=[
                    SignalSpec(semantic_element="登录"),
                    SignalSpec(semantic_element="用户名"),
                ],
            ),
            variables={driver: variable},
            run=run,
            target=TargetSpec(fields=fields, attachments=attachments, record_key=record_key),
            learned=LearnedSpec(
                page_hints=list(draft.page_hints),
                field_mappings=learned.field_mappings,
                attachment_mappings=learned.attachment_mappings,
                table=learned_table,
            ),
            validation=ValidationSpec(min_records=0),
            output=OutputSpec(
                columns=[field.key for field in fields],
                filename_pattern=draft.template_id,
            ),
        )


def _unique(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        cleaned = value.strip()
        if cleaned and cleaned not in out:
            out.append(cleaned)
    return out
