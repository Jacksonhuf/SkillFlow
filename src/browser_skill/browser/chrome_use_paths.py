from __future__ import annotations

import os
import shutil
from pathlib import Path

from browser_skill.errors import ErrorCode, SkillError

CHROME_USE_INSTALL_HINT = """
chrome-use CLI was not found. The Chrome Web Store extension alone is not enough.

Install the CLI (same project as your extension knfcmbamhjmaonkfnjhldjedeobeafmk):

  Linux / macOS:
    curl -fsSL https://raw.githubusercontent.com/leeguooooo/chrome-use/main/install.sh | sh
    # then ensure ~/.local/bin is on PATH, or:
    export PATH="$HOME/.local/bin:$PATH"

  Or set an explicit binary:
    export CHROME_USE_BIN=/full/path/to/chrome-use

  After install (one time per machine):
    chrome-use extension install
    chrome-use doctor

Docs: https://chrome-use.leeguoo.com/en/install.html
""".strip()


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
