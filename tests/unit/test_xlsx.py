import json
import os
import zipfile
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree

import pytest

from browser_skill.models import BrowserTemplate, RunContext, RunState
from browser_skill.outputs.writer import OutputWriter, RunWorkspace
from browser_skill.outputs.xlsx import MAX_XLSX_COLUMNS, MAX_XLSX_ROWS, XlsxWriter
from browser_skill.runtime.validator import ResultValidator


def test_output_writer_creates_valid_xlsx_with_safe_inline_strings(
    tmp_path: Path, template_data
) -> None:
    data = deepcopy(template_data)
    data["output"]["format"] = "xlsx"
    data["output"]["filename_pattern"] = "../inventory_{date}"
    template = BrowserTemplate.model_validate(data)
    workspace = RunWorkspace(tmp_path, "run_xlsx")
    records = [
        {
            "sample_id": '=HYPERLINK("https://evil.example")',
            "sn": "SN<&>1",
            "product_model": "P\x01-1",
        }
    ]
    context = RunContext(
        run_id="run_xlsx",
        template_id=template.template_id,
        template_version=template.version,
        template_snapshot=template,
        variables={"date": "2026-09-20"},
        workspace=workspace.path,
        state=RunState.COMPLETED,
        records=records,
    )
    report = ResultValidator().validate(template, records, [], pagination_complete=True)

    artifacts = OutputWriter().write(context, report)

    relative = artifacts["xlsx"]
    assert relative.endswith(".xlsx")
    assert "/" not in relative and "\\" not in relative
    workbook_path = workspace.path / relative
    with zipfile.ZipFile(workbook_path) as workbook:
        assert workbook.testzip() is None
        names = set(workbook.namelist())
        assert "xl/worksheets/sheet1.xml" in names
        sheet = workbook.read("xl/worksheets/sheet1.xml").decode("utf-8")
        ElementTree.fromstring(sheet)
    assert "<f>" not in sheet
    assert '=HYPERLINK("https://evil.example")' in sheet
    assert "SN&lt;&amp;&gt;1" in sheet
    assert "\x01" not in sheet
    summary = json.loads((workspace.path / "summary.json").read_text(encoding="utf-8"))
    assert summary["artifacts"]["xlsx"] == relative


def test_xlsx_preserves_boolean_and_numeric_cell_types(tmp_path: Path) -> None:
    path = tmp_path / "typed.xlsx"

    XlsxWriter().write(
        path,
        columns=["enabled", "count", "ratio"],
        records=[{"enabled": True, "count": 3, "ratio": 1.5}],
    )

    with zipfile.ZipFile(path) as workbook:
        sheet = workbook.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert '<c r="A2" t="b"><v>1</v></c>' in sheet
    assert '<c r="B2"><v>3</v></c>' in sheet
    assert '<c r="C2"><v>1.5</v></c>' in sheet


def test_xlsx_rejects_empty_or_excessive_columns(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least one column"):
        XlsxWriter().write(tmp_path / "empty.xlsx", columns=[], records=[])
    with pytest.raises(ValueError, match="column limit"):
        XlsxWriter().write(
            tmp_path / "wide.xlsx",
            columns=[f"c{index}" for index in range(MAX_XLSX_COLUMNS + 1)],
            records=[],
        )

    class OversizedRecords(list[dict[str, object]]):
        def __len__(self) -> int:
            return MAX_XLSX_ROWS

    with pytest.raises(ValueError, match="row limit"):
        XlsxWriter().write(
            tmp_path / "tall.xlsx",
            columns=["value"],
            records=OversizedRecords(),
        )


def test_xlsx_atomic_replace_failure_cleans_temporary_archive(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "result.xlsx"

    def fail_replace(_source: str | Path, _target: str | Path) -> None:
        raise OSError("injected XLSX replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected XLSX replace failure"):
        XlsxWriter().write(target, columns=["value"], records=[{"value": "data"}])

    assert not target.exists()
    assert list(tmp_path.glob(".result.xlsx.*")) == []
