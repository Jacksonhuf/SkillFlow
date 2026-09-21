import asyncio
import json
import os
from pathlib import Path

import pytest

from browser_skill.browser.chrome_use import ChromeUseAdapter, ChromeUseToolAdapter
from browser_skill.platform.probe import probe_adapter


@pytest.mark.integration
def test_live_chrome_use_cli_probe_when_enabled() -> None:
    if os.environ.get("BROWSER_SKILL_CHROME_USE_INTEGRATION") != "1":
        pytest.skip("Set BROWSER_SKILL_CHROME_USE_INTEGRATION=1 to run live chrome-use probes")
    report = asyncio.run(probe_adapter(ChromeUseAdapter(), mode="local_cli"))
    assert report.text


@pytest.mark.integration
def test_recorded_platform_fixture_still_matches_contract() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[2]
        / "fixtures"
        / "platform"
        / "reference-capability-response.json"
    )
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))

    async def invoke(_tool: str, arguments: dict[str, object]) -> dict[str, object]:
        if arguments.get("operation") == "status":
            return {"ok": True}
        if arguments.get("operation") == "capabilities":
            return payload
        return {"ok": True}

    report = asyncio.run(probe_adapter(ChromeUseToolAdapter(invoke), mode="platform_tool"))
    assert report.ready is True
