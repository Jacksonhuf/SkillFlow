"""Minimal platform bridge: register this as an Agent tool alongside OpenCode skills.

OpenCode loads SKILL.md for *instructions*; this module shows how to *execute* with chrome-use.
Adapt `call_your_chrome_use` to your existing platform client.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from browser_skill.app import BrowserSkillApp
from browser_skill.browser.chrome_use import ChromeUseToolAdapter
from browser_skill.models import SkillRequest


async def call_your_chrome_use(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Replace with your platform's existing chrome-use RPC/MCP/plugin call."""
    raise NotImplementedError("Wire this to your company's chrome-use tool")


def build_app(user_id: str) -> BrowserSkillApp:
    root = Path(__file__).resolve().parents[1]
    return BrowserSkillApp(
        templates_root=root / "templates",
        runs_root=root / "runs" / user_id,
        adapter=ChromeUseToolAdapter(call_your_chrome_use),
    )


async def handle_user_message(user_id: str, action: str, **payload: Any) -> dict[str, Any]:
    """Example tool entry: map platform JSON to SkillRequest."""
    app = build_app(user_id)
    request = SkillRequest(action=action, **payload)  # type: ignore[arg-type]
    response = await app.handle(request)
    return response.model_dump(mode="json")
