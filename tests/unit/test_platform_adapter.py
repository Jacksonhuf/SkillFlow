import asyncio
from pathlib import Path
from typing import Any

import pytest

from browser_skill.browser.chrome_use import ChromeUseToolAdapter
from browser_skill.errors import SkillError


class RecordingInvoker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((tool, arguments))
        operation = arguments["operation"]
        if operation == "capabilities":
            return {
                "ok": True,
                "data": {"snapshot": True, "download": True, "unknown": True},
            }
        if operation == "snapshot":
            return {
                "ok": True,
                "data": {"url": "https://example.internal/home", "text": "退出登录"},
            }
        return {"ok": True, "data": {"operation": operation}}


def test_platform_adapter_uses_structured_tool_calls_without_shell() -> None:
    invoker = RecordingInvoker()
    adapter = ChromeUseToolAdapter(invoker)
    result = asyncio.run(adapter.open("https://example.internal"))
    assert result.ok
    assert invoker.calls == [
        (
            "chrome-use",
            {"operation": "open", "url": "https://example.internal"},
        )
    ]


def test_platform_adapter_normalizes_capabilities_and_snapshot() -> None:
    invoker = RecordingInvoker()
    adapter = ChromeUseToolAdapter(invoker, tool_name="company.chrome-use")
    capabilities = asyncio.run(adapter.capabilities())
    snapshot = asyncio.run(adapter.snapshot(interactive=True, diff=False))
    assert capabilities.snapshot is True
    assert capabilities.download is True
    assert snapshot.url == "https://example.internal/home"
    assert all(call[0] == "company.chrome-use" for call in invoker.calls)


def test_platform_download_passes_contained_path_as_data(tmp_path: Path) -> None:
    invoker = RecordingInvoker()
    adapter = ChromeUseToolAdapter(invoker)
    target = tmp_path / "attachments" / "evidence.pdf"
    asyncio.run(adapter.download("attachment", target))
    assert invoker.calls[0][1] == {
        "operation": "download",
        "target": "attachment",
        "path": str(target),
    }


def test_platform_adapter_rejects_malformed_response() -> None:
    async def malformed(_tool: str, _arguments: dict[str, Any]) -> Any:
        return ["not", "an", "object"]

    with pytest.raises(SkillError, match="invalid response"):
        asyncio.run(ChromeUseToolAdapter(malformed).status())


def test_platform_adapter_normalizes_invoker_failure_without_leaking_exception() -> None:
    async def failing(_tool: str, _arguments: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("authorization=secret-value")

    with pytest.raises(SkillError) as raised:
        asyncio.run(ChromeUseToolAdapter(failing).snapshot())

    assert raised.value.code.value == "E_CHROME_USE_UNAVAILABLE"
    assert "secret-value" not in raised.value.message
