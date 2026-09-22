from __future__ import annotations

from browser_skill.errors import ErrorCode, SkillError
from browser_skill.models import BrowserTemplate, LearnedSpec, TemplateStatus


class RepairService:
    """Create a candidate version while freezing the business contract."""

    def candidate(
        self,
        original: BrowserTemplate,
        learned: LearnedSpec,
        *,
        version: int | None = None,
    ) -> BrowserTemplate:
        if original.status == TemplateStatus.DISABLED:
            raise SkillError(ErrorCode.REPAIR_FAILED, "Disabled templates cannot be repaired")
        return original.model_copy(
            update={
                "version": version or original.version + 1,
                "status": TemplateStatus.TESTING,
                "learned": learned,
            },
            deep=True,
        )

    def contract_unchanged(self, original: BrowserTemplate, candidate: BrowserTemplate) -> bool:
        frozen = (
            "variables",
            "target",
            "validation",
            "output",
            "auth",
            "system",
            "processing",
            "analysis",
            "report",
            "delivery",
        )
        return all(getattr(original, key) == getattr(candidate, key) for key in frozen)
