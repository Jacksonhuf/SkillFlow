from __future__ import annotations

from pathlib import Path

import pytest

from browser_skill.browser import chrome_use_paths as paths
from browser_skill.errors import ErrorCode, SkillError


def test_ensure_skips_when_binary_present(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    binary = tmp_path / "chrome-use"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    monkeypatch.setenv("CHROME_USE_BIN", str(binary))

    resolved, notes = paths.ensure_chrome_use_executable(skill_root=tmp_path)
    assert resolved == str(binary.resolve())
    assert notes == []


def test_ensure_respects_disable_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHROME_USE_BIN", raising=False)
    monkeypatch.setattr(paths.shutil, "which", lambda _name: None)

    with pytest.raises(SkillError, match=r"Chrome Web Store"):
        paths.ensure_chrome_use_executable(skill_root=tmp_path, auto_install=False)


def test_ensure_non_windows_skips_auto_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CHROME_USE_BIN", raising=False)
    monkeypatch.setattr(paths.shutil, "which", lambda _name: None)

    with pytest.raises(SkillError, match="Windows-only"):
        paths.ensure_chrome_use_executable(skill_root=tmp_path, auto_install=True)


def test_ensure_runs_windows_installer_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNIVERSAL_BROWSER_SKILL_ROOT", str(tmp_path))
    monkeypatch.setattr(paths.sys, "platform", "win32")

    binary = tmp_path / ".universal-browser" / "chrome-use" / "chrome-use.exe"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text("stub", encoding="utf-8")

    call_count = {"n": 0}

    def resolve_side_effect(name: str = "chrome-use") -> str:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise SkillError(ErrorCode.CHROME_USE_UNAVAILABLE, "missing", stage="adapter")
        return str(binary.resolve())

    monkeypatch.setattr(paths, "resolve_chrome_use_executable", resolve_side_effect)

    def fake_installer(root: Path) -> Path:
        assert root == tmp_path.resolve()
        return binary

    monkeypatch.setattr(paths, "_run_windows_installer", fake_installer)
    monkeypatch.setattr(
        paths,
        "_register_extension_if_possible",
        lambda _binary: "Registered chrome-use native bridge",
    )

    resolved, notes = paths.ensure_chrome_use_executable(skill_root=tmp_path)
    assert resolved == str(binary.resolve())
    assert (tmp_path / ".universal-browser" / "chrome-use-auto-install.done").is_file()
    assert any("Windows bundle" in n for n in notes)


def test_find_windows_exe_prefers_direct_child(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    exe = bundle / "chrome-use.exe"
    exe.write_text("x", encoding="utf-8")
    assert paths._find_windows_exe(bundle) == exe


def test_bundled_windows_executable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setenv("UNIVERSAL_BROWSER_SKILL_ROOT", str(tmp_path))
    exe = tmp_path / ".universal-browser" / "chrome-use" / "chrome-use.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("stub", encoding="utf-8")
    assert paths.resolve_chrome_use_executable() == str(exe.resolve())
