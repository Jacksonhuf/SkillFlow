from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

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


def snapshot_from_data(data: Any) -> BrowserSnapshot:
    if isinstance(data, BrowserSnapshot):
        return data
    if isinstance(data, dict):
        aliases = {
            "url": data.get("url", ""),
            "title": data.get("title", ""),
            "text": data.get("text", data.get("snapshot", "")),
            "elements": data.get("elements", []),
            "records": data.get("records", []),
        }
        return BrowserSnapshot.model_validate(aliases)
    return BrowserSnapshot(text=str(data))
