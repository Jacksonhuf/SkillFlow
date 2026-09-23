from __future__ import annotations

from pathlib import Path

from browser_skill.console.server import resolve_console_token


def test_console_token_persists_in_runs_dir(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    first = resolve_console_token(runs)
    second = resolve_console_token(runs)
    assert first == second
    assert (runs / ".console-token").is_file()
