from __future__ import annotations

import os
import sys
from pathlib import Path

from browser_skill.app import BrowserSkillApp
from browser_skill.browser.auto_engine import plan_engine
from browser_skill.browser.factory import build_adapter


def resolve_skill_root(start: Path | None = None) -> Path:
    """Locate the universal-browser skill directory (contains SKILL.md + templates/)."""
    env = os.environ.get("UNIVERSAL_BROWSER_SKILL_ROOT")
    if env:
        root = Path(env).expanduser().resolve()
        if _looks_like_skill_root(root):
            return root
        raise FileNotFoundError(f"UNIVERSAL_BROWSER_SKILL_ROOT is not a skill root: {root}")

    cursor = (start or Path.cwd()).resolve()
    for candidate in [cursor, *cursor.parents]:
        if _looks_like_skill_root(candidate):
            return candidate
        nested = candidate / "universal-browser"
        if _looks_like_skill_root(nested):
            return nested
    raise FileNotFoundError(
        "Could not find universal-browser skill root (need SKILL.md and templates/). "
        "Set UNIVERSAL_BROWSER_SKILL_ROOT or run from the skill directory."
    )


def _looks_like_skill_root(path: Path) -> bool:
    return (path / "SKILL.md").is_file() and (path / "templates").is_dir()


def bootstrap_runtime_import(skill_root: Path) -> None:
    """Allow importing browser_skill from bundled runtime/ without a global pip install."""
    runtime_src = skill_root / "runtime" / "src"
    if not runtime_src.is_dir():
        raise FileNotFoundError(
            f"Bundled runtime missing at {runtime_src}. Use the full skill package "
            "(universal-browser-full-*.zip), not the slim SKILL-only zip."
        )
    src = str(runtime_src)
    if src not in sys.path:
        sys.path.insert(0, src)


def make_standalone_app(
    skill_root: Path | None = None,
    *,
    chrome_use_executable: str = "chrome-use",
    auto_install_chrome_use: bool = True,
    engine: str | None = None,
) -> BrowserSkillApp:
    """Build the app for the bundled skill directory.

    ``engine`` defaults to ``auto``: reuse an existing chrome-use CLI, otherwise drive the
    user's Chrome through Playwright (installed on demand). Nothing here asks the user anything.
    """
    root = skill_root or resolve_skill_root()
    bootstrap_runtime_import(root)
    runs = root / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    plan = plan_engine(
        engine,
        skill_root=root,
        chrome_use_executable=chrome_use_executable,
        auto_install=auto_install_chrome_use,
    )
    if plan.engine == "chrome-use":
        from browser_skill.browser.chrome_use_paths import ensure_chrome_use_executable

        resolved = plan.chrome_use_executable
        if resolved is None:
            resolved, _notes = ensure_chrome_use_executable(
                chrome_use_executable,
                skill_root=root,
                auto_install=auto_install_chrome_use,
            )
        adapter = build_adapter(plan.engine, chrome_use_executable=resolved, skill_root=root)
    else:
        adapter = build_adapter(plan.engine, skill_root=root)
    return BrowserSkillApp(
        templates_root=root / "templates",
        runs_root=runs,
        adapter=adapter,
        samples_root=runs / "uploads",
    )
