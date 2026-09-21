from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from browser_skill.errors import ErrorCode, SkillError
from browser_skill.models import FieldSpec, FieldType, SampleInference, SourcePage


class SampleAnalyzer:
    """Infer an editable target contract from a small, platform-provided CSV or JSON sample."""

    ATTACHMENT_WORDS = ("附件", "文件", "凭证", "合同", "attachment", "file", "document")
    VARIABLE_WORDS = ("日期", "时间", "区域", "地区", "单号", "date", "region", "period")
    KEY_WORDS = ("id", "编号", "单号", "sn", "序列号", "code", "编码")

    def __init__(self, *, max_bytes: int = 2 * 1024 * 1024, max_records: int = 1000) -> None:
        self.max_bytes = max_bytes
        self.max_records = max_records

    def analyze(self, path: Path) -> SampleInference:
        if not path.is_file() or path.is_symlink():
            raise SkillError(ErrorCode.TEMPLATE_INVALID, "Sample must be a regular file")
        if path.stat().st_size > self.max_bytes:
            raise SkillError(ErrorCode.TEMPLATE_INVALID, "Sample exceeds the allowed size")
        suffix = path.suffix.casefold()
        if suffix == ".csv":
            records = self._read_csv(path)
        elif suffix == ".json":
            records = self._read_json(path)
        else:
            raise SkillError(ErrorCode.TEMPLATE_INVALID, "Only CSV and JSON samples are supported")
        if not records:
            raise SkillError(ErrorCode.TEMPLATE_INVALID, "Sample does not contain records")
        headers = list(dict.fromkeys(key for record in records for key in record))
        fields: list[FieldSpec] = []
        attachments: list[str] = []
        variables: list[str] = []
        keys: list[str] = []
        used_keys: set[str] = set()
        for index, header in enumerate(headers, 1):
            machine_key = self._machine_key(header, index, used_keys)
            used_keys.add(machine_key)
            values = [record.get(header) for record in records]
            inferred_type = self._infer_type(values)
            required = all(self._is_present(value) for value in values)
            fields.append(
                FieldSpec(
                    key=machine_key,
                    name=header,
                    type=inferred_type,
                    required=required,
                    semantic=[header],
                    source=SourcePage.LIST,
                )
            )
            folded = header.casefold()
            if any(word in folded for word in self.ATTACHMENT_WORDS):
                attachments.append(machine_key)
            if any(word in folded for word in self.VARIABLE_WORDS):
                variables.append(machine_key)
            if any(word in folded for word in self.KEY_WORDS) and self._is_unique(values):
                keys.append(machine_key)
        return SampleInference(
            fields=fields,
            attachment_columns=attachments,
            variable_candidates=variables,
            record_key_candidates=keys,
            sample_record_count=len(records),
        )

    def _read_csv(self, path: Path) -> list[dict[str, Any]]:
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                if not reader.fieldnames or any(not name.strip() for name in reader.fieldnames):
                    raise SkillError(ErrorCode.TEMPLATE_INVALID, "CSV requires non-empty headers")
                return [dict(row) for _, row in zip(range(self.max_records), reader, strict=False)]
        except UnicodeDecodeError as exc:
            raise SkillError(ErrorCode.TEMPLATE_INVALID, "Sample must use UTF-8 encoding") from exc

    def _read_json(self, path: Path) -> list[dict[str, Any]]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SkillError(ErrorCode.TEMPLATE_INVALID, "Sample JSON is invalid") from exc
        if isinstance(payload, dict):
            payload = payload.get("records", [payload])
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise SkillError(ErrorCode.TEMPLATE_INVALID, "JSON sample must contain record objects")
        return [dict(item) for item in payload[: self.max_records]]

    @staticmethod
    def _machine_key(header: str, index: int, used: set[str]) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "_", header.casefold()).strip("_")
        if not normalized or not normalized[0].isalpha():
            normalized = f"field_{index}"
        normalized = normalized[:64]
        candidate = normalized
        suffix = 2
        while candidate in used:
            tail = f"_{suffix}"
            candidate = f"{normalized[: 64 - len(tail)]}{tail}"
            suffix += 1
        return candidate

    @staticmethod
    def _infer_type(values: list[Any]) -> FieldType:
        present = [value for value in values if SampleAnalyzer._is_present(value)]
        if not present:
            return FieldType.STRING
        counts: Counter[FieldType] = Counter()
        for value in present:
            text = str(value).strip()
            if isinstance(value, bool) or text.casefold() in {"true", "false", "是", "否"}:
                counts[FieldType.BOOLEAN] += 1
            elif re.fullmatch(r"[-+]?\d+", text):
                counts[FieldType.INTEGER] += 1
            elif re.fullmatch(r"[-+]?(?:\d+\.\d*|\d*\.\d+)", text):
                counts[FieldType.NUMBER] += 1
            elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
                counts[FieldType.DATE] += 1
            else:
                counts[FieldType.STRING] += 1
        inferred, count = counts.most_common(1)[0]
        return inferred if count == len(present) else FieldType.STRING

    @staticmethod
    def _is_unique(values: list[Any]) -> bool:
        normalized = [str(value) for value in values if SampleAnalyzer._is_present(value)]
        return bool(normalized) and len(normalized) == len(values) == len(set(normalized))

    @staticmethod
    def _is_present(value: Any) -> bool:
        return value is not None and value != ""
