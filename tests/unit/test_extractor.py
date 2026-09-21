import asyncio

from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.models import BrowserSnapshot, CommandResult, PaginationSpec, PaginationStrategy
from browser_skill.runtime.extractor import RecordExtractor


def test_next_button_pagination_collects_unique_records(template) -> None:
    template.target.pagination = PaginationSpec(
        strategy=PaginationStrategy.NEXT_BUTTON,
        semantic=["下一页"],
        max_pages=5,
    )
    first = BrowserSnapshot(records=[{"sample_id": "S1", "sn": "SN1"}])
    adapter = FakeBrowserAdapter(
        {
            "find_result": [
                CommandResult(ok=True, operation="find", data={"target": "next"}),
                CommandResult(ok=False, operation="find"),
            ],
            "snapshot": [
                BrowserSnapshot(records=[{"sample_id": "S2", "sn": "SN2"}]),
            ],
        }
    )
    records, complete, _ = asyncio.run(RecordExtractor().collect(adapter, template, first))
    assert [record["sn"] for record in records] == ["SN1", "SN2"]
    assert complete is True


def test_page_number_pagination_uses_bounded_next_action(template) -> None:
    template.target.pagination = PaginationSpec(
        strategy=PaginationStrategy.PAGE_NUMBER,
        max_pages=5,
    )
    adapter = FakeBrowserAdapter(
        {
            "do_action": [
                CommandResult(ok=True, operation="do"),
                CommandResult(ok=False, operation="do"),
            ],
            "snapshot": [
                BrowserSnapshot(
                    url="https://example.internal/page/2",
                    records=[{"sample_id": "S2", "sn": "SN2"}],
                )
            ],
        }
    )

    records, complete, _ = asyncio.run(
        RecordExtractor().collect(
            adapter,
            template,
            BrowserSnapshot(
                url="https://example.internal/page/1",
                records=[{"sample_id": "S1", "sn": "SN1"}],
            ),
        )
    )

    assert [record["sn"] for record in records] == ["SN1", "SN2"]
    assert complete is True
    assert [call for call in adapter.calls if call[0] == "do_action"]


def test_infinite_scroll_requires_configured_idle_rounds_before_complete(template) -> None:
    template.target.pagination = PaginationSpec(
        strategy=PaginationStrategy.INFINITE_SCROLL,
        max_pages=6,
        max_idle_rounds=2,
    )
    page_two = BrowserSnapshot(
        url="https://example.internal/list",
        records=[{"sample_id": "S2", "sn": "SN2"}],
    )
    adapter = FakeBrowserAdapter(
        {
            "snapshot": [page_two, page_two, page_two],
        }
    )

    records, complete, _ = asyncio.run(
        RecordExtractor().collect(
            adapter,
            template,
            BrowserSnapshot(
                url="https://example.internal/list",
                records=[{"sample_id": "S1", "sn": "SN1"}],
            ),
        )
    )

    assert [record["sn"] for record in records] == ["SN1", "SN2"]
    assert complete is True
    scrolls = [call for call in adapter.calls if call[0] == "do_action"]
    assert len(scrolls) == 3


def test_load_more_uses_snapshot_control_and_stops_when_control_disappears(template) -> None:
    template.target.pagination = PaginationSpec(
        strategy=PaginationStrategy.LOAD_MORE,
        semantic=["加载更多"],
        max_pages=4,
    )
    adapter = FakeBrowserAdapter(
        {
            "snapshot": [
                BrowserSnapshot(
                    url="https://example.internal/list",
                    records=[{"sample_id": "S2", "sn": "SN2"}],
                )
            ]
        }
    )
    first = BrowserSnapshot(
        url="https://example.internal/list",
        records=[{"sample_id": "S1", "sn": "SN1"}],
        elements=[{"text": "加载更多", "ref": "@more"}],
    )

    records, complete, _ = asyncio.run(RecordExtractor().collect(adapter, template, first))

    assert [record["sn"] for record in records] == ["SN1", "SN2"]
    assert complete is True
    assert any(call[0] == "click" and call[1][0] == "@more" for call in adapter.calls)


def test_next_page_unchanged_after_click_is_incomplete(template) -> None:
    template.target.pagination = PaginationSpec(
        strategy=PaginationStrategy.NEXT_BUTTON,
        semantic=["下一页"],
        max_pages=3,
    )
    first = BrowserSnapshot(
        url="https://example.internal/list",
        records=[{"sample_id": "S1", "sn": "SN1"}],
        elements=[{"text": "下一页", "ref": "@next"}],
    )
    adapter = FakeBrowserAdapter({"snapshot": [first]})

    _, complete, _ = asyncio.run(RecordExtractor().collect(adapter, template, first))

    assert complete is False


def test_pagination_cycle_and_page_budget_are_incomplete(template) -> None:
    template.target.pagination = PaginationSpec(
        strategy=PaginationStrategy.PAGE_NUMBER,
        max_pages=2,
    )
    first = BrowserSnapshot(
        url="https://example.internal/page/1",
        records=[{"sample_id": "S1", "sn": "SN1"}],
    )
    second = BrowserSnapshot(
        url="https://example.internal/page/2",
        records=[{"sample_id": "S2", "sn": "SN2"}],
    )
    cycle_adapter = FakeBrowserAdapter({"snapshot": [second, first]})

    _, cycle_complete, _ = asyncio.run(RecordExtractor().collect(cycle_adapter, template, first))
    budget_adapter = FakeBrowserAdapter({"snapshot": [second, BrowserSnapshot(records=[])]})
    _, budget_complete, _ = asyncio.run(RecordExtractor().collect(budget_adapter, template, first))

    assert cycle_complete is False
    assert budget_complete is False


def test_pagination_rejects_cross_host_snapshot(template) -> None:
    template.target.pagination = PaginationSpec(
        strategy=PaginationStrategy.PAGE_NUMBER,
        max_pages=2,
    )
    adapter = FakeBrowserAdapter(
        {
            "snapshot": [
                BrowserSnapshot(
                    url="https://evil.example/page/2",
                    records=[{"sample_id": "S2", "sn": "SN2"}],
                )
            ]
        }
    )

    import pytest

    from browser_skill.errors import SkillError

    with pytest.raises(SkillError, match="outside the template host scope"):
        asyncio.run(
            RecordExtractor().collect(
                adapter,
                template,
                BrowserSnapshot(
                    url="https://example.internal/page/1",
                    records=[{"sample_id": "S1", "sn": "SN1"}],
                ),
            )
        )
