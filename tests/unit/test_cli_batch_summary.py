from __future__ import annotations

from browser_skill.runtime.batch import batch_summary_extra_lines


def test_batch_summary_lists_failure_groups_and_list_nav_retry() -> None:
    items = {
        "total": 5,
        "ok": 2,
        "partial": 1,
        "failed": 2,
        "failed_values": ["ORD-1", "ORD-2", "ORD-3"],
        "failure_groups": {
            "list_navigation": ["ORD-1", "ORD-2"],
            "pick_field_empty": ["ORD-3"],
        },
        "list_navigation_failure_values": ["ORD-1", "ORD-2"],
        "pick_field_empty_values": ["ORD-3"],
    }
    lines = batch_summary_extra_lines(items)
    assert any("列表搜索/进详情" in line for line in lines)
    assert any("点选字段为空" in line for line in lines)
    assert any("ORD-1" in line and "列表进详情" in line for line in lines)
    assert any("ORD-3" in line and "点选空列" in line for line in lines)
