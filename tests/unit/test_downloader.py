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


def _multi_snapshot() -> BrowserSnapshot:
    return BrowserSnapshot(
        elements=[
            {"record_key": "SN1", "text": "凭证一.pdf", "ref": "@d1"},
            {"record_key": "SN1", "text": "凭证二.pdf", "ref": "@d2"},
            {"record_key": "SN1", "text": "凭证.pdf", "ref": "@d3", "href": "/f/a.pdf"},
            {"record_key": "SN1", "text": "凭证.pdf", "ref": "@d4", "href": "/f/b.pdf"},
        ]
    )


def test_downloader_takes_only_first_match_unless_multiple(tmp_path: Path, template_data) -> None:
    from browser_skill.models import BrowserTemplate

    template = BrowserTemplate.model_validate(template_data)
    adapter = FakeBrowserAdapter()

    files = asyncio.run(
        AttachmentDownloader().collect(
            adapter, template, _multi_snapshot(), [{"sample_id": "S1", "sn": "SN1"}], tmp_path
        )
    )

    assert [item.relative_path for item in files] == ["attachments/evidence/SN1_凭证一.pdf"]


def test_downloader_downloads_every_match_for_multiple_and_dedupes_names(
    tmp_path: Path, template_data
) -> None:
    from browser_skill.models import BrowserTemplate

    template_data["target"]["attachments"][0]["multiple"] = True
    template = BrowserTemplate.model_validate(template_data)
    adapter = FakeBrowserAdapter()

    files = asyncio.run(
        AttachmentDownloader().collect(
            adapter, template, _multi_snapshot(), [{"sample_id": "S1", "sn": "SN1"}], tmp_path
        )
    )

    assert [item.status for item in files] == ["ok"] * 4
    assert [item.relative_path for item in files] == [
        "attachments/evidence/SN1_凭证一.pdf",
        "attachments/evidence/SN1_凭证二.pdf",
        "attachments/evidence/SN1_凭证.pdf",
        "attachments/evidence/SN1_凭证_2.pdf",
    ]
    targets = [call[1][0] for call in adapter.calls if call[0] == "download"]
    assert targets == ["@d1", "@d2", "@d3", "@d4"]


def test_downloader_multiple_honours_max_count(tmp_path: Path, template_data) -> None:
    from browser_skill.models import BrowserTemplate

    template_data["target"]["attachments"][0]["multiple"] = True
    template_data["target"]["attachments"][0]["max_count"] = 2
    template = BrowserTemplate.model_validate(template_data)

    files = asyncio.run(
        AttachmentDownloader().collect(
            FakeBrowserAdapter(),
            template,
            _multi_snapshot(),
            [{"sample_id": "S1", "sn": "SN1"}],
            tmp_path,
        )
    )

    assert len(files) == 2


def test_downloader_copies_repeated_source_url_within_a_run(tmp_path: Path, template_data) -> None:
    from browser_skill.models import BrowserTemplate

    template = BrowserTemplate.model_validate(template_data)
    adapter = FakeBrowserAdapter()
    downloader = AttachmentDownloader()
    snapshot = BrowserSnapshot(
        url="https://example.internal/orders/1",
        elements=[
            {"record_key": "SN1", "text": "凭证", "ref": "@a", "href": "/static/terms.pdf"},
            {"record_key": "SN2", "text": "凭证", "ref": "@b", "href": "/static/terms.pdf"},
            {"record_key": "SN3", "text": "凭证", "ref": "@c", "href": "/static/other.pdf"},
        ],
    )
    records = [
        {"sample_id": "S", "sn": "SN1"},
        {"sample_id": "S", "sn": "SN2"},
        {"sample_id": "S", "sn": "SN3"},
    ]

    files = asyncio.run(downloader.collect(adapter, template, snapshot, records, tmp_path))

    assert [item.status for item in files] == ["ok", "ok", "ok"]
    assert [item.copied_from for item in files] == [
        None,
        "attachments/evidence/SN1_terms.pdf",
        None,
    ]
    assert files[0].sha256 == files[1].sha256
    assert [call[1][0] for call in adapter.calls if call[0] == "download"] == ["@a", "@c"]

    # a different run workspace starts with an empty cache
    other = tmp_path / "other"
    other.mkdir()
    again = asyncio.run(downloader.collect(adapter, template, snapshot, records[:1], other))
    assert again[0].copied_from is None


def test_downloader_ignores_non_document_hrefs_for_dedupe(tmp_path: Path, template_data) -> None:
    from browser_skill.models import BrowserTemplate

    template = BrowserTemplate.model_validate(template_data)
    adapter = FakeBrowserAdapter()
    snapshot = BrowserSnapshot(
        url="https://example.internal/orders/1",
        elements=[
            {"record_key": "SN1", "text": "凭证", "ref": "@a", "href": "javascript:dl(1)"},
            {"record_key": "SN2", "text": "凭证", "ref": "@b", "href": "javascript:dl(1)"},
        ],
    )
    records = [{"sample_id": "S", "sn": "SN1"}, {"sample_id": "S", "sn": "SN2"}]

    files = asyncio.run(
        AttachmentDownloader().collect(adapter, template, snapshot, records, tmp_path)
    )

    assert [item.copied_from for item in files] == [None, None]
    assert len([call for call in adapter.calls if call[0] == "download"]) == 2
