from pathlib import Path

import pytest

from browser_skill.errors import SkillError
from browser_skill.outputs.paths import attachment_basename, contained_path, safe_filename


def test_safe_filename_removes_traversal_and_reserved_characters() -> None:
    name = safe_filename("../../contract:01?.pdf")
    assert "/" not in name
    assert "\\" not in name
    assert ":" not in name
    assert "?" not in name
    assert name.endswith(".pdf")


def test_safe_filename_strips_hash_and_shortens_spa_url() -> None:
    raw = "https://efinance.huawei.com/saasone/#/sse-legacy-portal?x=1"
    name = safe_filename(raw, fallback="invoice.pdf", max_length=64)
    assert "#" not in name
    assert len(name) <= 64
    assert name != raw


def test_attachment_basename_rejects_page_url() -> None:
    url = "https://efinance.huawei.com/saasone/#/detail"
    assert attachment_basename(url, fallback="ORD-1_invoice.pdf") == "ORD-1_invoice.pdf"


def test_is_fetchable_rejects_huawei_hash_route() -> None:
    from browser_skill.acquire.attachments import is_fetchable_attachment_url

    page = "https://efinance.huawei.com/saasone/#/sse-legacy-portal?x=1"
    assert is_fetchable_attachment_url(page, page_url=page) is False
    assert (
        is_fetchable_attachment_url(
            "https://efinance.huawei.com/static/evidence.pdf", page_url=page
        )
        is True
    )


def test_contained_path_rejects_escape(tmp_path: Path) -> None:
    with pytest.raises(SkillError):
        contained_path(tmp_path, "..", "escape")
