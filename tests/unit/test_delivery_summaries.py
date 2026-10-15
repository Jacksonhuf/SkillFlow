from __future__ import annotations

from browser_skill.models import DeliveryChannelSpec, DeliverySpec
from browser_skill.pipeline.deliver import delivery_channel_summaries


def test_delivery_channel_summaries_masks_webhook_secret() -> None:
    spec = DeliverySpec(
        enabled=True,
        channels=[
            DeliveryChannelSpec(
                type="webhook",
                target="http://127.0.0.1:1/hook",
                enabled=True,
                options={"webhook_secret": "hidden"},
            ),
        ],
    )
    rows = delivery_channel_summaries(spec)
    assert rows == [
        {
            "type": "webhook",
            "target": "http://127.0.0.1:1/hook",
            "shared_secret_configured": True,
        }
    ]
    assert "hidden" not in str(rows)
