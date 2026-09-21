from __future__ import annotations

import math
import os
import tempfile
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

MAX_XLSX_ROWS = 1_048_576
MAX_XLSX_COLUMNS = 16_384


class XlsxWriter:
    """Write a minimal standards-compliant XLSX workbook with inline, non-formula strings."""

    def write(
        self,
        path: Path,
        *,
        columns: list[str],
        records: list[dict[str, Any]],
    ) -> Path:
        if not columns:
            raise ValueError("XLSX output requires at least one column")
        if len(columns) > MAX_XLSX_COLUMNS:
            raise ValueError("XLSX column limit exceeded")
        if len(records) + 1 > MAX_XLSX_ROWS:
            raise ValueError("XLSX row limit exceeded")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        os.close(fd)
        temporary_path = Path(temporary)
        try:
            with zipfile.ZipFile(
                temporary_path,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=6,
            ) as workbook:
                workbook.writestr("[Content_Types].xml", self._content_types())
                workbook.writestr("_rels/.rels", self._root_relationships())
                workbook.writestr("xl/workbook.xml", self._workbook())
                workbook.writestr("xl/_rels/workbook.xml.rels", self._workbook_relationships())
                workbook.writestr("xl/worksheets/sheet1.xml", self._sheet(columns, records))
            with temporary_path.open("rb") as handle:
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
            return path
        finally:
            temporary_path.unlink(missing_ok=True)

    def _sheet(self, columns: list[str], records: list[dict[str, Any]]) -> str:
        rows = [self._row(1, columns)]
        rows.extend(
            self._row(index, [record.get(column) for column in columns])
            for index, record in enumerate(records, start=2)
        )
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<dimension ref="A1:{self._column_name(len(columns))}{len(records) + 1}"/>'
            f"<sheetData>{''.join(rows)}</sheetData>"
            "</worksheet>"
        )

    def _row(self, number: int, values: list[Any]) -> str:
        cells = "".join(
            self._cell(f"{self._column_name(index)}{number}", value)
            for index, value in enumerate(values, start=1)
        )
        return f'<row r="{number}">{cells}</row>'

    def _cell(self, reference: str, value: Any) -> str:
        if isinstance(value, bool):
            return f'<c r="{reference}" t="b"><v>{1 if value else 0}</v></c>'
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and (not isinstance(value, float) or math.isfinite(value))
        ):
            return f'<c r="{reference}"><v>{value}</v></c>'
        if value is None:
            text = ""
        elif isinstance(value, (date, datetime)):
            text = value.isoformat()
        else:
            text = str(value)
        # Inline strings are deliberate: values beginning with =,+,-,@ remain data, never formulas.
        safe = escape(self._xml_text(text))
        return f'<c r="{reference}" t="inlineStr"><is><t xml:space="preserve">{safe}</t></is></c>'

    @staticmethod
    def _xml_text(value: str) -> str:
        return "".join(
            character for character in value if character in "\t\n\r" or ord(character) >= 0x20
        )

    @staticmethod
    def _column_name(index: int) -> str:
        if index < 1 or index > MAX_XLSX_COLUMNS:
            raise ValueError("Invalid XLSX column index")
        name = ""
        while index:
            index, remainder = divmod(index - 1, 26)
            name = chr(65 + remainder) + name
        return name

    @staticmethod
    def _content_types() -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            "</Types>"
        )

    @staticmethod
    def _root_relationships() -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/officeDocument" '
            'Target="xl/workbook.xml"/>'
            "</Relationships>"
        )

    @staticmethod
    def _workbook() -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Results" sheetId="1" r:id="rId1"/></sheets>'
            "</workbook>"
        )

    @staticmethod
    def _workbook_relationships() -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet1.xml"/>'
            "</Relationships>"
        )
