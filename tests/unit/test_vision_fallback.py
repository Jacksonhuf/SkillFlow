from __future__ import annotations

import asyncio
import base64
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from browser_skill.acquire.vision import (
    NullVisionProvider,
    ScriptedVisionProvider,
    VisionFallback,
    VisionTarget,
    decode_screenshot,
    parse_xy_target,
)
from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.errors import SkillError
from browser_skill.models import BrowserSnapshot, BrowserTemplate, CommandResult, RunState
from browser_skill.runtime.locator import LocatorService
from browser_skill.runtime.runner import Runner


def test_xy_target_round_trip_and_screenshot_decoding() -> None:
    assert VisionTarget(x=12.4, y=300.6, confidence=0.9).target == "xy:12,301"
    assert parse_xy_target("xy:12,301") == (12.0, 301.0)
    assert parse_xy_target("@e12") is None
    raw = b"\x89PNG\r\n"
    encoded = base64.b64encode(raw).decode("ascii")
    assert decode_screenshot(CommandResult(ok=True, operation="s", data=raw)) == (raw, None)
    assert decode_screenshot(
        CommandResult(
            ok=True, operation="s", data={"png_base64": encoded, "width": 1280, "height": 720}
        )
    ) == (raw, (1280, 720))
    assert decode_screenshot(CommandResult(ok=False, operation="s", data=raw)) is None


def test_locator_uses_vision_only_after_dom_strategies_fail() -> None:
    provider = ScriptedVisionProvider({"查询": VisionTarget(x=100, y=40, confidence=0.9)})
    locator = LocatorService(vision=VisionFallback(provider))
    adapter = FakeBrowserAdapter()

    located = asyncio.run(locator.locate(adapter, BrowserSnapshot(), ["查询"]))

    assert located is not None
    assert located.strategy == "vision" and located.target == "xy:100,40"
    assert provider.calls == [("查询", len(b"\x89PNG fake"))]
    assert any(call[0] == "find" for call in adapter.calls)  # semantic find tried first
    assert any(call[0] == "screenshot" for call in adapter.calls)


def test_locator_prefers_snapshot_match_over_vision() -> None:
    provider = ScriptedVisionProvider({"查询": VisionTarget(x=1, y=1, confidence=1.0)})
    locator = LocatorService(vision=VisionFallback(provider))
    located = asyncio.run(
        locator.locate(
            FakeBrowserAdapter(),
            BrowserSnapshot(elements=[{"text": "查询", "ref": "@q"}]),
            ["查询"],
        )
    )
    assert located is not None and located.target == "@q"
    assert provider.calls == []


def test_low_confidence_or_null_provider_keeps_domain_error() -> None:
    weak = ScriptedVisionProvider({"查询": VisionTarget(x=1, y=1, confidence=0.2)})
    fallback = VisionFallback(weak, min_confidence=0.6)
    with pytest.raises(SkillError) as info:
        asyncio.run(
            LocatorService(vision=fallback).locate(
                FakeBrowserAdapter(), BrowserSnapshot(), ["查询"]
            )
        )
    assert info.value.code.value == "E_ELEMENT_NOT_FOUND"
    assert fallback.attempts[-1]["outcome"] == "rejected"

    inert = LocatorService(vision=VisionFallback(NullVisionProvider()))
    adapter = FakeBrowserAdapter()
    with pytest.raises(SkillError):
        asyncio.run(inert.locate(adapter, BrowserSnapshot(), ["查询"]))
    assert not any(call[0] == "screenshot" for call in adapter.calls)


def test_fallback_without_screenshot_capability_is_skipped() -> None:
    class NoScreenshot(FakeBrowserAdapter):
        screenshot = None  # type: ignore[assignment]

    fallback = VisionFallback(ScriptedVisionProvider({"x": VisionTarget(1, 1, 1.0)}))
    assert asyncio.run(fallback.locate(NoScreenshot(), "x")) is None
    assert fallback.attempts == [{"hint": "x", "outcome": "no_screenshot_capability"}]


def test_runner_reports_vision_attempts_in_execution_log(
    tmp_path: Path, template_data: dict[str, Any]
) -> None:
    data = deepcopy(template_data)
    data["target"]["attachments"] = []
    # Only the query button remains; it is not in the snapshot, so DOM strategies fail.
    data["workflow"]["hints"] = [{"action": "query", "target": "查询"}]
    template = BrowserTemplate.model_validate(data)
    adapter = FakeBrowserAdapter(
        {
            "snapshot": [
                BrowserSnapshot(
                    url="https://example.internal/home",
                    text="退出登录 样机盘点反馈",
                    records=[{"sample_id": "S-1", "sn": "SN-1", "product_model": "P"}],
                )
            ]
        }
    )
    provider = ScriptedVisionProvider({"查询": VisionTarget(x=640, y=120, confidence=0.8)})

    response = asyncio.run(Runner(adapter, tmp_path, vision_provider=provider).run(template, {}))

    assert response.ok and response.state == RunState.COMPLETED
    assert ("click", ("xy:640,120",), {"observe": True}) in adapter.calls
    events = [
        json.loads(line)
        for line in (tmp_path / str(response.run_id) / "execution.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    vision = [event for event in events if event["event"] == "vision_fallback"]
    assert len(vision) == 1
    assert vision[0]["provider"] == "scripted" and vision[0]["located"] == 1
    assert vision[0]["attempts"][0]["target"] == "xy:640,120"
