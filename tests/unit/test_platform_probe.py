import asyncio
import json
from pathlib import Path
from typing import Any

from browser_skill.app import BrowserSkillApp
from browser_skill.browser.chrome_use import ChromeUseToolAdapter
from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.models import BrowserCapabilities, CommandResult, SkillRequest
from browser_skill.platform.acceptance import validate_acceptance_bundle
from browser_skill.platform.probe import default_contract_path, load_minimum_contract, probe_adapter


def test_minimum_contract_fixture_is_loadable() -> None:
    contract = load_minimum_contract()
    assert contract["schema_version"] == "1.0"
    assert "snapshot" in contract["required_capability_flags"]
    assert default_contract_path().exists()


def test_probe_passes_with_reference_platform_payload() -> None:
    fixture = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "fixtures"
            / "platform"
            / "reference-capability-response.json"
        ).read_text(encoding="utf-8")
    )

    async def invoke(_tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if arguments["operation"] == "status":
            return {"ok": True, "data": {"ready": True}}
        if arguments["operation"] == "capabilities":
            return fixture
        return {"ok": True, "data": {}}

    report = asyncio.run(
        probe_adapter(ChromeUseToolAdapter(invoke), mode="platform_tool")
    )
    assert report.ready is True
    assert report.missing_capability_flags == []
    assert report.missing_operations == []
    assert report.text


def test_probe_fails_when_operations_missing() -> None:
    async def invoke(_tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if arguments["operation"] == "status":
            return {"ok": True}
        if arguments["operation"] == "capabilities":
            return {
                "ok": True,
                "data": {
                    "snapshot": True,
                    "find": True,
                    "download": True,
                    "downloads": True,
                    "tabs": True,
                    "dialogs": True,
                    "operations": {"status": True},
                },
            }
        return {"ok": True}

    report = asyncio.run(probe_adapter(ChromeUseToolAdapter(invoke), mode="platform_tool"))
    assert report.ready is False
    assert report.missing_operations


def test_sample_acceptance_bundle_validates() -> None:
    bundle = (
        Path(__file__).resolve().parents[2]
        / "fixtures"
        / "platform"
        / "sample-acceptance-bundle.json"
    )
    result = validate_acceptance_bundle(bundle, require_sign_off=True)
    assert result.ok is True
    assert result.errors == []


def test_app_probe_action_returns_interaction(tmp_path: Path) -> None:
    adapter = FakeBrowserAdapter(
        {
            "status": [CommandResult(ok=True, operation="status")],
            "capabilities": [
                BrowserCapabilities(
                    snapshot=True,
                    find=True,
                    download=True,
                    downloads=True,
                    tabs=True,
                    dialogs=True,
                )
            ],
        }
    )
    app = BrowserSkillApp(tmp_path / "templates", tmp_path / "runs", adapter)
    response = asyncio.run(app.handle(SkillRequest(action="probe", probe_mode="platform_tool")))
    assert response.data["interaction"]["kind"] == "platform_probe"
    assert response.data["interaction"]["text"]
    assert response.ok is True
