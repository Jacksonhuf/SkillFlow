from __future__ import annotations

from browser_skill.models import DeliveryChannelSpec, DeliverySpec
from browser_skill.templates.detail import template_detail_dict


def test_template_detail_dict_masks_webhook_secret(template_data: dict[str, object]) -> None:
    from browser_skill.models import BrowserTemplate

    data = dict(template_data)
    data["delivery"] = DeliverySpec(
        enabled=True,
        channels=[
            DeliveryChannelSpec(
                type="webhook",
                target="https://hook.example/",
                enabled=True,
                options={"webhook_secret": "hidden"},
            )
        ],
    )
    template = BrowserTemplate.model_validate(data)
    detail = template_detail_dict(template)
    assert detail["delivery_channels"][0]["shared_secret_configured"] is True
    assert "hidden" not in str(detail)
