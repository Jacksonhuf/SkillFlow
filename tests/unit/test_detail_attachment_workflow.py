from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path

from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.models import BrowserSnapshot, BrowserTemplate, WorkflowHint
from browser_skill.runtime.detail import DetailCollector


def _detail_template(template_data: dict) -> BrowserTemplate:
    data = deepcopy(template_data)
    data["workflow"]["hints"] = [
        WorkflowHint(action="query", target="展开附件", phase="attachments").model_dump()
    ]
    return BrowserTemplate.model_validate(data)


def test_detail_collector_runs_prepare_and_refresh_before_download(
    template_data: dict, tmp_path: Path
) -> None:
    template = _detail_template(template_data)
    list_page = BrowserSnapshot(
        url="https://example.internal/list",
        elements=[{"record_key": "SN-1", "text": "查看详情", "ref": "@detail"}],
    )
    detail_page = BrowserSnapshot(
        url="https://example.internal/detail/1",
        text="SN-1",
        elements=[
            {
                "record_key": "SN-1",
                "text": "凭证附件",
                "ref": "@download",
                "filename": "evidence.pdf",
            }
        ],
    )
    expanded = BrowserSnapshot(
        url="https://example.internal/detail/1",
        text="SN-1 附件已展开",
        elements=[
            {
                "record_key": "SN-1",
                "text": "凭证附件",
                "ref": "@download",
                "filename": "evidence.pdf",
                "href": "https://example.internal/files/evidence.pdf",
            }
        ],
    )
    adapter = FakeBrowserAdapter(
        {"snapshot": [detail_page, BrowserSnapshot(url="https://example.internal/list")]}
    )
    prepare_calls: list[str] = []

    async def prepare(snapshot: BrowserSnapshot) -> BrowserSnapshot:
        prepare_calls.append(snapshot.text)
        return expanded

    async def refresh() -> list:
        return []

    result = asyncio.run(
        DetailCollector().collect(
            adapter,
            template,
            list_page,
            [{"sample_id": "S1", "sn": "SN-1"}],
            tmp_path,
            prepare_attachments=prepare,
            refresh_exchanges=refresh,
        )
    )
    assert prepare_calls == ["SN-1"]
    assert result.files[0].status == "ok"
