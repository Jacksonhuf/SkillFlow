import pytest

from browser_skill.errors import SkillError
from browser_skill.models import BrowserCapabilities, BrowserTemplate
from browser_skill.runtime.capability_requirements import (
    ensure_template_runtime_capabilities,
    missing_capabilities_for_template,
)


def test_missing_download_when_attachments_declared(template_data) -> None:
    template = BrowserTemplate.model_validate(template_data)
    caps = BrowserCapabilities(snapshot=True, find=True, download=False, downloads=True)
    missing = missing_capabilities_for_template(caps, template)
    assert "download" in missing


def test_ensure_raises_user_friendly_message(template_data) -> None:
    template = BrowserTemplate.model_validate(template_data)
    caps = BrowserCapabilities(snapshot=True, find=True, download=False, downloads=False)
    with pytest.raises(SkillError, match="浏览器环境"):
        ensure_template_runtime_capabilities(caps, template)


def test_no_missing_when_fully_capable(template_data) -> None:
    template = BrowserTemplate.model_validate(template_data)
    caps = BrowserCapabilities(
        snapshot=True, find=True, download=True, downloads=True, tabs=True
    )
    assert missing_capabilities_for_template(caps, template) == []
