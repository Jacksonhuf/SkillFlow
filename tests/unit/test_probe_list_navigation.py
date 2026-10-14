from __future__ import annotations

import asyncio
from pathlib import Path

from browser_skill.app import BrowserSkillApp, _list_nav_semantics_from_steps
from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.models import BrowserSnapshot, CommandResult, SkillRequest
from browser_skill.runtime.probe_compiler import ProbeDraftCompiler

SAMPLE_URL = "https://portal.example.com/orders/ORD-2024-0917/detail?tab=files"


def _draft(**overrides: object) -> object:
    from browser_skill.models import ProbeDraftInput

    data: dict = {
        "template_id": "order_files",
        "name": "订单附件下载",
        "sample_url": SAMPLE_URL,
        "url_template": "https://portal.example.com/orders/{order_no}/detail?tab=files",
        "driver_variable": "order_no",
        "fields": [
            {
                "key": "amount",
                "name": "金额",
                "sample": "1",
                "source": "dom",
            }
        ],
        "attachments": [],
        "driver_prompt": "订单号",
    }
    data.update(overrides)
    return ProbeDraftInput.model_validate(data)


def test_list_nav_semantics_from_steps_splits_kinds() -> None:
    steps = [
        {"kind": "input", "label": "订单号", "ref": "@e1", "frame_index": 1},
        {"kind": "action", "label": "查询", "ref": "@e2", "frame_index": 1},
        {"kind": "row", "label": "查看详情"},
    ]
    data = _list_nav_semantics_from_steps(steps)
    assert data["list_nav_input_semantic"] == ["订单号"]
    assert data["list_nav_action_semantic"] == ["查询"]
    assert data["list_nav_row_semantic"] == ["查看详情"]
    assert data["list_nav_input_frame_index"] == 1
    assert data["list_nav_action_frame_index"] == 1


def test_probe_list_navigation_stop_returns_semantics(tmp_path: Path) -> None:
    app = BrowserSkillApp(tmp_path / "templates", tmp_path / "runs", FakeBrowserAdapter())
    response = asyncio.run(
        app.handle(
            SkillRequest(
                action="probe_list_navigation",
                list_nav_recording="stop",
            )
        )
    )
    assert response.ok is True
    assert response.data["list_nav_input_semantic"] == ["订单号"]
    assert response.data["list_nav_action_semantic"] == ["查询"]
    assert response.data["list_nav_input_ref"] == "@e3"
    assert response.data["list_nav_action_ref"] == "@e4"


def test_probe_list_navigation_stop_realigns_refs_from_snapshot(tmp_path: Path) -> None:
    adapter = FakeBrowserAdapter(
        {
            "list_nav_recording": [
                CommandResult(
                    ok=True,
                    operation="probe.list_nav_stop",
                    data={
                        "steps": [
                            {"kind": "input", "label": "订单号", "ref": "@e3"},
                            {"kind": "action", "label": "查询", "ref": "@e4"},
                        ]
                    },
                )
            ],
            "snapshot": [
                BrowserSnapshot(
                    elements=[
                        {"ref": "@e10", "placeholder": "订单号"},
                        {"ref": "@e11", "text": "查询"},
                    ],
                )
            ],
        }
    )
    app = BrowserSkillApp(tmp_path / "templates", tmp_path / "runs", adapter)
    response = asyncio.run(
        app.handle(
            SkillRequest(
                action="probe_list_navigation",
                list_nav_recording="stop",
            )
        )
    )
    assert response.ok is True
    assert response.data["refs_realigned"] == 2
    assert response.data["list_nav_input_ref"] == "@e10"
    assert response.data["list_nav_action_ref"] == "@e11"


def test_compiler_merges_recorded_list_nav_semantics() -> None:
    template = ProbeDraftCompiler().compile(
        _draft(
            navigate_from_list=True,
            list_nav_input_semantic=["我的单号"],
            list_nav_action_semantic=["Go"],
            list_nav_input_ref="@e3",
            list_nav_action_ref="@e4",
            list_nav_input_label="我的单号",
            list_nav_action_label="Go",
            list_nav_input_frame_index=1,
            list_nav_action_frame_index=1,
        ),
        version=1,
    )
    nav = template.run.list_navigation
    assert nav.search_input_semantic[0] == "我的单号"
    assert nav.search_action_semantic[0] == "Go"
    assert "订单号" in nav.search_input_semantic
    assert nav.search_input_ref == "@e3"
    assert nav.search_action_ref == "@e4"
    assert nav.search_input_label == "我的单号"
    assert nav.search_action_label == "Go"
    assert nav.search_input_frame_index == 1
    assert nav.search_action_frame_index == 1


def test_probe_list_navigation_start_reports_cross_origin_iframes(tmp_path: Path) -> None:
    adapter = FakeBrowserAdapter(
        {
            "snapshot": [
                BrowserSnapshot(meta={"cross_origin_iframes": 1}),
            ],
        }
    )
    app = BrowserSkillApp(tmp_path / "templates", tmp_path / "runs", adapter)
    response = asyncio.run(
        app.handle(
            SkillRequest(
                action="probe_list_navigation",
                list_nav_recording="start",
            )
        )
    )
    assert response.ok is True
    assert response.data.get("cross_origin_iframes") == 1
