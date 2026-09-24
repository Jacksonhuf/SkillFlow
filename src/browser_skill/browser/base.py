from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from browser_skill.browser.snapshot_normalize import coerce_snapshot_elements
from browser_skill.models import BrowserCapabilities, BrowserSnapshot, CommandResult


class BrowserAdapter(Protocol):
    async def status(self) -> CommandResult: ...

    async def capabilities(self) -> BrowserCapabilities: ...

    async def open(self, url: str) -> CommandResult: ...

    async def adopt_tab(self, match: str) -> CommandResult: ...

    async def list_tabs(self) -> CommandResult: ...

    async def snapshot(
        self, *, interactive: bool = True, diff: bool = False
    ) -> BrowserSnapshot: ...

    async def find(self, description: str) -> CommandResult: ...

    async def click(self, target: str, *, observe: bool = True) -> CommandResult: ...

    async def fill(self, target: str, value: str, *, sensitive: bool = False) -> CommandResult: ...

    async def type(self, target: str, value: str, *, sensitive: bool = False) -> CommandResult: ...

    async def get_actions(self, target: str) -> CommandResult: ...

    async def do_action(self, target: str, action: str) -> CommandResult: ...

    async def download(self, target: str, path: Path) -> CommandResult: ...

    async def list_downloads(self) -> CommandResult: ...

    async def get_dialog_status(self) -> CommandResult: ...

    async def accept_dialog(self) -> CommandResult: ...

    async def dismiss_dialog(self) -> CommandResult: ...

    async def list_sessions(self) -> CommandResult: ...

    async def network_requests(self) -> CommandResult: ...


class ScreenshotCapable(Protocol):
    """Optional extension used by the vision fallback; adapters may omit it."""

    async def screenshot(self) -> CommandResult: ...


def snapshot_from_data(data: Any) -> BrowserSnapshot:
    if isinstance(data, BrowserSnapshot):
        return data
    if isinstance(data, dict):
        elements = coerce_snapshot_elements(data)
        aliases = {
            "url": str(data.get("url", data.get("page_url", ""))),
            "title": str(data.get("title", "")),
            "text": str(data.get("text", data.get("snapshot", data.get("content", "")))),
            "elements": elements,
            "records": data.get("records", []),
            "tables": [
                item
                for item in (data.get("tables") or [])
                if isinstance(item, dict) and isinstance(item.get("rows"), list)
            ],
        }
        if not aliases["text"] and isinstance(data.get("snapshot"), str):
            aliases["text"] = data["snapshot"]
        return BrowserSnapshot.model_validate(aliases)
    return BrowserSnapshot(text=str(data))
