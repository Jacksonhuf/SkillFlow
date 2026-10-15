from __future__ import annotations

import asyncio
from copy import deepcopy

from browser_skill.app import BrowserSkillApp
from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.models import BrowserTemplate, SkillRequest, TemplateStatus
from browser_skill.templates.store import TemplateStore


def test_update_delivery_on_draft(tmp_path, template_data: dict[str, object]) -> None:
    data = deepcopy(template_data)
    data["status"] = TemplateStatus.DRAFT
    data["version"] = 2
    store = TemplateStore(tmp_path / "templates")
    store.save(BrowserTemplate.model_validate(data))
    app = BrowserSkillApp(tmp_path / "templates", tmp_path / "runs", FakeBrowserAdapter())
    response = asyncio.run(
        app.handle(
            SkillRequest(
                action="update_delivery",
                template_id=str(data["template_id"]),
                version=2,
                webhook_url="https://hooks.example/skillflow",
                webhook_secret="rotate-me",
            )
        )
    )
    assert response.ok is True
    channels = response.data["delivery_channels"]
    assert channels[0]["target"] == "https://hooks.example/skillflow"
    assert channels[0]["shared_secret_configured"] is True
    reloaded = store.load(str(data["template_id"]), 2, require_published=False)
    assert reloaded.delivery.enabled is True
    assert reloaded.report.enabled is True


def test_update_delivery_rejects_published(tmp_path, template_data: dict[str, object]) -> None:
    store = TemplateStore(tmp_path / "templates")
    store.save(BrowserTemplate.model_validate(template_data))
    app = BrowserSkillApp(tmp_path / "templates", tmp_path / "runs", FakeBrowserAdapter())
    response = asyncio.run(
        app.handle(
            SkillRequest(
                action="update_delivery",
                template_id=str(template_data["template_id"]),
                version=1,
                webhook_url="https://hooks.example/x",
            )
        )
    )
    assert response.ok is False
    assert "发布" in response.message
