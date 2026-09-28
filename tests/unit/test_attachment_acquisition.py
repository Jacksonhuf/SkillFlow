import asyncio
from pathlib import Path

from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.models import (
    AttachmentSpec,
    BrowserSnapshot,
    BrowserTemplate,
    CommandResult,
    LearnedMapping,
    LearnedSpec,
    NetworkExchange,
    SourcePage,
)
from browser_skill.runtime.downloader import AttachmentDownloader


def test_session_fetch_used_before_click(tmp_path: Path, template_data) -> None:
    data = dict(template_data)
    data["learned"] = LearnedSpec().model_dump()
    template = BrowserTemplate.model_validate(data)
    adapter = FakeBrowserAdapter(
        {
            "fetch_result": [CommandResult(ok=True, operation="fetch", data={"size": 12})],
            "download_result": [CommandResult(ok=False, operation="download")],
        }
    )
    snapshot = BrowserSnapshot(
        url="https://example.internal/doc/1",
        elements=[
            {
                "ref": "@e1",
                "text": "盘点凭证",
                "href": "https://example.internal/files/evidence.pdf",
                "filename": "evidence.pdf",
            }
        ],
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
    assert files[0].status == "ok"
    assert any(call[0] == "fetch_resource" for call in adapter.calls)
    assert not any(call[0] == "download" for call in adapter.calls)


def test_network_binary_body_is_saved(tmp_path: Path, template_data) -> None:
    import base64

    template = BrowserTemplate.model_validate(template_data)
    adapter = FakeBrowserAdapter()
    payload = base64.b64encode(b"%PDF-1.4 test").decode("ascii")
    data = dict(template_data)
    att = data["target"]["attachments"][0]
    att["file_types"] = []
    template = BrowserTemplate.model_validate(data)
    exchanges = [
        NetworkExchange(
            url="https://example.internal/api/file/invoice",
            content_type="application/pdf",
            body_base64=payload,
            size=len(payload),
        )
    ]
    snapshot = BrowserSnapshot(url="https://example.internal/home", elements=[])
    files = asyncio.run(
        AttachmentDownloader(completion_polls=1).collect(
            adapter,
            template,
            snapshot,
            [{"sample_id": "S1", "sn": "SN1"}],
            tmp_path,
            exchanges=exchanges,
        )
    )
    assert files[0].status == "ok"
    assert files[0].size > 0


def test_learned_network_json_url_is_fetched(tmp_path: Path, template_data) -> None:
    data = dict(template_data)
    data["learned"] = LearnedSpec(
        attachment_mappings={
            "inventory_evidence": LearnedMapping(
                page=SourcePage.LIST,
                strategy="semantic",
                hints=["凭证"],
                endpoint_hint="/api/docs",
                json_path="$.data.fileUrl",
            )
        }
    ).model_dump()
    template = BrowserTemplate.model_validate(data)
    adapter = FakeBrowserAdapter(
        {"fetch_result": [CommandResult(ok=True, operation="fetch", data={"size": 4})]}
    )
    exchanges = [
        NetworkExchange(
            url="https://example.internal/api/docs?id=1",
            body={"data": {"fileUrl": "https://example.internal/static/evidence.pdf"}},
        )
    ]
    snapshot = BrowserSnapshot(url="https://example.internal/home", elements=[])
    spec = template.target.attachments[0]
    template.target.attachments = [
        AttachmentSpec.model_validate(
            {**spec.model_dump(), "semantic": ["凭证"], "file_types": []}
        )
    ]
    files = asyncio.run(
        AttachmentDownloader(completion_polls=1).collect(
            adapter,
            template,
            snapshot,
            [{"sample_id": "S1", "sn": "SN1"}],
            tmp_path,
            exchanges=exchanges,
        )
    )
    assert files[0].status == "ok"
    assert any(call[0] == "fetch_resource" for call in adapter.calls)
