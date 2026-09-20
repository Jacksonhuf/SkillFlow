import asyncio
from copy import deepcopy
from pathlib import Path

import pytest

from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.models import BrowserSnapshot, BrowserTemplate, SourcePage
from browser_skill.runtime.detail import DetailCollector


def detail_template(template_data) -> BrowserTemplate:
    data = deepcopy(template_data)
    data["target"]["fields"][2]["source"] = "detail"
    data["target"]["fields"][2]["required"] = True
    return BrowserTemplate.model_validate(data)


def test_merges_detail_fields_downloads_attachment_and_returns_to_list(
    tmp_path: Path, template_data
) -> None:
    template = detail_template(template_data)
    list_page = BrowserSnapshot(
        url="https://example.internal/list",
        elements=[{"record_key": "SN-1", "text": "查看详情", "ref": "@detail"}],
    )
    detail_page = BrowserSnapshot(
        url="https://example.internal/detail/1",
        text="SN-1",
        records=[{"product_model": "P-100"}],
        elements=[
            {
                "record_key": "SN-1",
                "text": "凭证附件",
                "ref": "@download",
                "filename": "evidence.pdf",
            }
        ],
    )
    adapter = FakeBrowserAdapter(
        {"snapshot": [detail_page, BrowserSnapshot(url="https://example.internal/list")]}
    )
    result = asyncio.run(
        DetailCollector().collect(
            adapter,
            template,
            list_page,
            [{"sample_id": "S1", "sn": "SN-1"}],
            tmp_path,
        )
    )
    assert result.records[0]["product_model"] == "P-100"
    assert result.files[0].record_key == "SN-1"
    assert result.files[0].status == "ok"
    assert (tmp_path / result.files[0].relative_path).exists()
    assert any(call[0] == "do_action" for call in adapter.calls)


def test_extracts_label_value_detail_field(template_data, tmp_path: Path) -> None:
    template = detail_template(template_data)
    assert template.target.fields[2].source == SourcePage.DETAIL
    list_page = BrowserSnapshot(elements=[{"record_key": "SN-1", "text": "详情", "ref": "@detail"}])
    detail_page = BrowserSnapshot(
        text="SN-1",
        elements=[{"label": "产品型号", "value": "P-200"}],
    )
    adapter = FakeBrowserAdapter(
        {"snapshot": [detail_page, BrowserSnapshot(url="https://example.internal/list")]}
    )
    result = asyncio.run(
        DetailCollector().collect(
            adapter,
            template.model_copy(
                update={"target": template.target.model_copy(update={"attachments": []})}
            ),
            list_page,
            [{"sample_id": "S1", "sn": "SN-1"}],
            tmp_path,
        )
    )
    assert result.records[0]["product_model"] == "P-200"


def test_fake_adapter_can_inject_browser_faults() -> None:
    adapter = FakeBrowserAdapter({"snapshot": [TimeoutError("snapshot timeout")]})

    with pytest.raises(TimeoutError, match="snapshot timeout"):
        asyncio.run(adapter.snapshot())
