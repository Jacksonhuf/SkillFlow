"""Read a column of driver values from a text / CSV / TSV / XLSX file for batch runs.

Rules match the console's client-side importer so users get the same values either way:

- plain text (``.txt`` or no delimiter): one value per line, ``#`` lines ignored
- delimited (``,`` / tab / ``;``): the first row is a header; pick a column by header name
  or 1-based index (default: first column)
- ``.xlsx``: first sheet, same header rule (requires ``openpyxl``)
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from browser_skill.errors import ErrorCode, SkillError
from browser_skill.models import BrowserTemplate

_DELIMITERS = ("\t", ",", ";")
_MAX_BYTES = 20 * 1024 * 1024


def load_values_file(path: Path, column: str | None = None) -> list[str]:
    """Return the non-empty values of one column, in file order (duplicates kept)."""
    if not path.is_file():
        raise SkillError(ErrorCode.VARIABLE_INVALID, f"值文件不存在：{path}")
    if path.stat().st_size > _MAX_BYTES:
        raise SkillError(ErrorCode.VARIABLE_INVALID, f"值文件过大（>20MB）：{path.name}")
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        rows, tabular = _read_xlsx(path), True
    else:
        rows, tabular = _read_text(path)
    if not tabular:
        if column not in (None, "", "1"):
            raise SkillError(ErrorCode.VARIABLE_INVALID, f"{path.name} 不是表格文件，无需指定列")
        return [row[0] for row in rows if row and row[0]]
    return _pick_column(rows, column, path.name)


def _read_text(path: Path) -> tuple[list[list[str]], bool]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    lines = [line for line in text.splitlines() if line.strip() and not line.startswith("#")]
    if not lines:
        return [], False
    delimiter = next((item for item in _DELIMITERS if item in lines[0]), None)
    if delimiter is None or path.suffix.lower() == ".txt":
        return [[line.strip()] for line in lines], False
    reader = csv.reader(lines, delimiter=delimiter)
    return [[cell.strip() for cell in row] for row in reader], True


def _read_xlsx(path: Path) -> list[list[str]]:
    try:
        import openpyxl  # type: ignore[import-not-found,import-untyped,unused-ignore]
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise SkillError(
            ErrorCode.VARIABLE_INVALID,
            "读取 .xlsx 需要安装 openpyxl（pip install openpyxl），或先另存为 CSV",
        ) from exc
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook.worksheets[0]
        rows: list[list[str]] = []
        for row in sheet.iter_rows(values_only=True):
            cells = ["" if value is None else str(value).strip() for value in row]
            if any(cells):
                rows.append(cells)
        return rows
    finally:
        workbook.close()


def _pick_column(rows: list[list[str]], column: str | None, filename: str) -> list[str]:
    if not rows:
        return []
    header, body = rows[0], rows[1:]
    index = _column_index(header, column, filename)
    # A single-row export has no header row when its only cell already looks like a value.
    if not body and index < len(header) and _looks_like_value(header[index]):
        return [header[index]]
    return [row[index] for row in body if index < len(row) and row[index]]


def _column_index(header: list[str], column: str | None, filename: str) -> int:
    if column in (None, ""):
        return 0
    assert column is not None
    if column.isdigit():
        index = int(column) - 1
        if not 0 <= index < len(header):
            raise SkillError(
                ErrorCode.VARIABLE_INVALID,
                f"{filename} 只有 {len(header)} 列，没有第 {column} 列",
            )
        return index
    wanted = column.strip().casefold()
    for index, name in enumerate(header):
        if name.strip().casefold() == wanted:
            return index
    raise SkillError(
        ErrorCode.VARIABLE_INVALID,
        f"{filename} 没有名为「{column}」的列；可用列：{', '.join(h or '(空)' for h in header)}",
        details={"columns": header},
    )


def _looks_like_value(text: str) -> bool:
    return any(char.isdigit() for char in text) or text.startswith(("http://", "https://"))


def merge_values(existing: Any, values: list[str]) -> list[str]:
    """Combine ``--var`` values with file values, preserving order."""
    if existing is None:
        return list(values)
    head = list(existing) if isinstance(existing, list | tuple) else [existing]
    return [str(item) for item in head] + list(values)


def apply_values_file(
    template: BrowserTemplate,
    variables: dict[str, Any],
    path: Path,
    *,
    column: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    """Fill ``variables[name]`` (default: the batch driver variable) from a values file."""
    target = name or template.run.driver_variable
    if target is None:
        raise SkillError(
            ErrorCode.VARIABLE_INVALID,
            "该模板不是批量模板，请指明要从文件填充的变量名",
        )
    spec = template.variables.get(target)
    if spec is None:
        raise SkillError(ErrorCode.VARIABLE_INVALID, f"模板没有变量 {target}")
    values = load_values_file(path, column)
    if not values:
        raise SkillError(ErrorCode.VARIABLE_MISSING, f"{path.name} 中没有可用的值")
    if not spec.multiple and len(values) > 1:
        raise SkillError(
            ErrorCode.VARIABLE_INVALID,
            f"变量 {target} 只接受一个值，文件里有 {len(values)} 个",
        )
    variables[target] = merge_values(variables.get(target), values)
    return variables
