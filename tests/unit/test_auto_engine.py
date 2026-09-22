from __future__ import annotations

from pathlib import Path

import pytest

from browser_skill.browser import auto_engine
from browser_skill.browser.factory import CDP_URL_ENV, ENGINE_ENV, PROFILE_DIR_ENV
from browser_skill.browser.playwright_adapter import PlaywrightAdapter
from browser_skill.standalone import make_standalone_app


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (ENGINE_ENV, CDP_URL_ENV, PROFILE_DIR_ENV, auto_engine.NO_AUTO_PIP_ENV):
        monkeypatch.delenv(name, raising=False)


def test_explicit_engine_wins_over_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auto_engine, "chrome_use_available", lambda *a, **k: "/opt/chrome-use")
    plan = auto_engine.plan_engine("playwright")
    assert plan.engine == "playwright" and plan.reason == "explicit"

    monkeypatch.setenv(ENGINE_ENV, "chrome-use")
    assert auto_engine.plan_engine().engine == "chrome-use"


def test_existing_chrome_use_cli_is_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auto_engine, "chrome_use_available", lambda *a, **k: "/opt/chrome-use")
    monkeypatch.setattr(auto_engine, "playwright_available", lambda: True)
    plan = auto_engine.plan_engine()
    assert plan.engine == "chrome-use"
    assert plan.chrome_use_executable == "/opt/chrome-use"


def test_playwright_preferred_when_no_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auto_engine, "chrome_use_available", lambda *a, **k: None)
    monkeypatch.setattr(auto_engine, "playwright_available", lambda: True)
    installs: list[str] = []
    monkeypatch.setattr(auto_engine, "install_playwright", lambda **k: installs.append("x"))
    plan = auto_engine.plan_engine()
    assert plan.engine == "playwright" and not installs


def test_playwright_installed_on_demand(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auto_engine, "chrome_use_available", lambda *a, **k: None)
    monkeypatch.setattr(auto_engine, "playwright_available", lambda: False)
    monkeypatch.setattr(auto_engine, "install_playwright", lambda **k: (True, "已安装 Playwright"))
    plan = auto_engine.plan_engine()
    assert plan.engine == "playwright"
    assert "已安装 Playwright" in plan.notes


def test_pip_opt_out_falls_back_to_chrome_use(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auto_engine, "chrome_use_available", lambda *a, **k: None)
    monkeypatch.setattr(auto_engine, "playwright_available", lambda: False)
    monkeypatch.setenv(auto_engine.NO_AUTO_PIP_ENV, "1")
    called = False

    def _boom(**_: object) -> tuple[bool, str]:
        nonlocal called
        called = True
        return True, ""

    monkeypatch.setattr(auto_engine, "install_playwright", _boom)
    plan = auto_engine.plan_engine()
    assert plan.engine == "chrome-use" and not called
    assert plan.chrome_use_executable is None


def test_failed_install_falls_back_to_chrome_use(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auto_engine, "chrome_use_available", lambda *a, **k: None)
    monkeypatch.setattr(auto_engine, "playwright_available", lambda: False)
    monkeypatch.setattr(auto_engine, "install_playwright", lambda **k: (False, "pip 失败"))
    plan = auto_engine.plan_engine()
    assert plan.engine == "chrome-use" and "pip 失败" in plan.notes


def test_playwright_setup_status_reports_missing_pieces(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(auto_engine, "playwright_available", lambda: False)
    monkeypatch.setattr(auto_engine, "find_chrome", lambda: None)
    status = auto_engine.playwright_setup_status(skill_root=tmp_path)
    assert status.ready is False
    by_key = {step.key: step for step in status.steps}
    assert by_key["playwright"].action == "install_playwright"
    assert by_key["chrome"].link == auto_engine.CHROME_DOWNLOAD_URL
    assert "首次运行" in by_key["login"].detail

    monkeypatch.setattr(auto_engine, "playwright_available", lambda: True)
    monkeypatch.setattr(auto_engine, "find_chrome", lambda: "/usr/bin/google-chrome")
    profile = tmp_path / "runs" / "chrome-profile"
    profile.mkdir(parents=True)
    (profile / "Default").mkdir()
    status = auto_engine.playwright_setup_status(skill_root=tmp_path)
    assert status.ready is True
    assert "自动复用" in {s.key: s for s in status.steps}["login"].detail


def test_chrome_use_setup_status_offers_switch() -> None:
    status = auto_engine.chrome_use_setup_status(
        probe_ready=False, probe_status_ok=False, executable="/x/chrome-use"
    )
    assert status.ready is False and status.can_switch_to_playwright is True
    assert any(step.action == "switch_to_playwright" for step in status.steps)


def _skill_dir(tmp_path: Path) -> Path:
    root = tmp_path / "skill"
    (root / "templates").mkdir(parents=True)
    (root / "runtime" / "src").mkdir(parents=True)
    (root / "SKILL.md").write_text("# skill", encoding="utf-8")
    return root


def test_standalone_app_uses_playwright_when_auto_picks_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(auto_engine, "chrome_use_available", lambda *a, **k: None)
    monkeypatch.setattr(auto_engine, "playwright_available", lambda: True)
    root = _skill_dir(tmp_path)
    app = make_standalone_app(root)
    assert isinstance(app.adapter, PlaywrightAdapter)
    assert app.adapter.user_data_dir == root / "runs" / "chrome-profile"
