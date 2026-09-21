import asyncio

import pytest

from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.errors import SkillError
from browser_skill.models import BrowserSnapshot, CommandResult
from browser_skill.runtime.locator import LocatorService


def test_prefers_learned_hint_in_current_snapshot_without_find() -> None:
    adapter = FakeBrowserAdapter()
    snapshot = BrowserSnapshot(
        elements=[
            {"role": "button", "name": "执行盘点查询", "ref": "@learned"},
            {"role": "button", "name": "查询", "ref": "@semantic"},
        ]
    )

    located = asyncio.run(
        LocatorService().locate(
            adapter,
            snapshot,
            ["查询"],
            learned_hints=["执行盘点查询"],
        )
    )

    assert located.target == "@learned"
    assert located.strategy == "learned"
    assert not any(call[0] == "find" for call in adapter.calls)


def test_uses_snapshot_exact_then_semantic_find_fallback() -> None:
    exact = asyncio.run(
        LocatorService().locate(
            FakeBrowserAdapter(),
            BrowserSnapshot(elements=[{"aria_label": "查询", "ref": "@query"}]),
            ["查询"],
        )
    )
    adapter = FakeBrowserAdapter(
        {"find_result": [CommandResult(ok=True, operation="find", data={"target": "live"})]}
    )
    fallback = asyncio.run(LocatorService().locate(adapter, BrowserSnapshot(), ["查询"]))

    assert exact.strategy == "snapshot_exact"
    assert exact.target == "@query"
    assert fallback.strategy == "semantic_find"
    assert fallback.target == "live"


def test_rejects_ambiguous_snapshot_candidates_instead_of_clicking() -> None:
    snapshot = BrowserSnapshot(
        elements=[
            {"name": "查询", "ref": "@one"},
            {"name": "查询", "ref": "@two"},
        ]
    )

    with pytest.raises(SkillError, match="Multiple page elements") as raised:
        asyncio.run(LocatorService().locate(FakeBrowserAdapter(), snapshot, ["查询"]))

    assert raised.value.repairable is True
    assert raised.value.details["candidate_count"] == 2


def test_record_scope_excludes_other_detail_rows() -> None:
    snapshot = BrowserSnapshot(
        elements=[
            {"record_key": "SN1", "text": "详情", "ref": "@one"},
            {"record_key": "SN2", "text": "详情", "ref": "@two"},
        ]
    )

    located = asyncio.run(
        LocatorService().locate(FakeBrowserAdapter(), snapshot, ["详情"], record_key="SN2")
    )

    assert located.target == "@two"


def test_missing_required_target_returns_repairable_domain_error() -> None:
    with pytest.raises(SkillError) as raised:
        asyncio.run(LocatorService().locate(FakeBrowserAdapter(), BrowserSnapshot(), ["不存在"]))

    assert raised.value.code.value == "E_ELEMENT_NOT_FOUND"
    assert raised.value.repairable is True


def test_validated_dom_hint_is_last_fallback_after_semantic_find() -> None:
    adapter = FakeBrowserAdapter({"find_result": [CommandResult(ok=False, operation="find")]})

    located = asyncio.run(
        LocatorService().locate(
            adapter,
            BrowserSnapshot(),
            ["查询"],
            dom_hints=['css=button[data-action="search"]'],
        )
    )

    assert located.strategy == "dom_hint"
    assert located.target == 'css=button[data-action="search"]'
    assert any(call[0] == "find" for call in adapter.calls)
