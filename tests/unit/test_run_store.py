import asyncio
from pathlib import Path

from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.models import BrowserSnapshot, RunState
from browser_skill.runtime.run_store import RunStore
from browser_skill.runtime.runner import Runner


def test_status_and_cancel_auth_paused_run(tmp_path: Path, template) -> None:
    adapter = FakeBrowserAdapter(
        {"snapshot": [BrowserSnapshot(url="https://example.internal/login", text="用户名 登录")]}
    )
    response = asyncio.run(Runner(adapter, tmp_path).run(template, {}))
    assert response.state == RunState.WAIT_USER_AUTH
    store = RunStore(tmp_path)
    assert store.load(str(response.run_id)).state == RunState.WAIT_USER_AUTH
    cancelled = store.cancel(str(response.run_id))
    assert cancelled.state == RunState.CANCELLED
    assert store.cancellation_requested(str(response.run_id))
    assert store.load(str(response.run_id)).state == RunState.CANCELLED


def test_cancel_terminal_run_is_idempotent(tmp_path: Path, template) -> None:
    adapter = FakeBrowserAdapter(
        {
            "snapshot": [
                BrowserSnapshot(
                    url="https://example.internal/home",
                    text="退出登录",
                    records=[{"sample_id": "S1", "sn": "SN1"}],
                )
            ]
        }
    )
    response = asyncio.run(Runner(adapter, tmp_path).run(template, {}))
    context = RunStore(tmp_path).cancel(str(response.run_id))
    assert context.state == RunState.COMPLETED
    assert not RunStore(tmp_path).cancellation_requested(str(response.run_id))
