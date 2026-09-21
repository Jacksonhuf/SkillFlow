from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import HttpUrl

from browser_skill.models import (
    AttachmentSpec,
    AuthSpec,
    BrowserTemplate,
    FieldSpec,
    LearnedSpec,
    LoginCheckSpec,
    OutputSpec,
    SignalSpec,
    SystemSpec,
    TargetSpec,
    TemplateStatus,
    VariableSpec,
)


class TeachCompiler:
    """Compile a safe editable draft; exploration/publish remains an explicit tested step."""

    def compile_draft(
        self,
        *,
        template_id: str,
        name: str,
        entry_url: str,
        fields: Sequence[dict[str, Any] | FieldSpec],
        attachments: Sequence[dict[str, Any] | AttachmentSpec] = (),
        variables: dict[str, VariableSpec] | None = None,
        record_key: Sequence[str] = (),
        page_hints: Sequence[str] = (),
        description: str = "",
        version: int = 1,
    ) -> BrowserTemplate:
        field_specs = [
            field if isinstance(field, FieldSpec) else FieldSpec.model_validate(field)
            for field in fields
        ]
        attachment_specs = [
            item if isinstance(item, AttachmentSpec) else AttachmentSpec.model_validate(item)
            for item in attachments
        ]
        parsed_url = HttpUrl(entry_url)
        host = parsed_url.host or ""
        return BrowserTemplate(
            template_id=template_id,
            name=name,
            description=description,
            status=TemplateStatus.DRAFT,
            version=version,
            system=SystemSpec(entry_url=parsed_url, allowed_hosts=[host]),
            auth=AuthSpec(
                login_check=LoginCheckSpec(any=[SignalSpec(semantic_element="退出登录")]),
                unauthenticated_signals=[SignalSpec(semantic_element="登录")],
            ),
            variables=variables or {},
            target=TargetSpec(
                fields=field_specs,
                attachments=attachment_specs,
                record_key=list(record_key),
            ),
            learned=LearnedSpec(page_hints=list(page_hints)),
            output=OutputSpec(columns=[field.key for field in field_specs]),
        )
