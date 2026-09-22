"""Pick the browser engine for a local run.

Selection order: explicit ``engine`` argument, then ``UNIVERSAL_BROWSER_ENGINE``, then chrome-use.
Playwright settings come from ``UNIVERSAL_BROWSER_CDP_URL`` (attach to the user's running Chrome
started with ``--remote-debugging-port``) or ``UNIVERSAL_BROWSER_PROFILE_DIR`` (dedicated persistent
profile); when neither is set an ephemeral Chrome is launched.
"""

from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Any

from browser_skill.browser.base import BrowserAdapter
from browser_skill.errors import ErrorCode, SkillError

ENGINE_ENV = "UNIVERSAL_BROWSER_ENGINE"
CDP_URL_ENV = "UNIVERSAL_BROWSER_CDP_URL"
PROFILE_DIR_ENV = "UNIVERSAL_BROWSER_PROFILE_DIR"
CHROME_PATH_ENV = "UNIVERSAL_BROWSER_CHROME_PATH"
HEADLESS_ENV = "UNIVERSAL_BROWSER_HEADLESS"
CHROME_ARGS_ENV = "UNIVERSAL_BROWSER_CHROME_ARGS"

ENGINES = ("chrome-use", "playwright")


def resolve_engine(engine: str | None = None) -> str:
    value = (engine or os.environ.get(ENGINE_ENV) or "chrome-use").strip().casefold()
    aliases = {"chrome_use": "chrome-use", "chromeuse": "chrome-use", "pw": "playwright"}
    value = aliases.get(value, value)
    if value not in ENGINES:
        raise SkillError(
            ErrorCode.CHROME_USE_UNAVAILABLE,
            f"未知浏览器引擎 '{value}'，可选：{', '.join(ENGINES)}",
            details={"engine": value},
        )
    return value


def build_adapter(
    engine: str | None = None,
    *,
    chrome_use_executable: str = "chrome-use",
    cdp_url: str | None = None,
    user_data_dir: Path | str | None = None,
    skill_root: Path | None = None,
    **playwright_options: Any,
) -> BrowserAdapter:
    resolved = resolve_engine(engine)
    if resolved == "chrome-use":
        from browser_skill.browser.chrome_use import ChromeUseAdapter

        return ChromeUseAdapter(executable=chrome_use_executable)

    from browser_skill.browser.playwright_adapter import PlaywrightAdapter

    cdp = cdp_url or os.environ.get(CDP_URL_ENV) or None
    profile = user_data_dir or os.environ.get(PROFILE_DIR_ENV) or None
    if not cdp and not profile and skill_root is not None:
        # Default to a per-user profile inside the skill so logins survive across runs
        profile = skill_root / "runs" / "chrome-profile"
    options: dict[str, Any] = {
        "cdp_url": cdp,
        "user_data_dir": profile,
        "executable_path": os.environ.get(CHROME_PATH_ENV) or None,
        "headless": os.environ.get(HEADLESS_ENV, "").strip().casefold() in {"1", "true", "yes"},
        "launch_args": shlex.split(os.environ.get(CHROME_ARGS_ENV, "")),
    }
    if skill_root is not None:
        options["downloads_dir"] = skill_root / "runs" / "downloads"
    options.update(playwright_options)
    return PlaywrightAdapter(**options)
