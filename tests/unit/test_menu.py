from browser_skill.errors import ErrorCode, SkillError
from browser_skill.interaction.template_menu import TemplateMenu
from browser_skill.models import TemplateStatus
from browser_skill.templates.store import TemplateSummary


def item(template_id: str, name: str) -> TemplateSummary:
    return TemplateSummary(template_id, 1, name, "", TemplateStatus.PUBLISHED)


def test_menu_resolves_id_index_name_and_create() -> None:
    menu = TemplateMenu([item("sales_report", "销售日报"), item("inventory", "样机盘点")])
    assert menu.resolve("inventory") == "inventory"
    assert menu.resolve(1) == "sales_report"
    assert menu.resolve("样机盘点") == "inventory"
    assert menu.resolve(3) is None


def test_menu_rejects_unknown_selector() -> None:
    menu = TemplateMenu([item("sales_report", "销售日报")])
    try:
        menu.resolve("completely unrelated")
    except SkillError as exc:
        assert exc.code == ErrorCode.TEMPLATE_NOT_FOUND
    else:
        raise AssertionError("expected a SkillError")
