import asyncio
import os
from pathlib import Path

import pytest

from browser_skill.browser.chrome_use import ChromeUseAdapter
from browser_skill.errors import SkillError
from browser_skill.outputs.writer import RunWorkspace


def executable(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "fake-chrome-use"
    path.write_text(f"#!/usr/bin/python3\n{body}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_cli_timeout_kills_process_and_returns_retryable_domain_error(tmp_path: Path) -> None:
    command = executable(tmp_path, "import time\ntime.sleep(5)")
    adapter = ChromeUseAdapter(str(command), timeout=0.02)

    with pytest.raises(SkillError) as raised:
        asyncio.run(adapter.open("https://example.internal"))

    assert raised.value.code.value == "E_CHROME_USE_UNAVAILABLE"
    assert raised.value.retryable is True
    assert "timed out" in raised.value.message


def test_cli_malformed_json_is_treated_as_untrusted_snapshot_text(tmp_path: Path) -> None:
    command = executable(tmp_path, 'print("{not-json")')
    snapshot = asyncio.run(ChromeUseAdapter(str(command)).snapshot())

    assert snapshot.text == "{not-json"
    assert snapshot.elements == []


def test_atomic_write_failure_removes_temporary_file(tmp_path: Path, monkeypatch) -> None:
    workspace = RunWorkspace(tmp_path, "run_atomic")

    def fail_replace(_source: str | Path, _target: str | Path) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected replace failure"):
        workspace.atomic_json("summary.json", {"ok": True})

    assert not (workspace.path / "summary.json").exists()
    assert list(workspace.path.glob(".summary.json.*")) == []


def test_duplicate_run_workspace_is_rejected(tmp_path: Path) -> None:
    RunWorkspace(tmp_path, "run_duplicate")

    with pytest.raises(FileExistsError):
        RunWorkspace(tmp_path, "run_duplicate")


def test_cli_arguments_are_not_interpreted_by_a_shell(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist"
    command = executable(
        tmp_path,
        "import json, sys\nprint(json.dumps(sys.argv[1:]))",
    )
    payload = f"target;touch {marker}"

    result = asyncio.run(ChromeUseAdapter(str(command)).find(payload))

    assert result.ok is True
    assert result.data == ["find", payload]
    assert not marker.exists()


def test_cli_sensitive_value_is_redacted_from_safe_diagnostics(tmp_path: Path) -> None:
    command = executable(
        tmp_path,
        "import sys\nprint(sys.argv[-1], file=sys.stderr)\nraise SystemExit(1)",
    )
    adapter = ChromeUseAdapter(str(command))

    result = asyncio.run(adapter.fill("username", "top-secret", sensitive=True))

    assert result.ok is False
    assert "top-secret" not in result.safe_stderr
    assert "top-secret" not in " ".join(adapter.last_safe_command)
    assert "***" in result.safe_stderr
