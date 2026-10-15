from __future__ import annotations

import asyncio

from browser_skill.browser.chrome_use import (
    chrome_use_operations_payload,
    enrich_chrome_use_capabilities_payload,
)
from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.models import BrowserCapabilities, CommandResult
from browser_skill.platform.probe import probe_adapter


def test_chrome_use_operations_marks_teach_false() -> None:
    caps = BrowserCapabilities(network=True)
    ops = chrome_use_operations_payload(caps)
    assert ops["network.list"] is True
    assert ops["probe.pick_start"] is False
    assert ops["probe.list_nav_start"] is False


def test_enrich_payload_adds_operations_when_absent() -> None:
    caps = BrowserCapabilities(network=False)
    payload = enrich_chrome_use_capabilities_payload({"snapshot": True}, caps)
    assert payload["engine"] == "chrome-use"
    assert payload["operations"]["probe.pick_start"] is False


def test_local_cli_probe_reports_chrome_use_teach_gaps() -> None:
    adapter = FakeBrowserAdapter(
        {
            "status": [CommandResult(ok=True, operation="status")],
            "capabilities": [BrowserCapabilities(network=True, snapshot=True, find=True)],
            "capabilities_payload": [
                enrich_chrome_use_capabilities_payload(
                    {"snapshot": True, "network": True},
                    BrowserCapabilities(network=True, snapshot=True),
                )
            ],
        }
    )

    report = asyncio.run(probe_adapter(adapter, mode="local_cli"))
    assert "probe.pick_start" in report.missing_recommended_operations
    assert "network.list" not in report.missing_recommended_operations
