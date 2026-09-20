from datetime import date, timedelta

import pytest

from browser_skill.errors import ErrorCode, SkillError
from browser_skill.interaction.variables import VariableResolver


def test_resolves_relative_date_default(template) -> None:
    values = VariableResolver().resolve(template, {})
    assert values["date"] == (date.today() - timedelta(days=1)).isoformat()


def test_unknown_variable_is_rejected(template) -> None:
    with pytest.raises(SkillError) as raised:
        VariableResolver().resolve(template, {"unknown": "x"})
    assert raised.value.code == ErrorCode.VARIABLE_INVALID


def test_sensitive_values_are_redacted(template) -> None:
    spec = template.variables["owner"].model_copy(update={"sensitive": True})
    template.variables["owner"] = spec
    assert VariableResolver().redacted(template, {"owner": "secret"}) == {"owner": "***"}
