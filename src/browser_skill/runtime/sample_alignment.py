"""Teach step: compare the user's uploaded sample with what a test run actually produced.

The sample is the user's statement of "what I want"; the test-run records are what the learned
profile delivers. The alignment report tells the Agent (and the console) which sample columns are
covered, which template fields never got values, and where value shapes differ (e.g. the sample
has ``2026-09-01`` but the page yields ``2026/09/01``), so Teach can fix the contract before
publishing.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from browser_skill.models import BrowserTemplate, FieldSpec, StrictModel
from browser_skill.runtime.sample_analyzer import SampleAnalyzer

Shape = Literal["empty", "integer", "number", "date", "datetime", "boolean", "text"]
MatchKind = Literal["key", "name", "semantic", "alias", "normalized"]

_EXAMPLES = 3


class ColumnAlignment(StrictModel):
    column: str
    field_key: str
    matched_by: MatchKind
    sample_shape: Shape
    run_shape: Shape
    shape_match: bool
    sample_examples: list[str] = Field(default_factory=list)
    run_examples: list[str] = Field(default_factory=list)
    run_fill_rate: float = Field(ge=0.0, le=1.0)


class SampleAlignmentReport(StrictModel):
    sample_path: str
    sample_record_count: int = Field(ge=0)
    run_record_count: int = Field(ge=0)
    columns: list[ColumnAlignment] = Field(default_factory=list)
    unmatched_sample_columns: list[str] = Field(default_factory=list)
    fields_without_sample_column: list[str] = Field(default_factory=list)
    fields_without_values: list[str] = Field(default_factory=list)
    coverage: float = Field(ge=0.0, le=1.0)
    issues: list[str] = Field(default_factory=list)

    @property
    def aligned(self) -> bool:
        return (
            not self.unmatched_sample_columns
            and not self.fields_without_values
            and all(item.shape_match for item in self.columns)
        )


def classify_shape(value: Any) -> Shape:
    if value is None:
        return "empty"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    text = str(value).strip()
    if not text:
        return "empty"
    if text.casefold() in {"true", "false", "是", "否", "yes", "no"}:
        return "boolean"
    if re.fullmatch(r"[-+]?\d[\d,]*", text):
        return "integer"
    if re.fullmatch(r"[-+]?(?:\d[\d,]*\.\d*|\.\d+)(?:%|)", text):
        return "number"
    if re.fullmatch(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2})?", text):
        return "datetime"
    if re.fullmatch(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{4}年\d{1,2}月\d{1,2}日", text):
        return "date"
    return "text"


def dominant_shape(values: list[Any]) -> Shape:
    counts: Counter[Shape] = Counter(classify_shape(value) for value in values)
    counts.pop("empty", None)
    if not counts:
        return "empty"
    return counts.most_common(1)[0][0]


def _normalize(text: str) -> str:
    return re.sub(r"[\s_\-()（）:：/·.]+", "", text).casefold()


def match_column(column: str, fields: list[FieldSpec]) -> tuple[FieldSpec, MatchKind] | None:
    folded = column.strip().casefold()
    for field in fields:
        if folded == field.key.casefold():
            return field, "key"
    for field in fields:
        if folded == field.name.strip().casefold():
            return field, "name"
    for field in fields:
        if any(folded == item.strip().casefold() for item in field.semantic):
            return field, "semantic"
    for field in fields:
        if any(folded == item.strip().casefold() for item in field.aliases):
            return field, "alias"
    normalized = _normalize(column)
    if normalized:
        for field in fields:
            candidates = [field.key, field.name, *field.semantic, *field.aliases]
            if any(_normalize(item) == normalized for item in candidates):
                return field, "normalized"
    return None


class SampleAligner:
    """Compare a CSV/JSON sample with run records using the template's field contract."""

    def __init__(self, analyzer: SampleAnalyzer | None = None) -> None:
        self.analyzer = analyzer or SampleAnalyzer()

    def align(
        self,
        template: BrowserTemplate,
        sample_path: Path,
        records: list[dict[str, Any]],
    ) -> SampleAlignmentReport:
        sample_records = self._read(sample_path)
        columns = list(dict.fromkeys(key for record in sample_records for key in record))
        fields = list(template.target.fields)
        aligned: list[ColumnAlignment] = []
        unmatched: list[str] = []
        matched_keys: set[str] = set()
        for column in columns:
            match = match_column(column, fields)
            if match is None:
                unmatched.append(column)
                continue
            field, how = match
            matched_keys.add(field.key)
            sample_values = [record.get(column) for record in sample_records]
            run_values = [record.get(field.key) for record in records]
            present = [value for value in run_values if classify_shape(value) != "empty"]
            sample_shape = dominant_shape(sample_values)
            run_shape = dominant_shape(run_values)
            aligned.append(
                ColumnAlignment(
                    column=column,
                    field_key=field.key,
                    matched_by=how,
                    sample_shape=sample_shape,
                    run_shape=run_shape,
                    shape_match=self._compatible(sample_shape, run_shape),
                    sample_examples=self._examples(sample_values),
                    run_examples=self._examples(run_values),
                    run_fill_rate=(len(present) / len(run_values)) if run_values else 0.0,
                )
            )
        fields_without_column = [f.key for f in fields if f.key not in matched_keys]
        fields_without_values = [
            f.key
            for f in fields
            if records and all(classify_shape(r.get(f.key)) == "empty" for r in records)
        ]
        coverage = (len(aligned) / len(columns)) if columns else 0.0
        report = SampleAlignmentReport(
            sample_path=sample_path.name,
            sample_record_count=len(sample_records),
            run_record_count=len(records),
            columns=aligned,
            unmatched_sample_columns=unmatched,
            fields_without_sample_column=fields_without_column,
            fields_without_values=fields_without_values,
            coverage=coverage,
        )
        report.issues.extend(self._issues(report))
        return report

    def _read(self, path: Path) -> list[dict[str, Any]]:
        inference_reader = {
            ".csv": self.analyzer._read_csv,
            ".json": self.analyzer._read_json,
        }.get(path.suffix.casefold())
        if inference_reader is None:
            return []
        return inference_reader(path)

    @staticmethod
    def _compatible(sample: Shape, run: Shape) -> bool:
        if "empty" in (sample, run):
            return True
        numeric = {"integer", "number"}
        temporal = {"date", "datetime"}
        return sample == run or ({sample, run} <= numeric) or ({sample, run} <= temporal)

    @staticmethod
    def _examples(values: list[Any]) -> list[str]:
        seen: list[str] = []
        for value in values:
            if classify_shape(value) == "empty":
                continue
            text = str(value).strip()
            if text not in seen:
                seen.append(text)
            if len(seen) >= _EXAMPLES:
                break
        return seen

    @staticmethod
    def _issues(report: SampleAlignmentReport) -> list[str]:
        issues: list[str] = []
        if not report.sample_record_count:
            issues.append("样例文件没有记录（仅支持 CSV / JSON）")
        if report.unmatched_sample_columns:
            issues.append("样例列未对应模板字段：" + "、".join(report.unmatched_sample_columns))
        for item in report.columns:
            if not item.shape_match:
                issues.append(
                    f"字段 {item.field_key}：样例为 {item.sample_shape}"
                    f"（如 {item.sample_examples[:1] or ['-']}），"
                    f"试跑得到 {item.run_shape}（如 {item.run_examples[:1] or ['-']}）"
                )
            elif item.run_fill_rate < 0.5 and report.run_record_count:
                issues.append(f"字段 {item.field_key} 试跑填充率仅 {item.run_fill_rate:.0%}")
        if report.fields_without_values and report.run_record_count:
            issues.append("试跑未取到任何值的字段：" + "、".join(report.fields_without_values))
        if not report.run_record_count:
            issues.append("试跑没有取到记录，无法比对取值")
        return issues
