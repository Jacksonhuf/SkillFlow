#!/usr/bin/env python3
"""Standalone entrypoint for the bundled universal-browser skill (OpenCode / Skill Hub).

Requires only:
  - This full skill directory (SKILL.md + templates/ + runtime/)
  - Google Chrome on the machine (Playwright is installed on demand) — or an existing
    chrome-use CLI + extension, which is reused automatically

No separate Agent platform or pip install to site-packages is required.
Business users: double-click open-console.bat (Windows) / open-console.sh and use the web UI.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


def _skill_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _bootstrap() -> None:
    # This guard must stay valid syntax on old interpreters so the message is actually shown.
    if sys.version_info < (3, 11):  # noqa: UP036
        current = "{}.{}".format(sys.version_info[0], sys.version_info[1])  # noqa: UP032
        print(
            "需要 Python 3.11 或更高版本（当前 " + current + "）。"
            "请到 https://www.python.org/downloads/ 安装 3.12（推荐）后重试。",
            file=sys.stderr,
        )
        print(
            "Windows 已装多版本时可在技能目录执行： py -3.12 scripts\\invoke.py ui",
            file=sys.stderr,
        )
        raise SystemExit(2)
    root = _skill_root()
    runtime_src = root / "runtime" / "src"
    if not runtime_src.is_dir():
        print(
            "ERROR: missing bundled runtime/. "
            "Use universal-browser-full-*.zip from SkillFlow releases.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    path = str(runtime_src)
    if path not in sys.path:
        sys.path.insert(0, path)
    os.environ.setdefault("UNIVERSAL_BROWSER_SKILL_ROOT", str(root))


def main(argv: list[str] | None = None) -> int:
    _bootstrap()
    from browser_skill.app import parse_variables
    from browser_skill.models import SkillRequest
    from browser_skill.standalone import make_standalone_app

    parser = argparse.ArgumentParser(description="Universal Browser standalone skill runner")
    parser.add_argument(
        "--chrome-use",
        default=os.environ.get("CHROME_USE_BIN", "chrome-use"),
        help="chrome-use CLI name or path (or set CHROME_USE_BIN)",
    )
    parser.add_argument(
        "--engine",
        choices=["auto", "chrome-use", "playwright"],
        default=os.environ.get("UNIVERSAL_BROWSER_ENGINE", "auto"),
        help=(
            "Browser engine. auto (default): drive local Chrome with Playwright (installed on "
            "demand); chrome-use is only used when Playwright is unavailable. "
            "Set UNIVERSAL_BROWSER_CDP_URL to attach to a running Chrome."
        ),
    )
    parser.add_argument(
        "--no-auto-install-chrome-use",
        action="store_true",
        help=(
            "Do not download chrome-use on first use "
            "(or set UNIVERSAL_BROWSER_SKIP_CHROME_USE_INSTALL=1)"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("templates", help="List published templates")
    sub.add_parser("start", help="Show template menu JSON")
    sub.add_parser("capabilities", help="JSON browser capabilities (operator / agent preflight)")
    sub.add_parser("doctor", help="Check chrome-use CLI and extension readiness (operator only)")

    run_p = sub.add_parser("run", help="Run a published template")
    run_p.add_argument("selector", help="Template id, menu index, or name")
    run_p.add_argument("--var", action="append", default=[], help="name=value")

    resume_p = sub.add_parser("resume", help="Resume after Chrome login")
    resume_p.add_argument("run_id")
    resume_p.add_argument("--var", action="append", default=[])

    ui_p = sub.add_parser("ui", help="Open the local web console (127.0.0.1 only)")
    ui_p.add_argument("--port", type=int, default=8765, help="Port (0 = random free port)")
    ui_p.add_argument("--no-browser", action="store_true", help="Do not open a browser tab")

    args = parser.parse_args(argv)
    try:
        app = make_standalone_app(
            _skill_root(),
            chrome_use_executable=args.chrome_use,
            auto_install_chrome_use=not args.no_auto_install_chrome_use,
            engine=args.engine,
        )
    except Exception as exc:
        from browser_skill.errors import SkillError

        if isinstance(exc, SkillError):
            print(exc.message, file=sys.stderr)
        else:
            print(str(exc), file=sys.stderr)
        return 1

    if args.command == "ui":
        from browser_skill.console.server import serve_console

        serve_console(
            app,
            port=args.port,
            open_browser=not args.no_browser,
        )
        return 0

    async def dispatch() -> int:
        if args.command == "capabilities":
            caps = await app.adapter.capabilities()
            status = await app.adapter.status()
            payload = {
                "status_ok": status.ok,
                "capabilities": caps.model_dump(mode="json"),
            }
            payload_fn = getattr(app.adapter, "capabilities_payload", None)
            if callable(payload_fn):
                extra = await payload_fn()
                if isinstance(extra, dict):
                    payload["capabilities_payload"] = extra
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if status.ok else 1
        if args.command == "doctor":
            from browser_skill.platform.probe import probe_adapter

            report = await probe_adapter(app.adapter, mode="local_cli")
            print(report.text)
            return 0 if report.ready else 1
        if args.command == "templates":
            items = app.store.list()
            for index, item in enumerate(items, 1):
                print(f"{index}. {item.name} ({item.template_id} v{item.version})")
            return 0
        if args.command == "start":
            response = await app.handle(SkillRequest(action="start"))
            print(json.dumps(response.model_dump(mode="json"), ensure_ascii=False, indent=2))
            return 0 if response.ok else 1
        if args.command == "run":
            variables = parse_variables(args.var)
            response = await app.handle(
                SkillRequest(
                    action="run",
                    selector=args.selector,
                    variables=variables,
                )
            )
            print(json.dumps(response.model_dump(mode="json"), ensure_ascii=False, indent=2))
            return 0 if response.ok else 1
        if args.command == "resume":
            response = await app.handle(
                SkillRequest(
                    action="resume",
                    run_id=args.run_id,
                    variables=parse_variables(args.var),
                )
            )
            print(json.dumps(response.model_dump(mode="json"), ensure_ascii=False, indent=2))
            return 0 if response.ok else 1
        return 2

    async def dispatch_and_close() -> int:
        try:
            return await dispatch()
        finally:
            # Playwright keeps a driver subprocess; release it before the loop shuts down.
            close = getattr(app.adapter, "close", None)
            if callable(close):
                await close()

    return asyncio.run(dispatch_and_close())


if __name__ == "__main__":
    raise SystemExit(main())
