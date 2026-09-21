from __future__ import annotations

from difflib import SequenceMatcher

from browser_skill.errors import ErrorCode, SkillError
from browser_skill.templates.store import TemplateSummary


class TemplateMenu:
    def __init__(self, templates: list[TemplateSummary]) -> None:
        self.templates = templates

    def indexed(self) -> list[tuple[int, TemplateSummary | None]]:
        return [(index, item) for index, item in enumerate(self.templates, 1)] + [
            (len(self.templates) + 1, None)
        ]

    def resolve(self, selector: str | int) -> str | None:
        text = str(selector).strip()
        by_id = {item.template_id: item for item in self.templates}
        if text in by_id:
            return text
        if text.isdigit():
            index = int(text)
            if index == len(self.templates) + 1:
                return None
            if 1 <= index <= len(self.templates):
                return self.templates[index - 1].template_id
        exact = [item for item in self.templates if item.name.casefold() == text.casefold()]
        if len(exact) == 1:
            return exact[0].template_id
        scored = sorted(
            (
                (SequenceMatcher(None, text.casefold(), item.name.casefold()).ratio(), item)
                for item in self.templates
            ),
            reverse=True,
            key=lambda pair: pair[0],
        )
        if scored and scored[0][0] >= 0.72:
            if len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.12:
                return scored[0][1].template_id
            raise SkillError(
                ErrorCode.TEMPLATE_SELECTOR_AMBIGUOUS, "Template selection is ambiguous"
            )
        raise SkillError(ErrorCode.TEMPLATE_NOT_FOUND, f"No template matches: {selector}")
