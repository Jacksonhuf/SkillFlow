from __future__ import annotations

from pathlib import Path

import pytest

from browser_skill.browser import factory
from browser_skill.browser.chrome_use import ChromeUseAdapter
from browser_skill.browser.playwright_adapter import PlaywrightAdapter
from browser_skill.errors import SkillError


def test_default_engine_is_chrome_use(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(factory.ENGINE_ENV, raising=False)
    adapter = factory.build_adapter(chrome_use_executable="/opt/chrome-use")
    assert isinstance(adapter, ChromeUseAdapter)
    assert adapter.executable == "/opt/chrome-use"


def test_env_selects_playwright_with_cdp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(factory.ENGINE_ENV, "playwright")
    monkeypatch.setenv(factory.CDP_URL_ENV, "http://127.0.0.1:9222")
    monkeypatch.delenv(factory.PROFILE_DIR_ENV, raising=False)
    adapter = factory.build_adapter(skill_root=tmp_path)
    assert isinstance(adapter, PlaywrightAdapter)
    assert adapter.mode == "cdp" and adapter.cdp_url == "http://127.0.0.1:9222"
    assert adapter.downloads_dir == tmp_path / "runs" / "downloads"


def test_playwright_defaults_to_persistent_profile_under_skill_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv(factory.CDP_URL_ENV, raising=False)
    monkeypatch.delenv(factory.PROFILE_DIR_ENV, raising=False)
    monkeypatch.setenv(factory.HEADLESS_ENV, "1")
    adapter = factory.build_adapter("pw", skill_root=tmp_path)
    assert isinstance(adapter, PlaywrightAdapter)
    assert adapter.mode == "persistent_profile"
    assert adapter.user_data_dir == tmp_path / "runs" / "chrome-profile"
    assert adapter.headless is True


def test_unknown_engine_is_rejected() -> None:
    with pytest.raises(SkillError):
        factory.resolve_engine("selenium")


def test_playwright_capabilities_and_sessions_without_connecting() -> None:
    pytest.importorskip("playwright")
    import asyncio

    adapter = PlaywrightAdapter(cdp_url="http://127.0.0.1:1")
    caps = asyncio.run(adapter.capabilities())
    assert caps.snapshot and caps.network and caps.dialogs and not caps.snapshot_diff
    sessions = asyncio.run(adapter.list_sessions())
    assert sessions.data[0]["mode"] == "cdp" and sessions.data[0]["connected"] is False
    assert asyncio.run(adapter.get_dialog_status()).data == {"open": False}
