import pytest

from browser_skill.browser.chrome_use_paths import resolve_chrome_use_executable
from browser_skill.errors import SkillError


def test_resolve_honors_chrome_use_bin(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    binary = tmp_path / "chrome-use"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    monkeypatch.setenv("CHROME_USE_BIN", str(binary))
    assert resolve_chrome_use_executable() == str(binary.resolve())


def test_resolve_raises_with_install_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHROME_USE_BIN", raising=False)
    monkeypatch.setattr("browser_skill.browser.chrome_use_paths.shutil.which", lambda _name: None)
    with pytest.raises(SkillError, match=r"Chrome Web Store"):
        resolve_chrome_use_executable("missing-binary")
