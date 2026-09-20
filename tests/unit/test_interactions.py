from copy import deepcopy

from browser_skill.interaction.contracts import (
    InteractionKind,
    auth_required_interaction,
    template_menu_interaction,
    variable_form_interaction,
)
from browser_skill.models import BrowserTemplate, TemplateStatus
from browser_skill.templates.store import TemplateSummary


def test_template_menu_is_platform_neutral_and_has_text_fallback() -> None:
    interaction = template_menu_interaction(
        [
            TemplateSummary(
                template_id="inventory_feedback",
                version=1,
                name="样机盘点反馈",
                description="下载盘点记录",
                status=TemplateStatus.PUBLISHED,
            )
        ]
    )
    assert interaction.kind == InteractionKind.TEMPLATE_MENU
    assert interaction.choices[0].value == "inventory_feedback"
    assert interaction.choices[-1].id == "create_template"
    assert "1. 样机盘点反馈" in interaction.text


def test_variable_form_contains_only_missing_required_fields(template_data) -> None:
    data = deepcopy(template_data)
    data["variables"]["date"].pop("default")
    template = BrowserTemplate.model_validate(data)
    interaction = variable_form_interaction(template, ["date"])
    assert interaction.kind == InteractionKind.VARIABLE_FORM
    assert [field.name for field in interaction.fields] == ["date"]
    assert interaction.text


def test_auth_interaction_is_resumable_without_requesting_credentials() -> None:
    interaction = auth_required_interaction("run_123", "unauthenticated")
    assert interaction.run_id == "run_123"
    assert "resume_run" in interaction.actions
    assert "密码" in interaction.text
    assert "提供密码" in interaction.text
