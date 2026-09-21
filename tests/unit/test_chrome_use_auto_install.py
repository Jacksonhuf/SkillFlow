from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

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

    with pytest.raises(SkillError, match="install.sh"):
        paths.ensure_chrome_use_executable(skill_root=tmp_path, auto_install=False)


def test_ensure_runs_installer_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHROME_USE_BIN", raising=False)
    calls: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        if "curl" in str(cmd):
            return MagicMock(returncode=0)
        return MagicMock(returncode=0)

    monkeypatch.setattr(paths.subprocess, "run", fake_run)

    binary = tmp_path / "chrome-use"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)

    call_count = {"n": 0}

    def resolve_side_effect(name: str = "chrome-use") -> str:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise SkillError(ErrorCode.CHROME_USE_UNAVAILABLE, "missing", stage="adapter")
        return str(binary.resolve())

    monkeypatch.setattr(paths, "resolve_chrome_use_executable", resolve_side_effect)

    resolved, notes = paths.ensure_chrome_use_executable(skill_root=tmp_path)
    assert resolved == str(binary.resolve())
    assert any("curl" in " ".join(c) for c in calls)
    assert (tmp_path / ".universal-browser" / "chrome-use-auto-install.done").is_file()
    assert any("First run" in n for n in notes)
