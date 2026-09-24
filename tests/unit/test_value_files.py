from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from browser_skill.app import parse_variables
from browser_skill.errors import ErrorCode, SkillError
from browser_skill.interaction.value_files import apply_values_file, load_values_file
from browser_skill.models import BrowserTemplate


def test_parse_variables_aggregates_repeated_names() -> None:
    assert parse_variables(["a=1", "order_no=ORD-1", "order_no=ORD-2", "order_no=ORD-3"]) == {
        "a": "1",
        "order_no": ["ORD-1", "ORD-2", "ORD-3"],
    }


def test_plain_text_one_value_per_line_ignores_comments(tmp_path: Path) -> None:
    path = tmp_path / "ids.txt"
    path.write_text("# 本周订单\nORD-1\n\n  ORD-2  \nORD-3\n", encoding="utf-8")

    assert load_values_file(path) == ["ORD-1", "ORD-2", "ORD-3"]


def test_plain_text_rejects_column_selection(tmp_path: Path) -> None:
    path = tmp_path / "ids.txt"
    path.write_text("ORD-1\n", encoding="utf-8")

    with pytest.raises(SkillError):
        load_values_file(path, "order_no")


def test_csv_picks_column_by_header_name_case_insensitive(tmp_path: Path) -> None:
    path = tmp_path / "orders.csv"
    path.write_text(
        "\ufeffOrder_No,客户,金额\nORD-1,张三,100\nORD-2,李四,\n,王五,30\nORD-3,,5\n",
        encoding="utf-8",
    )

    assert load_values_file(path, "order_no") == ["ORD-1", "ORD-2", "ORD-3"]
    assert load_values_file(path, "客户") == ["张三", "李四", "王五"]


def test_csv_defaults_to_first_column_and_accepts_index(tmp_path: Path) -> None:
    path = tmp_path / "orders.tsv"
    path.write_text("order_no\tcustomer\nORD-1\t张三\nORD-2\t李四\n", encoding="utf-8")

    assert load_values_file(path) == ["ORD-1", "ORD-2"]
    assert load_values_file(path, "2") == ["张三", "李四"]


def test_csv_unknown_column_lists_available_headers(tmp_path: Path) -> None:
    path = tmp_path / "orders.csv"
    path.write_text("order_no;customer\nORD-1;张三\n", encoding="utf-8")

    with pytest.raises(SkillError) as info:
        load_values_file(path, "nope")
    assert info.value.code == ErrorCode.VARIABLE_INVALID
    assert info.value.details["columns"] == ["order_no", "customer"]

    with pytest.raises(SkillError):
        load_values_file(path, "3")


def test_csv_quoted_cells_and_single_row_without_header(tmp_path: Path) -> None:
    quoted = tmp_path / "quoted.csv"
    quoted.write_text('id,name\n"ORD-1","张, 三"\n"ORD-2","李四"\n', encoding="utf-8")
    assert load_values_file(quoted, "name") == ["张, 三", "李四"]

    single = tmp_path / "single.csv"
    single.write_text("ORD-9,张三\n", encoding="utf-8")
    assert load_values_file(single) == ["ORD-9"]


def test_missing_file_raises_variable_invalid(tmp_path: Path) -> None:
    with pytest.raises(SkillError) as info:
        load_values_file(tmp_path / "nope.csv")
    assert info.value.code == ErrorCode.VARIABLE_INVALID


def _batch_template(template_data: dict[str, Any]) -> BrowserTemplate:
    data = deepcopy(template_data)
    data["schema_version"] = "2.0"
    data["system"]["url_template"] = "https://example.internal/orders/{order_no}"
    data["variables"] = {
        "order_no": {"type": "string", "required": True, "multiple": True, "prompt": "订单号"},
        "region": {"type": "string", "required": False, "prompt": "区域"},
    }
    data["run"] = {"mode": "detail_batch", "driver_variable": "order_no"}
    data["target"]["record_key"] = ["order_no"]
    data["target"]["fields"] = [
        {"key": "order_no", "name": "订单号", "required": True, "semantic": ["订单号"]}
    ]
    data["target"]["attachments"] = []
    data["workflow"]["hints"] = []
    data["output"]["columns"] = ["order_no"]
    return BrowserTemplate.model_validate(data)


def test_apply_values_file_fills_driver_and_merges_with_var(
    tmp_path: Path, template_data: dict[str, Any]
) -> None:
    template = _batch_template(template_data)
    path = tmp_path / "ids.txt"
    path.write_text("ORD-2\nORD-3\n", encoding="utf-8")

    variables = apply_values_file(template, {"order_no": "ORD-1"}, path)

    assert variables == {"order_no": ["ORD-1", "ORD-2", "ORD-3"]}


def test_apply_values_file_guards_variable_shape(
    tmp_path: Path, template_data: dict[str, Any]
) -> None:
    template = _batch_template(template_data)
    path = tmp_path / "ids.txt"
    path.write_text("ORD-2\nORD-3\n", encoding="utf-8")

    with pytest.raises(SkillError, match="只接受一个值"):
        apply_values_file(template, {}, path, name="region")
    with pytest.raises(SkillError, match="没有变量"):
        apply_values_file(template, {}, path, name="unknown")

    empty = tmp_path / "empty.txt"
    empty.write_text("# nothing\n", encoding="utf-8")
    with pytest.raises(SkillError) as info:
        apply_values_file(template, {}, empty)
    assert info.value.code == ErrorCode.VARIABLE_MISSING

    list_template = BrowserTemplate.model_validate(template_data)
    with pytest.raises(SkillError, match="不是批量模板"):
        apply_values_file(list_template, {}, path)
