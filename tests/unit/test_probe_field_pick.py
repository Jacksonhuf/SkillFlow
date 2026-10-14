from __future__ import annotations

import asyncio
from pathlib import Path

from browser_skill.app import BrowserSkillApp, _field_candidates_from_picks
from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.models import SkillRequest
from browser_skill.runtime.probe_compiler import ProbeDraftCompiler


def test_field_candidates_from_picks_assigns_dom_ref() -> None:
    fields = _field_candidates_from_picks(
        [{"ref": "@e3", "text": "100", "label": "金额"}, {"ref": "bad", "text": "x"}]
    )
    assert len(fields) == 1
    assert fields[0]["name"] == "金额"
    assert fields[0]["key"] == "ref_e3"
    assert fields[0]["dom_ref"] == "@e3"
    assert fields[0]["recommended"] is True


def test_probe_field_pick_start_includes_cross_origin_count(tmp_path: Path) -> None:
    from browser_skill.models import BrowserSnapshot

    adapter = FakeBrowserAdapter(
        {
            "snapshot": [
                BrowserSnapshot(
                    url="https://example.internal/detail",
                    meta={"cross_origin_iframes": 2},
                )
            ]
        }
    )
    app = BrowserSkillApp(tmp_path / "templates", tmp_path / "runs", adapter)
    response = asyncio.run(
        app.handle(
            SkillRequest(
                action="probe_field_pick",
                field_pick_recording="start",
                url="https://example.internal/detail",
            )
        )
    )
    assert response.ok is True
    assert response.data.get("cross_origin_iframes") == 2


def test_probe_field_pick_stop_returns_fields(tmp_path: Path) -> None:
    app = BrowserSkillApp(tmp_path / "templates", tmp_path / "runs", FakeBrowserAdapter())
    response = asyncio.run(
        app.handle(
            SkillRequest(
                action="probe_field_pick",
                field_pick_recording="stop",
            )
        )
    )
    assert response.ok is True
    assert response.data["fields"][0]["dom_ref"] == "@e9"
    assert response.data["fields"][0]["sample"] == "ACME"


def test_probe_compiler_uses_dom_ref_for_dom_hint() -> None:
    from tests.unit.test_probe_compiler import _draft

    draft = _draft(
        fields=[
            {
                "key": "customer",
                "name": "客户",
                "sample": "ACME",
                "source": "dom",
                "dom_ref": "@e9",
            }
        ],
        driver_prompt="订单号",
    )
    template = ProbeDraftCompiler().compile(draft, version=1)
    mapping = template.learned.field_mappings["customer"]
    assert mapping.strategy == "dom_hint"
    assert mapping.hints == ["@e9"]
