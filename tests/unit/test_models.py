from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from browser_skill.models import BrowserTemplate


def test_example_template_is_valid(template_data: dict[str, object]) -> None:
    template = BrowserTemplate.model_validate(template_data)
    assert template.template_id == "inventory_feedback"
    assert template.target.record_key == ["sn"]


def test_unknown_template_property_is_rejected(template_data: dict[str, object]) -> None:
    data = deepcopy(template_data)
    data["surprise"] = True
    with pytest.raises(ValidationError):
        BrowserTemplate.model_validate(data)


def test_per_record_attachment_requires_record_key(template_data: dict[str, object]) -> None:
    data = deepcopy(template_data)
    data["target"]["record_key"] = []  # type: ignore[index]
    with pytest.raises(ValidationError, match="record_key"):
        BrowserTemplate.model_validate(data)


def test_workflow_dom_hint_accepts_only_selector_or_xpath(template_data: dict[str, object]) -> None:
    safe = deepcopy(template_data)
    safe["workflow"]["hints"][0]["dom_hint"] = "xpath=//a[@data-page='inventory']"  # type: ignore[index]
    assert BrowserTemplate.model_validate(safe).workflow.hints[0].dom_hint.startswith("xpath=")

    unsafe = deepcopy(template_data)
    unsafe["workflow"]["hints"][0]["dom_hint"] = "javascript:stealCookies()"  # type: ignore[index]
    with pytest.raises(ValidationError, match="dom_hint"):
        BrowserTemplate.model_validate(unsafe)
