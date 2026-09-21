import asyncio
from pathlib import Path

from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.models import BrowserSnapshot, BrowserTemplate, CommandResult
from browser_skill.runtime.downloader import AttachmentDownloader


def test_downloader_falls_back_to_find_when_element_missing(
    tmp_path: Path, template_data
) -> None:
    template = BrowserTemplate.model_validate(template_data)
    adapter = FakeBrowserAdapter(
        {
            "find_result": [
                CommandResult(ok=True, operation="find", data={"target": "@download-from-find"}),
            ],
            "download_result": [CommandResult(ok=True, operation="download", data={"ok": True})],
            "list_downloads": [CommandResult(ok=True, operation="downloads", data={})],
        }
    )
    snapshot = BrowserSnapshot(elements=[])

    files = asyncio.run(
        AttachmentDownloader(completion_polls=1).collect(
            adapter,
            template,
            snapshot,
            [{"sample_id": "S1", "sn": "SN1"}],
            tmp_path,
        )
    )
    assert any(call[0] == "find" for call in adapter.calls)
    assert files[0].status != "missing"
    assert any(call[0] == "download" for call in adapter.calls)
