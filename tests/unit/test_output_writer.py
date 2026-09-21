import csv
import json
from pathlib import Path

from browser_skill.models import RunContext, RunState
from browser_skill.outputs.writer import OutputWriter, RunWorkspace
from browser_skill.runtime.validator import ResultValidator


def test_writes_and_validates_ten_thousand_records(tmp_path: Path, template) -> None:
    workspace = RunWorkspace(tmp_path, "run_large")
    records = [
        {"sample_id": f"S{index}", "sn": f"SN{index}", "product_model": "P"}
        for index in range(10_000)
    ]
    context = RunContext(
        run_id="run_large",
        template_id=template.template_id,
        template_version=template.version,
        template_snapshot=template,
        variables={"date": "2026-09-19"},
        workspace=workspace.path,
        state=RunState.COMPLETED,
        records=records,
    )
    report = ResultValidator().validate(template, records, [], pagination_complete=True)

    artifacts = OutputWriter().write(context, report)

    assert report.ok is True
    with (workspace.path / artifacts["csv"]).open(encoding="utf-8", newline="") as handle:
        assert sum(1 for _ in csv.DictReader(handle)) == 10_000
    payload = json.loads((workspace.path / artifacts["json"]).read_text(encoding="utf-8"))
    assert len(payload["records"]) == 10_000
