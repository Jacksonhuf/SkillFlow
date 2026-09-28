from browser_skill.models import RunState
from browser_skill.runtime.test_evidence import accepts_test_run_evidence


def test_completed_summary_accepted() -> None:
    summary = {"template": "demo@1", "state": RunState.COMPLETED.value}
    assert accepts_test_run_evidence(summary, expected_template="demo@1")


def test_partial_with_ok_validation_accepted() -> None:
    summary = {
        "template": "demo@1",
        "state": RunState.PARTIAL.value,
        "validation": {"ok": True, "partial": True},
    }
    assert accepts_test_run_evidence(summary, expected_template="demo@1")


def test_partial_without_ok_validation_rejected() -> None:
    summary = {
        "template": "demo@1",
        "state": RunState.PARTIAL.value,
        "validation": {"ok": False},
    }
    assert not accepts_test_run_evidence(summary, expected_template="demo@1")


def test_wrong_template_rejected() -> None:
    summary = {"template": "other@2", "state": RunState.COMPLETED.value}
    assert not accepts_test_run_evidence(summary, expected_template="demo@1")
