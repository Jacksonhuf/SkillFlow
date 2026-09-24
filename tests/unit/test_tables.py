from __future__ import annotations

from browser_skill.acquire.tables import (
    column_index,
    column_names,
    is_grid,
    select_table,
    tables_from_snapshot,
)
from browser_skill.models import BrowserSnapshot, LearnedTable, TableData

KV = TableData(index=0, headers=[], rows=[["订单号", "ORD-1"], ["客户", "张三"]])
LINES = TableData(
    index=1,
    title="商品明细",
    headers=["序号", "物料编码", "物料名称", "数量"],
    rows=[["1", "M-001", "螺栓", "200"], ["2", "M-002", "垫片", "50"]],
)


def test_key_value_table_is_not_a_grid_but_line_items_are() -> None:
    assert is_grid(KV) is False
    assert is_grid(LINES) is True
    # header-less table with several wide rows is still a grid (headers become 列N)
    wide = TableData(index=2, rows=[["a", "b", "c"], ["d", "e", "f"]])
    assert is_grid(wide) is True
    assert column_names(wide) == ["列1", "列2", "列3"]
    assert is_grid(TableData(index=3, headers=["only"], rows=[["x"]])) is False


def test_tables_from_snapshot_prefers_tables_then_records_then_elements() -> None:
    assert tables_from_snapshot(BrowserSnapshot(tables=[LINES])) == [LINES]

    from_records = tables_from_snapshot(
        BrowserSnapshot(records=[{"sku": "M-001", "qty": 1}, {"sku": "M-002", "qty": 2}])
    )
    assert from_records[0].headers == ["sku", "qty"]
    assert from_records[0].rows == [["M-001", "1"], ["M-002", "2"]]

    elements = [
        {"role": "columnheader", "column_index": 0, "text": "物料编码", "table_index": 0},
        {"role": "columnheader", "column_index": 1, "text": "数量", "table_index": 0},
        {"role": "cell", "row_index": 1, "column_index": 0, "text": "M-1", "table_index": 0},
        {"role": "cell", "row_index": 1, "column_index": 1, "text": "3", "table_index": 0},
        {"role": "cell", "row_index": 2, "column_index": 0, "text": "M-2"},
        {"role": "cell", "row_index": 2, "column_index": 1, "text": "4"},
    ]
    from_elements = tables_from_snapshot(BrowserSnapshot(elements=elements))
    assert from_elements[0].headers == ["物料编码", "数量"]
    assert from_elements[0].rows == [["M-1", "3"], ["M-2", "4"]]


def test_select_table_by_headers_survives_position_change() -> None:
    learned = LearnedTable(index=0, headers=["序号", "物料编码", "物料名称", "数量"])
    moved = LINES.model_copy(
        update={"index": 3, "headers": ["序号", "物料编码", "物料名称 ", "数量"]}
    )
    other = TableData(index=0, headers=["付款日期", "金额"], rows=[["2024-01-01", "1"]])

    assert select_table([other, moved], learned) is moved
    # no header overlap: fall back to the taught position when it is a grid
    assert select_table([LINES, other], LearnedTable(index=1, headers=["完全不同"])) is other
    assert select_table([KV], LearnedTable(index=0, headers=["完全不同"])) is None


def test_column_index_matches_exact_then_partial_then_fallback() -> None:
    assert column_index(LINES, ["物料编码"], None) == 1
    assert column_index(LINES, ["名称"], None) == 2  # partial: 物料名称
    assert column_index(LINES, ["不存在"], 3) == 3
    assert column_index(LINES, ["不存在"], 9) is None
