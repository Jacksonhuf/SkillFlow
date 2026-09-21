import json
from pathlib import Path

import pytest

from browser_skill.errors import SkillError
from browser_skill.models import FieldType
from browser_skill.runtime.sample_analyzer import SampleAnalyzer


def test_csv_infers_fields_types_candidates_and_requiredness(tmp_path: Path) -> None:
    sample = tmp_path / "sample.csv"
    sample.write_text(
        "订单号,日期,金额,合同附件,备注\nA-1,2026-09-19,12.5,a.pdf,ok\n"
        "A-2,2026-09-20,20.0,b.pdf,\n",
        encoding="utf-8",
    )
    inference = SampleAnalyzer().analyze(sample)
    by_name = {field.name: field for field in inference.fields}
    assert inference.sample_record_count == 2
    assert by_name["日期"].type == FieldType.DATE
    assert by_name["金额"].type == FieldType.NUMBER
    assert by_name["备注"].required is False
    assert inference.attachment_columns
    assert inference.variable_candidates
    assert inference.record_key_candidates


def test_json_records_support_nested_values_without_execution(tmp_path: Path) -> None:
    sample = tmp_path / "sample.json"
    sample.write_text(
        json.dumps(
            {
                "records": [
                    {"SN": "A", "metadata": {"source": "sample"}},
                    {"SN": "B", "metadata": {"source": "sample"}},
                ]
            }
        ),
        encoding="utf-8",
    )
    inference = SampleAnalyzer().analyze(sample)
    assert [field.name for field in inference.fields] == ["SN", "metadata"]
    assert inference.record_key_candidates == ["sn"]


def test_rejects_unsupported_or_oversized_sample(tmp_path: Path) -> None:
    unsupported = tmp_path / "sample.xlsx"
    unsupported.write_bytes(b"not an xlsx")
    with pytest.raises(SkillError, match="Only CSV and JSON"):
        SampleAnalyzer().analyze(unsupported)
    large = tmp_path / "large.csv"
    large.write_bytes(b"x" * 10)
    with pytest.raises(SkillError, match="allowed size"):
        SampleAnalyzer(max_bytes=5).analyze(large)
