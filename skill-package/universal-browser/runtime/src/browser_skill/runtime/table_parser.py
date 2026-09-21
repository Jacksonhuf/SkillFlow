from __future__ import annotations

from collections import defaultdict
from typing import Any

from browser_skill.models import BrowserSnapshot, BrowserTemplate, SourcePage


class SnapshotTableParser:
    """Convert normalized accessibility-table elements into template-keyed list records."""

    def parse(self, template: BrowserTemplate, snapshot: BrowserSnapshot) -> list[dict[str, Any]]:
        list_fields = [field for field in template.target.fields if field.source == SourcePage.LIST]
        headers: dict[int, str] = {}
        rows: defaultdict[int, dict[int, Any]] = defaultdict(dict)
        for element in snapshot.elements:
            role = str(element.get("role", "")).casefold()
            if role in {"columnheader", "header"}:
                column = self._index(element, "column_index")
                if column is not None:
                    headers[column] = self._value(element)
            elif role in {"cell", "gridcell"}:
                row = self._index(element, "row_index")
                column = self._index(element, "column_index")
                if row is not None and column is not None:
                    rows[row][column] = element.get("value", self._value(element))
            elif role == "row" and isinstance(element.get("cells"), list):
                row = self._index(element, "row_index")
                if row is None:
                    row = len(rows) + 1
                for column, value in enumerate(element["cells"]):
                    rows[row][column] = value
        field_by_column: dict[int, str] = {}
        for column, header in headers.items():
            folded = header.casefold()
            candidates = [
                field
                for field in list_fields
                if any(alias.casefold() == folded for alias in [field.name, *field.semantic])
            ]
            if not candidates:
                candidates = [
                    field
                    for field in list_fields
                    if any(alias.casefold() in folded for alias in [field.name, *field.semantic])
                ]
            if len(candidates) == 1:
                field_by_column[column] = candidates[0].key
        return [
            {
                field_by_column[column]: value
                for column, value in sorted(cells.items())
                if column in field_by_column
            }
            for _, cells in sorted(rows.items())
            if any(column in field_by_column for column in cells)
        ]

    @staticmethod
    def _index(element: dict[str, Any], name: str) -> int | None:
        value = element.get(name)
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _value(element: dict[str, Any]) -> str:
        return str(
            element.get("text")
            or element.get("name")
            or element.get("label")
            or element.get("aria_label")
            or ""
        ).strip()
