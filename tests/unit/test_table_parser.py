from browser_skill.models import BrowserSnapshot
from browser_skill.runtime.table_parser import SnapshotTableParser


def test_parses_accessibility_table_into_template_records(template) -> None:
    snapshot = BrowserSnapshot(
        elements=[
            {"role": "columnheader", "column_index": 0, "text": "样机ID"},
            {"role": "columnheader", "column_index": 1, "text": "序列号"},
            {"role": "columnheader", "column_index": 2, "text": "产品型号"},
            {"role": "cell", "row_index": 1, "column_index": 0, "text": "S1"},
            {"role": "cell", "row_index": 1, "column_index": 1, "text": "SN1"},
            {"role": "cell", "row_index": 1, "column_index": 2, "text": "P1"},
            {"role": "cell", "row_index": 2, "column_index": 0, "text": "S2"},
            {"role": "cell", "row_index": 2, "column_index": 1, "text": "SN2"},
            {"role": "cell", "row_index": 2, "column_index": 2, "text": "P2"},
        ]
    )
    assert SnapshotTableParser().parse(template, snapshot) == [
        {"sample_id": "S1", "sn": "SN1", "product_model": "P1"},
        {"sample_id": "S2", "sn": "SN2", "product_model": "P2"},
    ]


def test_parser_ignores_unknown_columns_and_supports_row_cells(template) -> None:
    snapshot = BrowserSnapshot(
        elements=[
            {"role": "columnheader", "column_index": 0, "text": "SN"},
            {"role": "columnheader", "column_index": 1, "text": "未知列"},
            {"role": "row", "row_index": 1, "cells": ["SN1", "ignored"]},
        ]
    )
    assert SnapshotTableParser().parse(template, snapshot) == [{"sn": "SN1"}]
