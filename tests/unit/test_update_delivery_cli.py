from __future__ import annotations

from browser_skill.app import _update_delivery_cli
from browser_skill.models import DeliveryChannelSpec, DeliverySpec, SkillRequest


def test_update_delivery_cli_enable() -> None:
    delivery = DeliverySpec(
        enabled=True,
        channels=[
            DeliveryChannelSpec(
                type="webhook",
                target="https://hooks.example/h",
                enabled=True,
                options={},
            )
        ],
    )
    request = SkillRequest(
        action="update_delivery",
        template_id="demo_tpl",
        version=3,
    )
    cli = _update_delivery_cli(request, delivery)
    assert cli == "browser-skill update-delivery demo_tpl --version 3 --webhook-url https://hooks.example/h"


def test_update_delivery_cli_fork_flag() -> None:
    request = SkillRequest(
        action="update_delivery",
        template_id="demo_tpl",
        version=1,
        fork_as_new_version=True,
    )
    cli = _update_delivery_cli(request, DeliverySpec())
    assert "--fork" in cli


def test_update_delivery_cli_disable() -> None:
    request = SkillRequest(
        action="update_delivery",
        template_id="demo_tpl",
        version=1,
        disable_delivery=True,
    )
    cli = _update_delivery_cli(request, DeliverySpec())
    assert cli == "browser-skill update-delivery demo_tpl --version 1 --disable"
