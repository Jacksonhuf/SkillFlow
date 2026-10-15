from __future__ import annotations

from browser_skill.models import DeliveryChannelSpec, DeliverySpec
from browser_skill.pipeline.deliver import delivery_channel_summaries, delivery_spec_from_webhook


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


def test_delivery_spec_from_webhook_builds_channel() -> None:
    spec = delivery_spec_from_webhook("https://hook.example/run", "s3cr3t")
    assert spec.enabled is True
    assert len(spec.channels) == 1
    assert spec.channels[0].target == "https://hook.example/run"
    assert spec.channels[0].options.get("webhook_secret") == "s3cr3t"


def test_delivery_spec_from_webhook_disable_clears() -> None:
    assert delivery_spec_from_webhook("https://x", "y", disable=True).enabled is False
    assert delivery_spec_from_webhook("", None).enabled is False


def test_delivery_spec_from_webhook_rejects_bad_scheme() -> None:
    import pytest

    with pytest.raises(ValueError, match="http"):
        delivery_spec_from_webhook("ftp://bad", None)
