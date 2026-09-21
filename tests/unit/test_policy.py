import pytest

from browser_skill.errors import ErrorCode, SkillError
from browser_skill.runtime.policy import ActionPolicy


def test_high_risk_action_is_denied() -> None:
    with pytest.raises(SkillError) as raised:
        ActionPolicy().require_allowed("delete")
    assert raised.value.code == ErrorCode.ACTION_NOT_ALLOWED


def test_page_cannot_declare_unknown_action() -> None:
    with pytest.raises(SkillError):
        ActionPolicy().require_allowed("read", declared=False)
