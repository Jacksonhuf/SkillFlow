from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request
from pathlib import Path

from browser_skill.errors import ErrorCode, SkillError

CHROME_USE_GITHUB_REPO = "leeguooooo/chrome-use"
CHROME_USE_WINDOWS_ASSET = "chrome-use-win32-x64.tar.gz"
# Pin release; override with CHROME_USE_INSTALL_VERSION=v1.x.x when needed.
CHROME_USE_WINDOWS_RELEASE = os.environ.get("CHROME_USE_INSTALL_VERSION", "v1.5.131")

CHROME_USE_INSTALL_HINT = """
chrome-use CLI was not found. The Chrome Web Store extension alone is not enough.

Windows (manual):
  Download chrome-use-win32-x64.tar.gz from:
  https://github.com/leeguooooo/chrome-use/releases
  Extract chrome-use.exe and either add it to PATH or set:
    set CHROME_USE_BIN=C:\\path\\to\\chrome-use.exe

First-run auto-install (Windows only):
  Run once from the skill directory:
    py scripts\\invoke.py doctor
  The skill downloads the official win32 bundle into .universal-browser\\chrome-use\\

After install (one time per machine):
  chrome-use extension install
  chrome-use doctor

Disable skill auto-install:
  set UNIVERSAL_BROWSER_SKIP_CHROME_USE_INSTALL=1

Docs: https://chrome-use.leeguoo.com/en/install.html
""".strip()

_USER_BROWSER_ENV_MESSAGE = "浏览器自动化环境尚未就绪，请稍后重试。"
_USER_BROWSER_INIT_FAILED = "浏览器自动化环境初始化失败，请稍后重试或联系管理员。"


def _operator_details(**extra: object) -> dict[str, object]:
    details: dict[str, object] = {"operator_guide": CHROME_USE_INSTALL_HINT}
    details.update(extra)
    return details


def _chrome_use_unavailable(
    user_message: str = _USER_BROWSER_ENV_MESSAGE,
    *,
    stage: str = "adapter",
    retryable: bool = True,
    **details: object,
) -> SkillError:
    return SkillError(
        ErrorCode.CHROME_USE_UNAVAILABLE,
        user_message,
        stage=stage,
        retryable=retryable,
        details=_operator_details(**details),
    )


def _skill_root_from_env() -> Path | None:
    env = os.environ.get("UNIVERSAL_BROWSER_SKILL_ROOT", "").strip()
    if not env:
        return None
    return Path(env).expanduser().resolve()


def _windows_bundle_dir(skill_root: Path) -> Path:
    return skill_root / ".universal-browser" / "chrome-use"


def _bootstrap_marker(skill_root: Path) -> Path:
    return skill_root / ".universal-browser" / "chrome-use-auto-install.done"


def _find_windows_exe(directory: Path) -> Path | None:
    direct = directory / "chrome-use.exe"
    if direct.is_file():
        return direct
    matches = sorted(directory.rglob("chrome-use.exe"))
    if len(matches) == 1:
        return matches[0]
    if matches:
        return matches[0]
    return None


def _bundled_windows_executable(skill_root: Path | None) -> str | None:
    if sys.platform != "win32" or skill_root is None:
        return None
    exe = _find_windows_exe(_windows_bundle_dir(skill_root))
    if exe and exe.is_file():
        return str(exe.resolve())
    return None


def _windows_download_url() -> str:
    release = CHROME_USE_WINDOWS_RELEASE
    version = release if release.startswith("v") else f"v{release.lstrip('v')}"
    return (
        f"https://github.com/{CHROME_USE_GITHUB_REPO}/releases/download/"
        f"{version}/{CHROME_USE_WINDOWS_ASSET}"
    )


def _run_windows_installer(skill_root: Path) -> Path:
    if sys.platform != "win32":
        raise _chrome_use_unavailable(stage="adapter")

    dest_dir = _windows_bundle_dir(skill_root)
    dest_dir.mkdir(parents=True, exist_ok=True)
    archive = dest_dir / CHROME_USE_WINDOWS_ASSET
    url = _windows_download_url()

    try:
        with urllib.request.urlopen(url, timeout=300) as response:
            archive.write_bytes(response.read())
    except (urllib.error.URLError, TimeoutError) as exc:
        raise _chrome_use_unavailable(
            _USER_BROWSER_INIT_FAILED,
            stage="adapter",
            download_url=url,
        ) from exc

    try:
        with tarfile.open(archive, "r:gz") as archive_file:
            archive_file.extractall(dest_dir, filter="data")
    except (tarfile.TarError, OSError) as exc:
        raise _chrome_use_unavailable(
            _USER_BROWSER_INIT_FAILED,
            stage="adapter",
            archive=str(archive),
        ) from exc

    exe = _find_windows_exe(dest_dir)
    if exe is None:
        raise _chrome_use_unavailable(
            _USER_BROWSER_INIT_FAILED,
            stage="adapter",
            extract_dir=str(dest_dir),
        )

    os.environ["CHROME_USE_BIN"] = str(exe.resolve())
    return exe


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
    fallback = detail or "see chrome-use doctor"
    return f"chrome-use extension install exited {completed.returncode}: {fallback}"


def _is_executable_file(path: Path) -> bool:
    if not path.is_file():
        return False
    if sys.platform == "win32":
        return True
    return os.access(path, os.X_OK)


def resolve_chrome_use_executable(name: str = "chrome-use") -> str:
    skill_root = _skill_root_from_env()
    bundled = _bundled_windows_executable(skill_root)
    if bundled:
        return bundled

    override = os.environ.get("CHROME_USE_BIN", "").strip()
    if override:
        path = Path(override).expanduser()
        if _is_executable_file(path):
            return str(path.resolve())
        raise _chrome_use_unavailable(
            _USER_BROWSER_ENV_MESSAGE,
            stage="adapter",
            chrome_use_bin=str(path),
        )

    direct = Path(name).expanduser()
    if _is_executable_file(direct):
        return str(direct.resolve())

    search_names = [name]
    if sys.platform == "win32" and not name.lower().endswith(".exe"):
        search_names.append(f"{name}.exe")

    for candidate_name in search_names:
        found = shutil.which(candidate_name)
        if found:
            return found

    raise _chrome_use_unavailable(stage="adapter", executable=name)


def ensure_chrome_use_executable(
    name: str = "chrome-use",
    *,
    skill_root: Path | None = None,
    auto_install: bool = True,
) -> tuple[str, list[str]]:
    """Resolve chrome-use CLI; on Windows, download official release on first use."""
    notes: list[str] = []
    root = (skill_root or _skill_root_from_env() or Path(".")).resolve()

    try:
        return resolve_chrome_use_executable(name), notes
    except SkillError as exc:
        if not auto_install or os.environ.get("UNIVERSAL_BROWSER_SKIP_CHROME_USE_INSTALL") == "1":
            raise _chrome_use_unavailable(stage=exc.stage or "adapter") from exc
        if sys.platform != "win32":
            raise _chrome_use_unavailable(_USER_BROWSER_INIT_FAILED, stage="adapter") from None

    marker = _bootstrap_marker(root)
    if marker.exists():
        bundled = _bundled_windows_executable(root)
        if bundled:
            return bundled, notes
        try:
            return resolve_chrome_use_executable(name), notes
        except SkillError as exc:
            raise _chrome_use_unavailable(
                _USER_BROWSER_INIT_FAILED,
                stage=exc.stage or "adapter",
            ) from exc

    try:
        exe = _run_windows_installer(root)
    except SkillError:
        raise
    except Exception as exc:
        raise _chrome_use_unavailable(
            _USER_BROWSER_INIT_FAILED,
            stage="adapter",
            reason=str(exc),
        ) from exc

    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(f"installed:{exe}\n", encoding="utf-8")

    binary = str(exe.resolve())
    _register_extension_if_possible(binary)

    return binary, notes
