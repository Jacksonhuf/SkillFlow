from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from browser_skill.browser.base import snapshot_from_data
from browser_skill.browser.chrome_use_paths import resolve_chrome_use_executable
from browser_skill.errors import ErrorCode, SkillError
from browser_skill.models import BrowserCapabilities, BrowserSnapshot, CommandResult


class ChromeUseAdapter:
    """The only subprocess boundary for the third-party chrome-use CLI.

    The supplied V2.0 design is the compatibility baseline. `doctor` must verify the selected
    upstream version because its exact CLI and output contract are not controlled by this project.
    """

    def __init__(self, executable: str = "chrome-use", timeout: float = 30.0) -> None:
        self.executable = executable
        self.timeout = timeout
        self.last_safe_command: list[str] = []

    async def _run(
        self,
        args: list[str],
        *,
        timeout: float | None = None,
        sensitive_indexes: set[int] | None = None,
    ) -> CommandResult:
        binary = resolve_chrome_use_executable(self.executable)
        argv = [binary, *args]
        safe = list(argv)
        for index in sensitive_indexes or set():
            if 0 <= index < len(safe):
                safe[index] = "***"
        self.last_safe_command = safe
        started = time.monotonic()
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "NO_COLOR": "1"},
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout or self.timeout
            )
        except TimeoutError as exc:
            if "process" in locals():
                process.kill()
                await process.communicate()
            raise SkillError(
                ErrorCode.CHROME_USE_UNAVAILABLE,
                f"chrome-use operation timed out: {args[0]}",
                stage="adapter",
                retryable=True,
            ) from exc
        duration = int((time.monotonic() - started) * 1000)
        output = stdout.decode("utf-8", errors="replace").strip()
        error = stderr.decode("utf-8", errors="replace").strip()
        data: Any = output
        if output:
            with contextlib.suppress(json.JSONDecodeError):
                data = json.loads(output)
        return CommandResult(
            ok=process.returncode == 0,
            operation=args[0],
            data=data,
            safe_stderr=self._redact(error, argv, sensitive_indexes or set()),
            exit_code=process.returncode,
            duration_ms=duration,
        )

    @staticmethod
    def _redact(text: str, argv: list[str], indexes: set[int]) -> str:
        for index in indexes:
            if 0 <= index < len(argv) and argv[index]:
                text = text.replace(argv[index], "***")
        return text[:2000]

    async def status(self) -> CommandResult:
        return await self._run(["status"], timeout=10)

    async def capabilities(self) -> BrowserCapabilities:
        try:
            resolve_chrome_use_executable(self.executable)
        except SkillError:
            return BrowserCapabilities()
        result = await self._run(["--help"], timeout=10)
        help_text = f"{result.data}\n{result.safe_stderr}".casefold()
        # Conservative: advertise only capabilities visible in installed CLI help.
        return BrowserCapabilities(
            snapshot="snapshot" in help_text,
            snapshot_diff="--diff" in help_text,
            find="find" in help_text,
            download="download" in help_text,
            downloads="downloads" in help_text,
            tabs="tab" in help_text,
            sessions="session" in help_text,
            dialogs="dialog" in help_text,
            network="network" in help_text,
            screenshot="screenshot" in help_text,
        )

    async def capabilities_payload(self) -> dict[str, Any]:
        return (await self.capabilities()).model_dump(mode="json")

    async def open(self, url: str) -> CommandResult:
        return await self._run(["open", url])

    async def adopt_tab(self, match: str) -> CommandResult:
        return await self._run(["tab", "adopt", match])

    async def list_tabs(self) -> CommandResult:
        return await self._run(["tab", "list"])

    async def snapshot(self, *, interactive: bool = True, diff: bool = False) -> BrowserSnapshot:
        args = ["snapshot"]
        if interactive:
            args.append("-i")
        if diff:
            args.append("--diff")
        result = await self._run(args)
        if not result.ok:
            raise SkillError(
                ErrorCode.PAGE_NOT_FOUND,
                "Unable to snapshot the current page",
                stage="snapshot",
                retryable=True,
            )
        return snapshot_from_data(result.data)

    async def find(self, description: str) -> CommandResult:
        return await self._run(["find", description])

    async def click(self, target: str, *, observe: bool = True) -> CommandResult:
        args = ["click", target]
        if observe:
            args.append("--observe")
        return await self._run(args)

    async def fill(self, target: str, value: str, *, sensitive: bool = False) -> CommandResult:
        return await self._run(
            ["fill", target, value], sensitive_indexes={3} if sensitive else set()
        )

    async def type(self, target: str, value: str, *, sensitive: bool = False) -> CommandResult:
        return await self._run(
            ["type", target, value], sensitive_indexes={3} if sensitive else set()
        )

    async def get_actions(self, target: str) -> CommandResult:
        return await self._run(["actions", target])

    async def do_action(self, target: str, action: str) -> CommandResult:
        return await self._run(["do", target, action])

    async def download(
        self, target: str, path: Path, *, timeout_ms: int | None = None
    ) -> CommandResult:
        limit = timeout_ms if timeout_ms is not None else self.timeout
        return await self._run(["download", target, str(path)], timeout=max(limit, 120))

    async def list_downloads(self) -> CommandResult:
        return await self._run(["downloads"])

    async def get_dialog_status(self) -> CommandResult:
        return await self._run(["dialog", "status"])

    async def accept_dialog(self) -> CommandResult:
        return await self._run(["dialog", "accept"])

    async def dismiss_dialog(self) -> CommandResult:
        return await self._run(["dialog", "dismiss"])

    async def list_sessions(self) -> CommandResult:
        return await self._run(["session", "list"])

    async def network_requests(self) -> CommandResult:
        return await self._run(["network", "list", "--json"])

    async def screenshot(self) -> CommandResult:
        return await self._run(["screenshot", "--json"])


ToolInvoker = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class ChromeUseToolAdapter:
    """Bind BrowserAdapter to an internal platform's structured chrome-use tool.

    The host injects an async invoker. The adapter owns operation names and response normalization,
    keeping runtime modules independent of the platform SDK and shell commands.
    """

    def __init__(self, invoke: ToolInvoker, *, tool_name: str = "chrome-use") -> None:
        self.invoke = invoke
        self.tool_name = tool_name

    async def _call(self, operation: str, **arguments: Any) -> CommandResult:
        try:
            response = await self.invoke(
                self.tool_name,
                {"operation": operation, **arguments},
            )
        except Exception as exc:
            raise SkillError(
                ErrorCode.CHROME_USE_UNAVAILABLE,
                f"Platform chrome-use tool failed during {operation}",
                stage="adapter",
                retryable=True,
            ) from exc
        if not isinstance(response, dict):
            raise SkillError(
                ErrorCode.CHROME_USE_UNAVAILABLE,
                "Platform chrome-use tool returned an invalid response",
                stage="adapter",
            )
        ok = bool(response.get("ok", response.get("success", False)))
        return CommandResult(
            ok=ok,
            operation=operation,
            data=response.get("data", response.get("result")),
            safe_stderr=str(response.get("error", ""))[:2000],
            duration_ms=int(response.get("duration_ms", 0)),
        )

    async def status(self) -> CommandResult:
        return await self._call("status")

    async def capabilities(self) -> BrowserCapabilities:
        result = await self._call("capabilities")
        if not result.ok or not isinstance(result.data, dict):
            return BrowserCapabilities()
        allowed = BrowserCapabilities.model_fields
        return BrowserCapabilities.model_validate(
            {key: bool(value) for key, value in result.data.items() if key in allowed}
        )

    async def capabilities_payload(self) -> dict[str, Any]:
        result = await self._call("capabilities")
        if isinstance(result.data, dict):
            return result.data
        return {}

    async def open(self, url: str) -> CommandResult:
        return await self._call("open", url=url)

    async def adopt_tab(self, match: str) -> CommandResult:
        return await self._call("tab.adopt", match=match)

    async def list_tabs(self) -> CommandResult:
        return await self._call("tab.list")

    async def snapshot(self, *, interactive: bool = True, diff: bool = False) -> BrowserSnapshot:
        result = await self._call("snapshot", interactive=interactive, diff=diff)
        if not result.ok:
            raise SkillError(
                ErrorCode.PAGE_NOT_FOUND,
                "Unable to snapshot the current page",
                stage="snapshot",
                retryable=True,
            )
        return snapshot_from_data(result.data)

    async def find(self, description: str) -> CommandResult:
        return await self._call("find", description=description)

    async def click(self, target: str, *, observe: bool = True) -> CommandResult:
        return await self._call("click", target=target, observe=observe)

    async def fill(self, target: str, value: str, *, sensitive: bool = False) -> CommandResult:
        return await self._call("fill", target=target, value=value, sensitive=sensitive)

    async def type(self, target: str, value: str, *, sensitive: bool = False) -> CommandResult:
        return await self._call("type", target=target, value=value, sensitive=sensitive)

    async def get_actions(self, target: str) -> CommandResult:
        return await self._call("actions", target=target)

    async def do_action(self, target: str, action: str) -> CommandResult:
        return await self._call("do", target=target, action=action)

    async def download(
        self, target: str, path: Path, *, timeout_ms: int | None = None
    ) -> CommandResult:
        return await self._call("download", target=target, path=str(path))

    async def list_downloads(self) -> CommandResult:
        return await self._call("downloads")

    async def get_dialog_status(self) -> CommandResult:
        return await self._call("dialog.status")

    async def accept_dialog(self) -> CommandResult:
        return await self._call("dialog.accept")

    async def dismiss_dialog(self) -> CommandResult:
        return await self._call("dialog.dismiss")

    async def list_sessions(self) -> CommandResult:
        return await self._call("session.list")

    async def network_requests(self) -> CommandResult:
        return await self._call("network.list")

    async def screenshot(self) -> CommandResult:
        return await self._call("screenshot")
