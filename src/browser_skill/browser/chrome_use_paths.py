from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from browser_skill.errors import ErrorCode, SkillError

CHROME_USE_INSTALL_URL = (
    "https://raw.githubusercontent.com/leeguooooo/chrome-use/main/install.sh"
)

CHROME_USE_INSTALL_HINT = """
chrome-use CLI was not found. The Chrome Web Store extension alone is not enough.

Install the CLI (same project as your extension knfcmbamhjmaonkfnjhldjedeobeafmk):

  Linux / macOS:
    curl -fsSL https://raw.githubusercontent.com/leeguooooo/chrome-use/main/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"

  Or set an explicit binary:
    export CHROME_USE_BIN=/full/path/to/chrome-use

  After install (one time per machine):
    chrome-use extension install
    chrome-use doctor

Disable skill auto-install:
    export UNIVERSAL_BROWSER_SKIP_CHROME_USE_INSTALL=1

Docs: https://chrome-use.leeguoo.com/en/install.html
""".strip()


def _prepend_local_bin_to_path() -> None:
    local_bin = Path.home() / ".local" / "bin"
    if local_bin.is_dir():
        current = os.environ.get("PATH", "")
        prefix = str(local_bin)
        if prefix not in current.split(os.pathsep):
            os.environ["PATH"] = f"{prefix}{os.pathsep}{current}" if current else prefix


def _bootstrap_marker(skill_root: Path) -> Path:
    return skill_root / ".universal-browser" / "chrome-use-auto-install.done"


def _run_official_installer() -> None:
    if sys.platform not in {"linux", "darwin"}:
        raise SkillError(
            ErrorCode.CHROME_USE_UNAVAILABLE,
            "Automatic chrome-use CLI install is supported on Linux and macOS only. "
            "On Windows, download chrome-use.exe from GitHub Releases and set CHROME_USE_BIN.\n\n"
            + CHROME_USE_INSTALL_HINT,
            stage="adapter",
        )
    env = os.environ.copy()
    _prepend_local_bin_to_path()
    env["PATH"] = os.environ["PATH"]
    subprocess.run(
        ["bash", "-c", f"curl -fsSL {CHROME_USE_INSTALL_URL} | sh"],
        check=True,
        timeout=300,
        env=env,
    )
    _prepend_local_bin_to_path()


def _register_extension_if_possible(binary: str) -> str | None:
    try:
        completed = subprocess.run(
            [binary, "extension", "install"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode == 0:
        return "Registered chrome-use native bridge: chrome-use extension install"
    detail = (completed.stderr or completed.stdout or "").strip()[:200]
    return f"chrome-use extension install exited {completed.returncode}: {detail or 'see chrome-use doctor'}"


def resolve_chrome_use_executable(name: str = "chrome-use") -> str:
    override = os.environ.get("CHROME_USE_BIN", "").strip()
    if override:
        path = Path(override).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path.resolve())
        raise SkillError(
            ErrorCode.CHROME_USE_UNAVAILABLE,
            f"CHROME_USE_BIN is not executable: {path}\n\n{CHROME_USE_INSTALL_HINT}",
            stage="adapter",
        )

    direct = Path(name).expanduser()
    if direct.is_file() and os.access(direct, os.X_OK):
        return str(direct.resolve())
    _prepend_local_bin_to_path()
    found = shutil.which(name)
    if found:
        return found

    home = Path.home()
    for candidate in (
        home / ".local" / "bin" / name,
        home / "bin" / name,
    ):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())

    raise SkillError(
        ErrorCode.CHROME_USE_UNAVAILABLE,
        f"'{name}' was not found on PATH.\n\n{CHROME_USE_INSTALL_HINT}",
        stage="adapter",
    )


def ensure_chrome_use_executable(
    name: str = "chrome-use",
    *,
    skill_root: Path | None = None,
    auto_install: bool = True,
) -> tuple[str, list[str]]:
    """Resolve chrome-use CLI, optionally running official install.sh on first use."""
    notes: list[str] = []
    try:
        return resolve_chrome_use_executable(name), notes
    except SkillError:
        if not auto_install or os.environ.get("UNIVERSAL_BROWSER_SKIP_CHROME_USE_INSTALL") == "1":
            raise

    root = (skill_root or Path(os.environ.get("UNIVERSAL_BROWSER_SKILL_ROOT", "."))).resolve()
    marker = _bootstrap_marker(root)
    if marker.exists():
        _prepend_local_bin_to_path()
        try:
            return resolve_chrome_use_executable(name), notes
        except SkillError as exc:
            raise SkillError(
                exc.code,
                "Automatic install already ran for this skill copy but chrome-use is still missing.\n\n"
                + CHROME_USE_INSTALL_HINT,
                stage=exc.stage,
            ) from exc

    notes.append("First run: downloading and installing chrome-use CLI (official install.sh)…")
    try:
        _run_official_installer()
    except subprocess.CalledProcessError as exc:
        raise SkillError(
            ErrorCode.CHROME_USE_UNAVAILABLE,
            f"chrome-use auto-install failed (exit {exc.returncode}).\n\n{CHROME_USE_INSTALL_HINT}",
            stage="adapter",
        ) from exc

    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("installed\n", encoding="utf-8")
    notes.append("chrome-use CLI install finished.")

    binary = resolve_chrome_use_executable(name)
    extension_note = _register_extension_if_possible(binary)
    if extension_note:
        notes.append(extension_note)

    return binary, notes
