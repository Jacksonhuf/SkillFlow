from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
from typing import Any, TypeVar, cast

from browser_skill.models import BrowserCapabilities, BrowserSnapshot, CommandResult

T = TypeVar("T")


class FakeBrowserAdapter:
    """Scriptable adapter used by component tests; each method consumes queued results."""

    def __init__(self, script: dict[str, list[Any]] | None = None) -> None:
        self.script: defaultdict[str, deque[Any]] = defaultdict(deque)
        for operation, values in (script or {}).items():
            self.script[operation].extend(values)
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _take(self, operation: str, default: T) -> T:
        self.calls.append((operation, (), {}))
        value = self.script[operation].popleft() if self.script[operation] else default
        if isinstance(value, BaseException):
            raise value
        return cast(T, value)

    async def status(self) -> CommandResult:
        return self._take("status", CommandResult(ok=True, operation="status"))

    async def capabilities(self) -> BrowserCapabilities:
        return self._take(
            "capabilities",
            BrowserCapabilities(snapshot=True, find=True, download=True, downloads=True, tabs=True),
        )

    async def capabilities_payload(self) -> dict[str, Any]:
        if self.script["capabilities_payload"]:
            raw = self.script["capabilities_payload"].popleft()
            return raw if isinstance(raw, dict) else {}
        caps = await self.capabilities()
        payload = caps.model_dump(mode="json")
        payload["operations"] = {
            "status": True,
            "capabilities": True,
            "open": True,
            "snapshot": True,
            "find": True,
            "click": True,
            "fill": True,
            "download": True,
            "downloads": True,
            "tab.list": True,
            "dialog.status": True,
        }
        return payload

    async def open(self, url: str) -> CommandResult:
        self.calls.append(("open", (url,), {}))
        return self._take("open_result", CommandResult(ok=True, operation="open", data=url))

    async def adopt_tab(self, match: str) -> CommandResult:
        self.calls.append(("adopt_tab", (match,), {}))
        return self._take("adopt_tab_result", CommandResult(ok=True, operation="adopt_tab"))

    async def list_tabs(self) -> CommandResult:
        return self._take("list_tabs", CommandResult(ok=True, operation="list_tabs", data=[]))

    async def snapshot(self, *, interactive: bool = True, diff: bool = False) -> BrowserSnapshot:
        self.calls.append(("snapshot_args", (), {"interactive": interactive, "diff": diff}))
        return self._take("snapshot", BrowserSnapshot())

    async def find(self, description: str) -> CommandResult:
        self.calls.append(("find", (description,), {}))
        return self._take("find_result", CommandResult(ok=False, operation="find"))

    async def click(self, target: str, *, observe: bool = True) -> CommandResult:
        self.calls.append(("click", (target,), {"observe": observe}))
        return self._take("click_result", CommandResult(ok=True, operation="click"))

    async def fill(self, target: str, value: str, *, sensitive: bool = False) -> CommandResult:
        self.calls.append(("fill", (target, value), {"sensitive": sensitive}))
        return self._take("fill_result", CommandResult(ok=True, operation="fill"))

    async def type(self, target: str, value: str, *, sensitive: bool = False) -> CommandResult:
        self.calls.append(("type", (target, value), {"sensitive": sensitive}))
        return self._take("type_result", CommandResult(ok=True, operation="type"))

    async def get_actions(self, target: str) -> CommandResult:
        return self._take("get_actions", CommandResult(ok=True, operation="actions", data=[]))

    async def do_action(self, target: str, action: str) -> CommandResult:
        return self._take("do_action", CommandResult(ok=True, operation="do"))

    async def download(
        self, target: str, path: Path, *, timeout_ms: int | None = None
    ) -> CommandResult:
        self.calls.append(("download", (target, path), {"timeout_ms": timeout_ms}))
        result = self._take("download_result", CommandResult(ok=True, operation="download"))
        if result.ok and not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fake download")
        return result

    async def list_downloads(self) -> CommandResult:
        return self._take("list_downloads", CommandResult(ok=True, operation="downloads", data=[]))

    async def get_dialog_status(self) -> CommandResult:
        return self._take("dialog_status", CommandResult(ok=True, operation="dialog"))

    async def accept_dialog(self) -> CommandResult:
        return self._take("dialog_accept", CommandResult(ok=True, operation="dialog"))

    async def dismiss_dialog(self) -> CommandResult:
        return self._take("dialog_dismiss", CommandResult(ok=True, operation="dialog"))

    async def list_sessions(self) -> CommandResult:
        return self._take("sessions", CommandResult(ok=True, operation="session", data=[]))

    async def network_requests(self) -> CommandResult:
        self.calls.append(("network_requests", (), {}))
        return self._take("network", CommandResult(ok=True, operation="network", data=[]))

    async def screenshot(self) -> CommandResult:
        self.calls.append(("screenshot", (), {}))
        return self._take(
            "screenshot",
            CommandResult(ok=True, operation="screenshot", data=b"\x89PNG fake"),
        )
