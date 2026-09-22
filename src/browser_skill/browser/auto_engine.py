"""Zero-configuration engine selection.

Business users should never pick an engine. ``plan_engine`` decides for them:

1. An explicit request (``--engine`` / ``UNIVERSAL_BROWSER_ENGINE``) always wins.
2. A chrome-use CLI that is already on the machine (IT-provisioned) keeps working as before.
3. Otherwise Playwright drives the user's own Chrome with a persistent profile — the user logs
   in once in the window that pops up and never touches a setting.
4. When Playwright is not installed yet, it is installed silently with pip (opt out with
   ``UNIVERSAL_BROWSER_NO_AUTO_PIP=1``); if that fails, fall back to the chrome-use bootstrap.

``setup_status`` turns the same checks into a plain-language checklist for the console.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from browser_skill.browser.factory import CDP_URL_ENV, ENGINE_ENV, PROFILE_DIR_ENV, resolve_engine
from browser_skill.errors import SkillError

ENGINE_AUTO = "auto"
NO_AUTO_PIP_ENV = "UNIVERSAL_BROWSER_NO_AUTO_PIP"
PLAYWRIGHT_REQUIREMENT = "playwright>=1.45,<2"
CHROME_DOWNLOAD_URL = "https://www.google.com/chrome/"
_PIP_TIMEOUT_SECONDS = 900


@dataclass
class EnginePlan:
    engine: str
    reason: str
    chrome_use_executable: str | None = None
    notes: list[str] = field(default_factory=list)


def requested_engine(engine: str | None = None) -> str:
    value = (engine or os.environ.get(ENGINE_ENV) or ENGINE_AUTO).strip().casefold()
    return ENGINE_AUTO if value in {ENGINE_AUTO, ""} else value


def playwright_available() -> bool:
    return importlib.util.find_spec("playwright") is not None


def chrome_use_available(name: str = "chrome-use", *, skill_root: Path | None = None) -> str | None:
    """Return an already-present chrome-use CLI path, never downloading anything."""
    from browser_skill.browser.chrome_use_paths import resolve_chrome_use_executable

    previous = os.environ.get("UNIVERSAL_BROWSER_SKILL_ROOT")
    if skill_root is not None:
        os.environ["UNIVERSAL_BROWSER_SKILL_ROOT"] = str(skill_root)
    try:
        return resolve_chrome_use_executable(name)
    except SkillError:
        return None
    finally:
        if skill_root is not None:
            if previous is None:
                os.environ.pop("UNIVERSAL_BROWSER_SKILL_ROOT", None)
            else:
                os.environ["UNIVERSAL_BROWSER_SKILL_ROOT"] = previous


_WINDOWS_CHROME = (
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
)
_MAC_CHROME = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",)
_LINUX_CHROME_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")


def find_chrome() -> str | None:
    """Locate the user's Chrome binary without launching it."""
    override = os.environ.get("UNIVERSAL_BROWSER_CHROME_PATH", "").strip()
    if override and Path(override).is_file():
        return override
    if sys.platform == "win32":
        for raw in _WINDOWS_CHROME:
            candidate = Path(os.path.expandvars(raw))
            if candidate.is_file():
                return str(candidate)
    elif sys.platform == "darwin":
        for raw in _MAC_CHROME:
            if Path(raw).is_file():
                return raw
    for name in _LINUX_CHROME_NAMES:
        found = shutil.which(name)
        if found:
            return found
    return None


def auto_pip_allowed() -> bool:
    return os.environ.get(NO_AUTO_PIP_ENV, "").strip() not in {"1", "true", "yes"}


def install_playwright(*, timeout: int = _PIP_TIMEOUT_SECONDS) -> tuple[bool, str]:
    """Install the Playwright Python package into the running interpreter (no browser download)."""
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--quiet",
        "--disable-pip-version-check",
        PLAYWRIGHT_REQUIREMENT,
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"pip install playwright 失败：{exc}"
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[-400:]
        return False, f"pip install playwright 退出码 {completed.returncode}：{detail}"
    importlib.invalidate_caches()
    if not playwright_available():
        return False, "pip 报告成功，但仍无法导入 playwright"
    return True, "已安装 Playwright"


def plan_engine(
    engine: str | None = None,
    *,
    skill_root: Path | None = None,
    chrome_use_executable: str = "chrome-use",
    auto_install: bool = True,
) -> EnginePlan:
    wanted = requested_engine(engine)
    if wanted != ENGINE_AUTO:
        return EnginePlan(engine=resolve_engine(wanted), reason="explicit")

    existing = chrome_use_available(chrome_use_executable, skill_root=skill_root)
    if existing:
        return EnginePlan(
            engine="chrome-use",
            reason="检测到已安装的 chrome-use CLI",
            chrome_use_executable=existing,
        )

    if playwright_available():
        return EnginePlan(engine="playwright", reason="使用 Playwright 驱动本机 Chrome")

    notes: list[str] = []
    if auto_install and auto_pip_allowed():
        ok, message = install_playwright()
        notes.append(message)
        if ok:
            return EnginePlan(
                engine="playwright",
                reason="已自动安装 Playwright，驱动本机 Chrome",
                notes=notes,
            )
    else:
        notes.append("未启用 Playwright 自动安装")

    return EnginePlan(
        engine="chrome-use",
        reason="Playwright 不可用，回退到 chrome-use 引导安装",
        notes=notes,
    )


@dataclass
class SetupStep:
    key: str
    title: str
    ok: bool
    detail: str = ""
    action: str | None = None
    link: str | None = None


@dataclass
class SetupStatus:
    engine: str
    ready: bool
    headline: str
    steps: list[SetupStep]
    can_switch_to_playwright: bool = False


def playwright_setup_status(*, skill_root: Path | None) -> SetupStatus:
    steps: list[SetupStep] = []
    has_pw = playwright_available()
    steps.append(
        SetupStep(
            key="playwright",
            title="浏览器驱动（Playwright）",
            ok=has_pw,
            detail="已安装" if has_pw else "尚未安装，点击「一键修复」自动安装",
            action=None if has_pw else "install_playwright",
        )
    )
    cdp = os.environ.get(CDP_URL_ENV, "").strip()
    chrome = find_chrome()
    if cdp:
        steps.append(
            SetupStep(
                key="chrome", title="本机 Chrome", ok=True, detail=f"附着到已打开的 Chrome：{cdp}"
            )
        )
    else:
        steps.append(
            SetupStep(
                key="chrome",
                title="本机 Chrome",
                ok=chrome is not None,
                detail=chrome or "未找到 Google Chrome，请先安装",
                link=None if chrome else CHROME_DOWNLOAD_URL,
            )
        )
    profile_env = os.environ.get(PROFILE_DIR_ENV, "").strip()
    profile = (
        Path(profile_env)
        if profile_env
        else (skill_root / "runs" / "chrome-profile" if skill_root else None)
    )
    logged_in_hint = (
        "已有登录记录，运行时自动复用"
        if profile is not None and profile.is_dir() and any(profile.iterdir())
        else "首次运行会弹出 Chrome 窗口：在里面登录目标系统一次即可，之后自动复用"
    )
    steps.append(SetupStep(key="login", title="登录状态", ok=True, detail=logged_in_hint))
    ready = all(step.ok for step in steps)
    headline = "环境就绪，选择模板即可运行" if ready else "还差一步，按下面提示完成即可"
    return SetupStatus(engine="playwright", ready=ready, headline=headline, steps=steps)


_EXTENSION_URL = "https://chromewebstore.google.com/detail/chrome-use/knfcmbamhjmaonkfnjhldjedeobeafmk"
_EXTENSION_HINT = "请在 Chrome 安装并启用 chrome-use 扩展，或改用 Playwright（无需扩展）"


def chrome_use_setup_status(
    *, probe_ready: bool, probe_status_ok: bool, executable: str | None
) -> SetupStatus:
    steps = [
        SetupStep(
            key="cli",
            title="chrome-use 命令行",
            ok=executable is not None,
            detail=executable or "未找到，首次运行会自动下载",
        ),
        SetupStep(
            key="extension",
            title="Chrome 扩展 chrome-use",
            ok=probe_status_ok,
            detail="已连接" if probe_status_ok else _EXTENSION_HINT,
            link=None if probe_status_ok else _EXTENSION_URL,
            action=None if probe_status_ok else "switch_to_playwright",
        ),
    ]
    ready = probe_ready
    headline = "环境就绪，选择模板即可运行" if ready else "浏览器扩展未连接"
    return SetupStatus(
        engine="chrome-use",
        ready=ready,
        headline=headline,
        steps=steps,
        can_switch_to_playwright=not ready,
    )
