"""BrowserAdapter backed by Playwright driving the user's local Chrome.

Three connection modes, all per-user and local (no shared runner):

* ``cdp_url`` - attach to an already running Chrome started with
  ``--remote-debugging-port`` so the user's logged-in session is reused as-is.
* ``user_data_dir`` - launch Chrome with a dedicated persistent profile; the user logs in once and
  cookies survive across runs.
* neither - launch an ephemeral Chrome (tests / one-off runs).

Playwright is an optional dependency (``pip install universal-browser-skill[playwright]``). The
module imports it lazily so the rest of the runtime keeps working with chrome-use alone.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import re
import time
from collections import deque
from pathlib import Path
from typing import Any

from browser_skill.acquire.vision import parse_xy_target
from browser_skill.errors import ErrorCode, SkillError
from browser_skill.models import BrowserCapabilities, BrowserSnapshot, CommandResult

_REF_ATTR = "data-ubs-ref"
_REF_PREFIX = "@"
_MAX_TEXT_CHARS = 20_000
_MAX_ELEMENTS = 800
_MAX_NETWORK_ENTRIES = 300
_MAX_BODY_BYTES = 2_000_000
_SETTLE_GRACE_MS = 150

_NEXT_PAGE_SELECTORS = (
    "a[rel='next']",
    ".ant-pagination-next:not(.ant-pagination-disabled)",
    ".el-pagination .btn-next:not([disabled])",
    ".pagination .next:not(.disabled) a",
    "button[aria-label*='next' i]:not([disabled])",
    "a[aria-label*='next' i]",
    "li[title='下一页']:not(.ant-pagination-disabled)",
)
_NEXT_PAGE_TEXTS = ("下一页", "下页", "Next", "next page", "›", "»")
# Template dom_hints are CSS selectors: "#id", ".cls", "[attr]", "table tr td", "a.btn > span"
_CSS_LIKE = re.compile(r"^(?:[#.\[]|[a-zA-Z][\w-]*(?:[#.\[:>\s]|$))")

_PAGE_SCRIPTS = Path(__file__).with_name("playwright_page.js")


def _page_script(name: str) -> str:
    """Return one function from playwright_page.js as an expression Playwright can evaluate."""
    return f"(args) => ({_PAGE_SCRIPTS.read_text(encoding='utf-8')}).{name}(args)"


def _missing_playwright(exc: Exception) -> SkillError:
    return SkillError(
        ErrorCode.CHROME_USE_UNAVAILABLE,
        "Playwright 未安装：请执行 pip install 'universal-browser-skill[playwright]'"
        "（或 pip install playwright）后重试",
        stage="adapter",
        details={"import_error": str(exc)},
    )


class PlaywrightAdapter:
    """Drive the user's local Chrome through Playwright; implements BrowserAdapter."""

    def __init__(
        self,
        *,
        cdp_url: str | None = None,
        user_data_dir: Path | str | None = None,
        executable_path: str | None = None,
        channel: str | None = "chrome",
        headless: bool = False,
        downloads_dir: Path | str | None = None,
        timeout_ms: int = 15_000,
        launch_args: list[str] | None = None,
    ) -> None:
        self.cdp_url = cdp_url
        self.user_data_dir = Path(user_data_dir).expanduser() if user_data_dir else None
        self.executable_path = executable_path
        self.channel = channel
        self.headless = headless
        self.downloads_dir = Path(downloads_dir).expanduser() if downloads_dir else None
        self.timeout_ms = timeout_ms
        self.launch_args = list(launch_args or [])
        self._pw: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._opener_of: dict[int, Any] = {}
        self._network: deque[dict[str, Any]] = deque(maxlen=_MAX_NETWORK_ENTRIES)
        self._downloads: list[dict[str, Any]] = []
        self._dialog_events: deque[dict[str, Any]] = deque(maxlen=20)
        self._pending: set[asyncio.Task[None]] = set()
        self._connect_lock = asyncio.Lock()
        self._connect_error: str = ""

    # ------------------------------------------------------------------ lifecycle

    @property
    def mode(self) -> str:
        if self.cdp_url:
            return "cdp"
        if self.user_data_dir:
            return "persistent_profile"
        return "ephemeral"

    @property
    def connected(self) -> bool:
        return self._context is not None

    async def _ensure(self) -> Any:
        """Connect lazily; returns the active page."""
        async with self._connect_lock:
            if self._context is None:
                await self._connect()
            if self._page is None or self._page.is_closed():
                pages = [page for page in self._context.pages if not page.is_closed()]
                self._page = pages[-1] if pages else await self._context.new_page()
            return self._page

    async def _connect(self) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise _missing_playwright(exc) from exc
        try:
            self._pw = await async_playwright().start()
            chromium = self._pw.chromium
            if self.cdp_url:
                self._browser = await chromium.connect_over_cdp(
                    self.cdp_url, timeout=self.timeout_ms
                )
                contexts = self._browser.contexts
                self._context = contexts[0] if contexts else await self._browser.new_context()
            elif self.user_data_dir:
                self.user_data_dir.mkdir(parents=True, exist_ok=True)
                self._context = await chromium.launch_persistent_context(
                    str(self.user_data_dir),
                    headless=self.headless,
                    accept_downloads=True,
                    **self._launch_kwargs(),
                )
            else:
                self._browser = await chromium.launch(
                    headless=self.headless, **self._launch_kwargs()
                )
                self._context = await self._browser.new_context(accept_downloads=True)
        except SkillError:
            raise
        except Exception as exc:
            self._connect_error = str(exc)[:500]
            await self._teardown()
            raise SkillError(
                ErrorCode.EXTENSION_OFFLINE,
                f"无法连接本机 Chrome（{self.mode}）：{self._connect_error}",
                stage="adapter",
                retryable=True,
            ) from exc
        self._context.set_default_timeout(self.timeout_ms)
        self._context.on("page", self._on_page)
        for page in self._context.pages:
            self._wire_page(page)

    def _launch_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"args": self.launch_args}
        if self.executable_path:
            kwargs["executable_path"] = self.executable_path
        elif self.channel:
            kwargs["channel"] = self.channel
        if self.downloads_dir:
            self.downloads_dir.mkdir(parents=True, exist_ok=True)
            kwargs["downloads_path"] = str(self.downloads_dir)
        return kwargs

    def _on_page(self, page: Any) -> None:
        self._wire_page(page)
        opener = self._page
        if opener is not None and opener is not page:
            self._opener_of[id(page)] = opener
        self._page = page

    def _wire_page(self, page: Any) -> None:
        page.on("response", self._schedule_capture)
        page.on("dialog", lambda dialog: asyncio.ensure_future(self._on_dialog(dialog)))
        page.on("download", lambda download: self._downloads.append(self._download_entry(download)))

    def _schedule_capture(self, response: Any) -> None:
        task = asyncio.ensure_future(self._capture(response))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _drain_captures(self) -> None:
        """Body reads are asynchronous; wait for in-flight ones so listings are complete."""
        await asyncio.sleep(_SETTLE_GRACE_MS / 1000)
        pending = [task for task in self._pending if not task.done()]
        if pending:
            with contextlib.suppress(Exception):
                await asyncio.wait(pending, timeout=min(self.timeout_ms, 3_000) / 1000)

    async def _capture(self, response: Any) -> None:
        try:
            request = response.request
            if request.resource_type not in {"xhr", "fetch", "document", "other"}:
                return
            content_type = str(response.headers.get("content-type", ""))
            if "json" not in content_type.casefold() and request.resource_type == "document":
                return
            body_text: str | None = None
            size = 0
            if "json" in content_type.casefold() or request.resource_type in {"xhr", "fetch"}:
                raw = await response.body()
                size = len(raw)
                if size <= _MAX_BODY_BYTES:
                    body_text = raw.decode("utf-8", errors="replace")
            self._network.append(
                {
                    "url": response.url,
                    "method": request.method,
                    "status": response.status,
                    "content_type": content_type,
                    "body": body_text,
                    "size": size,
                    "resource_type": request.resource_type,
                    "captured_at": time.time(),
                }
            )
        except Exception:  # capture is best effort; never break navigation
            return

    async def _on_dialog(self, dialog: Any) -> None:
        # Auto-dismiss so Playwright never blocks; the runner reads the recorded event via
        # get_dialog_status and stops the template, matching the chrome-use behaviour.
        entry = {"type": dialog.type, "message": dialog.message, "handled": "dismiss"}
        with contextlib.suppress(Exception):
            if dialog.type == "beforeunload":
                await dialog.accept()
                entry["handled"] = "accept"
            else:
                await dialog.dismiss()
        self._dialog_events.append(entry)

    @staticmethod
    def _download_entry(download: Any) -> dict[str, Any]:
        return {
            "url": download.url,
            "filename": download.suggested_filename,
            "state": "started",
        }

    async def _teardown(self) -> None:
        with contextlib.suppress(Exception):
            if self._context is not None and self.mode != "cdp":
                await self._context.close()
        with contextlib.suppress(Exception):
            if self._browser is not None:
                await self._browser.close()
        with contextlib.suppress(Exception):
            if self._pw is not None:
                await self._pw.stop()
        self._pw = self._browser = self._context = self._page = None

    async def close(self) -> None:
        await self._teardown()

    # ------------------------------------------------------------------ helpers

    def _locator(self, page: Any, target: str) -> Any:
        target = target.strip()
        if target.startswith(_REF_PREFIX) and re.fullmatch(r"@e\d+", target):
            return page.locator(f"[{_REF_ATTR}='{target[1:]}']").first
        if target.startswith(("xpath=", "//", "css=", "text=", "role=")):
            return page.locator(target).first
        if _CSS_LIKE.match(target):
            return page.locator(target).first
        return page.get_by_text(target, exact=False).first

    @staticmethod
    def _result(
        operation: str, ok: bool, data: Any = None, error: str = "", started: float = 0.0
    ) -> CommandResult:
        return CommandResult(
            ok=ok,
            operation=operation,
            data=data,
            safe_stderr=error[:2000],
            duration_ms=int((time.monotonic() - started) * 1000) if started else 0,
        )

    async def _settle(self, page: Any) -> None:
        with contextlib.suppress(Exception):
            await page.wait_for_load_state("domcontentloaded", timeout=self.timeout_ms)
        # Give click handlers a beat to start their XHR before checking for idle, then let the
        # driver flush response events that may trail the DOM update.
        with contextlib.suppress(Exception):
            await page.wait_for_timeout(_SETTLE_GRACE_MS)
        with contextlib.suppress(Exception):
            await page.wait_for_load_state("networkidle", timeout=min(self.timeout_ms, 3_000))
        await asyncio.sleep(_SETTLE_GRACE_MS / 1000)

    async def _guarded(self, operation: str, coroutine_factory: Any) -> CommandResult:
        started = time.monotonic()
        try:
            data = await coroutine_factory()
        except SkillError:
            raise
        except Exception as exc:  # surfaced to the runner as a failed command
            return self._result(
                operation, False, error=f"{type(exc).__name__}: {exc}", started=started
            )
        return self._result(operation, True, data=data, started=started)

    # ------------------------------------------------------------------ BrowserAdapter

    async def status(self) -> CommandResult:
        started = time.monotonic()
        try:
            page = await self._ensure()
        except SkillError as exc:
            return self._result(
                "status",
                False,
                data={"mode": self.mode, "connected": False},
                error=exc.message,
                started=started,
            )
        return self._result(
            "status",
            True,
            data={"mode": self.mode, "connected": True, "url": page.url, "engine": "playwright"},
            started=started,
        )

    async def capabilities(self) -> BrowserCapabilities:
        try:
            import playwright  # noqa: F401
        except ImportError:
            return BrowserCapabilities()
        return BrowserCapabilities(
            snapshot=True,
            snapshot_diff=False,
            find=True,
            download=True,
            downloads=True,
            tabs=True,
            sessions=True,
            dialogs=True,
            network=True,
            screenshot=True,
        )

    async def capabilities_payload(self) -> dict[str, Any]:
        payload = (await self.capabilities()).model_dump(mode="json")
        payload["engine"] = "playwright"
        payload["mode"] = self.mode
        return payload

    async def open(self, url: str) -> CommandResult:
        async def action() -> Any:
            page = await self._ensure()
            await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            await self._settle(page)
            return page.url

        return await self._guarded("open", action)

    async def adopt_tab(self, match: str) -> CommandResult:
        async def action() -> Any:
            await self._ensure()
            needle = match.casefold()
            for page in reversed(self._context.pages):
                if page.is_closed():
                    continue
                if needle in page.url.casefold() or needle in (await page.title()).casefold():
                    self._page = page
                    with contextlib.suppress(Exception):
                        await page.bring_to_front()
                    return {"url": page.url}
            raise LookupError(f"No open tab matches '{match}'")

        return await self._guarded("tab.adopt", action)

    async def list_tabs(self) -> CommandResult:
        async def action() -> Any:
            await self._ensure()
            tabs = []
            for index, page in enumerate(self._context.pages):
                if page.is_closed():
                    continue
                tabs.append(
                    {
                        "index": index,
                        "url": page.url,
                        "title": await page.title(),
                        "active": page is self._page,
                    }
                )
            return tabs

        return await self._guarded("tab.list", action)

    async def snapshot(self, *, interactive: bool = True, diff: bool = False) -> BrowserSnapshot:
        try:
            page = await self._ensure()
            await self._settle(page)
            raw = await page.evaluate(
                _page_script("snapshot"),
                {
                    "refAttr": _REF_ATTR,
                    "maxElements": _MAX_ELEMENTS if interactive else 0,
                    "maxText": _MAX_TEXT_CHARS,
                    "maxTables": 3,
                },
            )
        except SkillError:
            raise
        except Exception as exc:
            raise SkillError(
                ErrorCode.PAGE_NOT_FOUND,
                "Unable to snapshot the current page",
                stage="snapshot",
                retryable=True,
                details={"error": str(exc)[:500]},
            ) from exc
        elements = raw.get("elements", []) if isinstance(raw, dict) else []
        for element in elements:
            if "ref" in element and "target" not in element:
                element["target"] = element["ref"]
        return BrowserSnapshot(
            url=str(raw.get("url", "")),
            title=str(raw.get("title", "")),
            text=str(raw.get("text", "")),
            elements=elements,
        )

    async def find(self, description: str) -> CommandResult:
        async def action() -> Any:
            page = await self._ensure()
            candidates = [
                page.get_by_role("button", name=description),
                page.get_by_role("link", name=description),
                page.get_by_label(description),
                page.get_by_placeholder(description),
                page.get_by_text(description, exact=True),
                page.get_by_text(description, exact=False),
                page.get_by_title(description),
            ]
            for locator in candidates:
                count = await locator.count()
                if count == 0:
                    continue
                handle = await locator.first.element_handle(timeout=2_000)
                if handle is None:
                    continue
                data = await page.evaluate(
                    _page_script("find"), {"el": handle, "refAttr": _REF_ATTR}
                )
                if data.get("disabled"):
                    continue
                data["target"] = data["ref"]
                data["match_count"] = count
                return data
            raise LookupError(f"No element matches '{description}'")

        return await self._guarded("find", action)

    async def click(self, target: str, *, observe: bool = True) -> CommandResult:
        async def action() -> Any:
            page = await self._ensure()
            before = page.url
            point = parse_xy_target(target)
            if point is not None:  # vision fallback answers in viewport coordinates
                await page.mouse.click(point[0], point[1])
            else:
                await self._locator(page, target).click(timeout=self.timeout_ms)
            if observe:
                await self._settle(page)
                # A popup may have replaced the active page while settling
                page = await self._ensure()
            return {"url": page.url, "navigated": page.url != before}

        return await self._guarded("click", action)

    async def fill(self, target: str, value: str, *, sensitive: bool = False) -> CommandResult:
        async def action() -> Any:
            page = await self._ensure()
            await self._locator(page, target).fill(value, timeout=self.timeout_ms)
            return {"filled": True}

        return await self._guarded("fill", action)

    async def type(self, target: str, value: str, *, sensitive: bool = False) -> CommandResult:
        async def action() -> Any:
            page = await self._ensure()
            locator = self._locator(page, target)
            await locator.click(timeout=self.timeout_ms)
            await locator.press_sequentially(value, delay=20)
            return {"typed": True}

        return await self._guarded("type", action)

    async def get_actions(self, target: str) -> CommandResult:
        async def action() -> Any:
            page = await self._ensure()
            locator = self._locator(page, target)
            tag = str(await locator.evaluate("el => el.tagName.toLowerCase()"))
            actions = ["click"]
            if tag in {"input", "textarea", "select"} or await locator.evaluate(
                "el => el.isContentEditable"
            ):
                actions.extend(["fill", "type"])
            return actions

        return await self._guarded("actions", action)

    async def do_action(self, target: str, action: str) -> CommandResult:
        async def run() -> Any:
            page = await self._ensure()
            key = f"{target}:{action}".casefold()
            if key in {"page:back", "history:back"}:
                opener = self._opener_of.pop(id(page), None)
                if opener is not None and not opener.is_closed():
                    with contextlib.suppress(Exception):
                        await page.close()
                    self._page = opener
                    return {"url": opener.url, "closed_popup": True}
                await page.go_back(wait_until="domcontentloaded", timeout=self.timeout_ms)
                await self._settle(page)
                return {"url": page.url}
            if key in {"page:forward", "history:forward"}:
                await page.go_forward(wait_until="domcontentloaded", timeout=self.timeout_ms)
                return {"url": page.url}
            if key in {"page:reload", "page:refresh"}:
                await page.reload(wait_until="domcontentloaded", timeout=self.timeout_ms)
                await self._settle(page)
                return {"url": page.url}
            if key in {"page:scroll_down", "page:scroll"}:
                await page.mouse.wheel(0, 1600)
                await page.evaluate("window.scrollBy(0, window.innerHeight)")
                await self._settle(page)
                return {"scrolled": True}
            if key == "page:scroll_up":
                await page.evaluate("window.scrollBy(0, -window.innerHeight)")
                return {"scrolled": True}
            if action.casefold() in {"next_page", "next"}:
                return await self._click_next_page(page)
            raise LookupError(f"Unsupported action '{action}' for target '{target}'")

        return await self._guarded("do", run)

    async def _click_next_page(self, page: Any) -> dict[str, Any]:
        for selector in _NEXT_PAGE_SELECTORS:
            locator = page.locator(selector).first
            if await locator.count() and await locator.is_visible():
                await locator.click(timeout=self.timeout_ms)
                await self._settle(page)
                return {"strategy": "selector", "selector": selector}
        for text in _NEXT_PAGE_TEXTS:
            locator = (
                page.get_by_role("button", name=text).or_(page.get_by_role("link", name=text)).first
            )
            if await locator.count() and await locator.is_visible() and await locator.is_enabled():
                await locator.click(timeout=self.timeout_ms)
                await self._settle(page)
                return {"strategy": "text", "text": text}
        raise LookupError("No enabled next-page control found")

    async def download(self, target: str, path: Path) -> CommandResult:
        async def action() -> Any:
            page = await self._ensure()
            path.parent.mkdir(parents=True, exist_ok=True)
            locator = self._locator(page, target)
            async with page.expect_download(timeout=max(self.timeout_ms, 120_000)) as info:
                await locator.click(timeout=self.timeout_ms)
            download = await info.value
            await download.save_as(str(path))
            entry = {
                "url": download.url,
                "filename": download.suggested_filename,
                "path": str(path),
                "state": "completed",
                "size": path.stat().st_size if path.exists() else 0,
            }
            self._downloads.append(entry)
            return entry

        return await self._guarded("download", action)

    async def list_downloads(self) -> CommandResult:
        return self._result("downloads", True, data=list(self._downloads))

    async def get_dialog_status(self) -> CommandResult:
        if self._dialog_events:
            latest = self._dialog_events[-1]
            return self._result("dialog.status", True, data={"open": True, **latest})
        return self._result("dialog.status", True, data={"open": False})

    async def accept_dialog(self) -> CommandResult:
        self._dialog_events.clear()
        return self._result("dialog.accept", True, data={"open": False})

    async def dismiss_dialog(self) -> CommandResult:
        self._dialog_events.clear()
        return self._result("dialog.dismiss", True, data={"open": False})

    async def list_sessions(self) -> CommandResult:
        return self._result(
            "session.list",
            True,
            data=[
                {
                    "engine": "playwright",
                    "mode": self.mode,
                    "connected": self.connected,
                    "cdp_url": self.cdp_url,
                    "user_data_dir": str(self.user_data_dir) if self.user_data_dir else None,
                    "tabs": len(self._context.pages) if self._context else 0,
                }
            ],
        )

    async def screenshot(self) -> CommandResult:
        async def action() -> Any:
            page = await self._ensure()
            png = await page.screenshot(type="png", full_page=False)
            size = page.viewport_size or {}
            return {
                "png_base64": base64.b64encode(png).decode("ascii"),
                "width": int(size.get("width", 0)),
                "height": int(size.get("height", 0)),
            }

        return await self._guarded("screenshot", action)

    async def network_requests(self) -> CommandResult:
        await self._drain_captures()
        entries = []
        for entry in self._network:
            item = dict(entry)
            body = item.get("body")
            if isinstance(body, str):
                with contextlib.suppress(json.JSONDecodeError):
                    item["body"] = json.loads(body)
            entries.append(item)
        return self._result("network.list", True, data=entries)
