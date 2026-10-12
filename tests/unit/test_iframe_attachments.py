from __future__ import annotations

import asyncio
from pathlib import Path

from browser_skill.acquire import attachments as attach
from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.models import (
    AttachmentSpec,
    BrowserSnapshot,
    BrowserTemplate,
    CommandResult,
)
from browser_skill.runtime.downloader import AttachmentDownloader


def test_find_elements_sees_iframe_preview_link() -> None:
    snapshot = BrowserSnapshot(
        url="https://example.internal/detail",
        elements=[
            {
                "ref": "@e9",
                "role": "link",
                "text": "合同PDF预览",
                "href": "https://example.internal/files/contract.pdf",
                "iframe_preview": True,
            }
        ],
    )
    matches = attach.find_elements(
        snapshot,
        ["合同"],
        record_key=None,
        record=None,
        match_by=[],
    )
    assert len(matches) == 1
    assert attach.stable_http_url(snapshot, matches[0]) == (
        "https://example.internal/files/contract.pdf"
    )


def test_downloader_session_fetches_iframe_preview_href(tmp_path: Path, template_data) -> None:
    template = BrowserTemplate.model_validate(template_data)
    template.system.allowed_hosts = ["example.internal"]
    template.target.attachments = [
        AttachmentSpec(
            key="contract",
            name="合同",
            semantic=["合同"],
            required=True,
            filename_pattern="{original_name}",
        )
    ]
    snapshot = BrowserSnapshot(
        url="https://example.internal/detail",
        elements=[
            {
                "ref": "@e1",
                "target": "@e1",
                "role": "link",
                "text": "合同PDF",
                "href": "https://example.internal/files/contract.pdf",
                "iframe_preview": True,
            }
        ],
    )
    adapter = FakeBrowserAdapter(
        {"fetch_result": [CommandResult(ok=True, operation="fetch", data={"size": 12})]}
    )
    files = asyncio.run(
        AttachmentDownloader().collect(
            adapter,
            template,
            snapshot,
            [{"order_no": "1"}],
            tmp_path,
        )
    )
    assert files[0].status.value == "ok"
    assert files[0].acquisition_method == "session_fetch"
