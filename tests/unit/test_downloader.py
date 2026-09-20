import asyncio
from pathlib import Path

from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.models import BrowserSnapshot, CommandResult
from browser_skill.runtime.downloader import AttachmentDownloader


class DelayedDownloadAdapter(FakeBrowserAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.pending_path: Path | None = None
        self.polls = 0

    async def download(self, target: str, path: Path) -> CommandResult:
        self.pending_path = path
        return CommandResult(ok=True, operation="download", data={"status": "pending"})

    async def list_downloads(self) -> CommandResult:
        self.polls += 1
        if self.polls == 2 and self.pending_path is not None:
            self.pending_path.write_bytes(b"completed later")
        return CommandResult(ok=True, operation="downloads", data={"status": "pending"})


def test_downloader_polls_until_async_browser_download_is_on_disk(
    tmp_path: Path, template_data
) -> None:
    from browser_skill.models import BrowserTemplate

    template = BrowserTemplate.model_validate(template_data)
    adapter = DelayedDownloadAdapter()
    snapshot = BrowserSnapshot(
        elements=[
            {
                "record_key": "SN1",
                "text": "盘点凭证",
                "ref": "@download",
                "filename": "evidence.pdf",
            }
        ]
    )

    files = asyncio.run(
        AttachmentDownloader(completion_polls=3).collect(
            adapter,
            template,
            snapshot,
            [{"sample_id": "S1", "sn": "SN1"}],
            tmp_path,
        )
    )

    assert adapter.polls == 2
    assert files[0].status == "ok"
    assert files[0].size > 0


def test_downloader_marks_download_failed_after_poll_budget(tmp_path: Path, template_data) -> None:
    from browser_skill.models import BrowserTemplate

    template = BrowserTemplate.model_validate(template_data)
    adapter = DelayedDownloadAdapter()
    snapshot = BrowserSnapshot(
        elements=[
            {
                "record_key": "SN1",
                "text": "盘点凭证",
                "ref": "@download",
                "filename": "evidence.pdf",
            }
        ]
    )

    files = asyncio.run(
        AttachmentDownloader(completion_polls=1).collect(
            adapter,
            template,
            snapshot,
            [{"sample_id": "S1", "sn": "SN1"}],
            tmp_path,
        )
    )

    assert adapter.polls == 1
    assert files[0].status == "failed"
    assert files[0].relative_path == ""
