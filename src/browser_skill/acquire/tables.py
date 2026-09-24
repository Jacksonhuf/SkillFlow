"""Tables on a detail page: which one holds the record rows, and which column is which field.

A detail page usually carries two kinds of tables: a two-column *key/value* table (basic info,
already read as label/value pairs) and one or more *grids* with a header row and N data rows
(line items, payments, logs). Only grids can become records. The probe offers every grid; the
template remembers the chosen one by its header texts so the same table is found again even when
its position on the page shifts.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from browser_skill.models import BrowserSnapshot, LearnedTable, TableData

_MIN_GRID_ROWS = 1
_MIN_GRID_COLUMNS = 2
_KV_LABEL_MAX = 24
_HEADER_MATCH_THRESHOLD = 0.5


def tables_from_snapshot(snapshot: BrowserSnapshot) -> list[TableData]:
    """``snapshot.tables`` when the adapter provides it, else derived from records/elements."""
    if snapshot.tables:
        return list(snapshot.tables)
    if snapshot.records:
        headers = list(dict.fromkeys(key for record in snapshot.records for key in record))
        rows = [[_cell(record.get(key)) for key in headers] for record in snapshot.records]
        return [TableData(index=0, headers=headers, rows=rows)]
    return _tables_from_elements(snapshot)


def _tables_from_elements(snapshot: BrowserSnapshot) -> list[TableData]:
    headers: dict[int, dict[int, str]] = {}
    rows: dict[int, dict[int, dict[int, str]]] = {}
    for element in snapshot.elements:
        role = str(element.get("role", "")).casefold()
        table = _int(element.get("table_index")) or 0
        column = _int(element.get("column_index"))
        if column is None:
            continue
        text = str(element.get("value", element.get("text", "")) or "").strip()
        if role in {"columnheader", "header"}:
            headers.setdefault(table, {})[column] = text
        elif role in {"cell", "gridcell"}:
            row = _int(element.get("row_index"))
            if row is not None:
                rows.setdefault(table, {}).setdefault(row, {})[column] = text
    out: list[TableData] = []
    for table in sorted(set(headers) | set(rows)):
        header_cells = headers.get(table, {})
        data = rows.get(table, {})
        width = max([*header_cells.keys(), *(c for r in data.values() for c in r)], default=-1) + 1
        out.append(
            TableData(
                index=len(out),
                headers=[header_cells.get(c, "") for c in range(width)] if header_cells else [],
                rows=[[data[r].get(c, "") for c in range(width)] for r in sorted(data)],
            )
        )
    return out


def is_grid(table: TableData) -> bool:
    """A grid has a header row and at least one data row; key/value tables are not grids."""
    if len(table.rows) < _MIN_GRID_ROWS:
        return False
    width = max(len(table.headers), *(len(row) for row in table.rows))
    if width < _MIN_GRID_COLUMNS:
        return False
    if table.headers and any(header.strip() for header in table.headers):
        return True
    # Header-less two-column table whose left column reads like labels: key/value, not rows
    if width == 2 and all(
        len(row) >= 1 and _looks_like_label(row[0]) for row in table.rows[: _KV_LABEL_MAX]
    ):
        return False
    return len(table.rows) >= 2


def column_names(table: TableData) -> list[str]:
    """Header texts, filling blanks with ``列N`` so every column can be referenced."""
    width = max(len(table.headers), *(len(row) for row in table.rows)) if table.rows else 0
    names: list[str] = []
    for index in range(width):
        header = table.headers[index].strip() if index < len(table.headers) else ""
        names.append(header or f"列{index + 1}")
    return names


def select_table(tables: Sequence[TableData], learned: LearnedTable) -> TableData | None:
    """Find the table the template was taught on: by header overlap first, position second."""
    wanted = [_fold(item) for item in learned.headers if item.strip()]
    best: tuple[float, TableData] | None = None
    if wanted:
        for table in tables:
            have = {_fold(item) for item in column_names(table)}
            score = sum(1 for item in wanted if item in have) / len(wanted)
            if score >= _HEADER_MATCH_THRESHOLD and (best is None or score > best[0]):
                best = (score, table)
        if best is not None:
            return best[1]
    if 0 <= learned.index < len(tables) and is_grid(tables[learned.index]):
        return tables[learned.index]
    return None


def column_index(table: TableData, hints: Sequence[str], fallback: int | None) -> int | None:
    """Column whose header equals (preferred) or contains one of ``hints``; else ``fallback``."""
    names = [_fold(item) for item in column_names(table)]
    wanted = [_fold(item) for item in hints if item.strip()]
    for hint in wanted:
        if hint in names:
            return names.index(hint)
    for hint in wanted:
        for index, name in enumerate(names):
            if hint and (hint in name or name in hint) and name:
                return index
    if fallback is not None and 0 <= fallback < len(names):
        return fallback
    return None


def _looks_like_label(text: str) -> bool:
    stripped = text.strip().rstrip(":：")
    return 0 < len(stripped) <= _KV_LABEL_MAX and not re.search(r"\d{3,}", stripped)


def _fold(text: str) -> str:
    return re.sub(r"\s+", "", text).rstrip(":：").casefold()


def _cell(value: object) -> str:
    return "" if value is None else str(value)


def _int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None
