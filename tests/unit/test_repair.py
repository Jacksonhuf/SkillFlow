from browser_skill.models import LearnedSpec, TemplateStatus
from browser_skill.runtime.repair import RepairService


def test_repair_increments_version_and_freezes_contract(template) -> None:
    candidate = RepairService().candidate(template, LearnedSpec(page_hints=["new page"]))
    assert candidate.version == template.version + 1
    assert candidate.status == TemplateStatus.TESTING
    assert RepairService().contract_unchanged(template, candidate)
