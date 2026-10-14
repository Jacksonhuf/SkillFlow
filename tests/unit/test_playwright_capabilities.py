from __future__ import annotations

import asyncio

from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.browser.playwright_adapter import _PLAYWRIGHT_OPERATIONS, PlaywrightAdapter
from browser_skill.platform.probe import probe_adapter


def test_playwright_capabilities_payload_declares_teach_operations() -> None:
    adapter = PlaywrightAdapter()
    payload = asyncio.run(adapter.capabilities_payload())
    operations = payload.get("operations")
    assert isinstance(operations, dict)
    for key in _PLAYWRIGHT_OPERATIONS:
        assert operations.get(key) is True


def test_local_cli_probe_uses_operations_for_recommended_teach_ops() -> None:
    report = asyncio.run(probe_adapter(FakeBrowserAdapter(), mode="local_cli"))
    assert report.missing_recommended_operations == []
