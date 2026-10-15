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
    assert "update-delivery" in response.data.get("cli", "")
    assert "invoke.py update-delivery" in response.data.get("invoke_cli", "")
    channels = response.data["delivery_channels"]
    assert channels[0]["target"] == "https://hooks.example/skillflow"
    assert channels[0]["shared_secret_configured"] is True
    reloaded = store.load(str(data["template_id"]), 2, require_published=False)
    assert reloaded.delivery.enabled is True
    assert reloaded.report.enabled is True


def test_update_delivery_clear_webhook_secret(tmp_path, template_data: dict[str, object]) -> None:
    from browser_skill.models import DeliveryChannelSpec, DeliverySpec

    data = deepcopy(template_data)
    data["status"] = TemplateStatus.DRAFT
    data["version"] = 2
    data["delivery"] = DeliverySpec(
        enabled=True,
        channels=[
            DeliveryChannelSpec(
                type="webhook",
                target="https://hooks.example/old",
                enabled=True,
                options={"webhook_secret": "old-secret"},
            )
        ],
    )
    store = TemplateStore(tmp_path / "templates")
    store.save(BrowserTemplate.model_validate(data))
    app = BrowserSkillApp(tmp_path / "templates", tmp_path / "runs", FakeBrowserAdapter())
    response = asyncio.run(
        app.handle(
            SkillRequest(
                action="update_delivery",
                template_id=str(data["template_id"]),
                version=2,
                webhook_url="https://hooks.example/old",
                clear_webhook_secret=True,
            )
        )
    )
    assert response.ok is True
    assert response.data["delivery_channels"][0]["shared_secret_configured"] is False
    reloaded = store.load(str(data["template_id"]), 2, require_published=False)
    assert reloaded.delivery.channels[0].options.get("webhook_secret") is None


def test_update_delivery_rejects_published_without_fork(
    tmp_path, template_data: dict[str, object]
) -> None:
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
    assert "fork" in response.message.casefold()


def test_update_delivery_fork_from_published(tmp_path, template_data: dict[str, object]) -> None:
    store = TemplateStore(tmp_path / "templates")
    store.save(BrowserTemplate.model_validate(template_data))
    app = BrowserSkillApp(tmp_path / "templates", tmp_path / "runs", FakeBrowserAdapter())
    response = asyncio.run(
        app.handle(
            SkillRequest(
                action="update_delivery",
                template_id=str(template_data["template_id"]),
                version=1,
                webhook_url="https://hooks.example/forked",
                fork_as_new_version=True,
            )
        )
    )
    assert response.ok is True
    assert response.data["version"] == 2
    assert response.data["forked_from_version"] == 1
    draft = store.load(str(template_data["template_id"]), 2, require_published=False)
    assert draft.status == TemplateStatus.DRAFT
    assert draft.delivery.channels[0].target == "https://hooks.example/forked"
    published = store.load(str(template_data["template_id"]), 1, require_published=True)
    assert published.delivery.enabled is False
