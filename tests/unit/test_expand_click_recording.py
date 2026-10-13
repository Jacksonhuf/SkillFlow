from __future__ import annotations

import asyncio

from browser_skill.app import BrowserSkillApp
from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.models import CommandResult, SkillRequest


def test_probe_expand_clicks_start_and_stop(tmp_path) -> None:
    adapter = FakeBrowserAdapter(
        {
            "expand_click_recording": [
                CommandResult(
                    ok=True,
                    operation="probe.record_stop",
                    data={"clicks": ["展开附件", "更多"]},
                )
            ]
        }
    )
    app = BrowserSkillApp(tmp_path / "templates", tmp_path / "runs", adapter)
    sample = "https://example.internal/orders/1/detail"
    started = asyncio.run(
        app.handle(
            SkillRequest(
                action="probe_expand_clicks",
                expand_click_recording="start",
                url=sample,
            )
        )
    )
    assert any(call[0] == "open" and call[1][0] == sample for call in adapter.calls)
    assert started.ok
    stopped = asyncio.run(
        app.handle(
            SkillRequest(action="probe_expand_clicks", expand_click_recording="stop")
        )
    )
    assert stopped.ok
    assert stopped.data["clicks"] == ["展开附件", "更多"]
