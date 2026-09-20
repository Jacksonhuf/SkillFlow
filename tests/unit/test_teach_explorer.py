import asyncio
from copy import deepcopy

import pytest

from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.errors import SkillError
from browser_skill.models import BrowserSnapshot, BrowserTemplate, CommandResult
from browser_skill.runtime.teach_explorer import TeachExplorer


def test_explores_declared_pages_and_detail_with_bounded_safe_actions(template_data) -> None:
    data = deepcopy(template_data)
    data["learned"]["page_hints"] = ["资产管理", "盘点反馈"]
    data["target"]["fields"][2]["source"] = "detail"
    data["target"]["fields"][2]["required"] = True
    data["target"]["attachments"][0]["required"] = True
    template = BrowserTemplate.model_validate(data)
    adapter = FakeBrowserAdapter(
        {
            "find_result": [
                CommandResult(ok=True, operation="find", data={"ref": "@assets"}),
                CommandResult(ok=True, operation="find", data={"ref": "@inventory"}),
                CommandResult(ok=True, operation="find", data={"ref": "@detail"}),
            ],
            "snapshot": [
                BrowserSnapshot(
                    url="https://example.internal/assets",
                    text="退出登录",
                    elements=[{"text": "样机ID"}],
                ),
                BrowserSnapshot(
                    url="https://example.internal/inventory",
                    text="退出登录",
                    elements=[{"text": "样机ID"}, {"text": "SN"}],
                ),
                BrowserSnapshot(
                    url="https://example.internal/detail/1",
                    text="退出登录",
                    elements=[{"text": "产品型号"}, {"text": "盘点凭证"}],
                ),
            ],
        }
    )

    result = asyncio.run(
        TeachExplorer(max_steps=12).explore(
            adapter,
            template,
            BrowserSnapshot(url="https://example.internal/home", text="退出登录"),
        )
    )

    assert result.report.publishable_candidate is True
    assert result.report.learned.field_mappings["product_model"].page == "detail"
    assert result.report.learned.attachment_mappings["inventory_evidence"].page == "detail"
    assert result.visited_urls == [
        "https://example.internal/home",
        "https://example.internal/assets",
        "https://example.internal/inventory",
        "https://example.internal/detail/1",
    ]
    assert result.steps == 10
    assert any(call[0] == "do_action" for call in adapter.calls)


def test_rejects_cross_host_snapshot_during_exploration(template_data) -> None:
    data = deepcopy(template_data)
    data["learned"]["page_hints"] = ["盘点反馈"]
    template = BrowserTemplate.model_validate(data)
    adapter = FakeBrowserAdapter(
        {
            "find_result": [CommandResult(ok=True, operation="find", data={"ref": "@menu"})],
            "snapshot": [BrowserSnapshot(url="https://evil.example/phishing", text="退出登录")],
        }
    )

    with pytest.raises(SkillError, match="outside the template host scope"):
        asyncio.run(
            TeachExplorer().explore(
                adapter,
                template,
                BrowserSnapshot(url="https://example.internal/home", text="退出登录"),
            )
        )


def test_budget_exhaustion_stops_exploration(template_data) -> None:
    data = deepcopy(template_data)
    data["learned"]["page_hints"] = ["资产管理", "盘点反馈"]
    template = BrowserTemplate.model_validate(data)
    adapter = FakeBrowserAdapter(
        {
            "find_result": [CommandResult(ok=True, operation="find", data={"ref": "@assets"})],
        }
    )

    result = asyncio.run(
        TeachExplorer(max_steps=2).explore(
            adapter,
            template,
            BrowserSnapshot(url="https://example.internal/home", text="退出登录"),
        )
    )

    assert result.budget_exhausted is True
    assert result.steps == 2
    assert not any(call[0] == "snapshot_args" for call in adapter.calls)
