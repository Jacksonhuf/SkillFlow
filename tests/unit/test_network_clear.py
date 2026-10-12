from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.runtime.runner import Runner


def test_runner_delegates_clear_network_log_to_adapter() -> None:
    adapter = FakeBrowserAdapter()

    async def run() -> None:
        await Runner(adapter, Path("/tmp/runs"))._clear_network_log()

    asyncio.run(run())
    assert ("clear_network_log", (), {}) in adapter.calls


def test_playwright_clear_network_log_empties_buffer() -> None:
    pytest.importorskip("playwright")
    from browser_skill.browser.playwright_adapter import PlaywrightAdapter

    adapter = PlaywrightAdapter()
    adapter._network.append({"url": "https://example.internal/x", "method": "GET"})
    asyncio.run(adapter.clear_network_log())
    assert len(adapter._network) == 0
