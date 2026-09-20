import json
from pathlib import Path

from browser_skill.telemetry.metrics import RunMetricsAggregator


def write_summary(root: Path, run_id: str, payload: dict[str, object]) -> None:
    directory = root / run_id
    directory.mkdir(parents=True)
    (directory / "summary.json").write_text(json.dumps(payload), encoding="utf-8")


def test_aggregates_only_terminal_summary_metrics_without_result_data(tmp_path: Path) -> None:
    write_summary(
        tmp_path,
        "run_one",
        {
            "state": "COMPLETED",
            "template": "inventory_feedback@1",
            "record_count": 10,
            "download_count": 8,
            "duration_ms": 100,
            "repair_attempts": 1,
            "recovery_run_id": None,
            "validation": {"field_completeness": 1.0, "download_success_rate": 0.8},
            "records": [{"secret": "must not be consumed"}],
        },
    )
    write_summary(
        tmp_path,
        "run_two",
        {
            "state": "FAILED",
            "template": "inventory_feedback@2",
            "record_count": 2,
            "download_count": 0,
            "duration_ms": 300,
            "repair_attempts": 0,
            "recovery_run_id": "run_child",
            "validation": {"field_completeness": 0.5, "download_success_rate": 0.0},
        },
    )

    report = RunMetricsAggregator(tmp_path).aggregate()

    assert report.scanned_runs == 2
    assert report.state_counts == {"COMPLETED": 1, "FAILED": 1}
    assert report.template_counts == {"inventory_feedback": 2}
    assert report.total_records == 12
    assert report.total_downloads == 8
    assert report.average_duration_ms == 200
    assert report.average_field_completeness == 0.75
    assert report.average_download_success_rate == 0.4
    assert report.repaired_runs == 1
    assert report.recovered_runs == 1


def test_ignores_malformed_and_symlinked_summaries_and_supports_filter(tmp_path: Path) -> None:
    write_summary(
        tmp_path,
        "run_valid",
        {
            "state": "COMPLETED",
            "template": "sales_report@1",
            "record_count": 3,
            "download_count": 0,
            "duration_ms": 1,
        },
    )
    malformed = tmp_path / "run_bad"
    malformed.mkdir()
    (malformed / "summary.json").write_text("not-json", encoding="utf-8")
    outside = tmp_path / "outside.json"
    outside.write_text('{"state":"COMPLETED"}', encoding="utf-8")
    linked = tmp_path / "run_linked"
    linked.mkdir()
    (linked / "summary.json").symlink_to(outside)

    matching = RunMetricsAggregator(tmp_path).aggregate(template_id="sales_report")
    absent = RunMetricsAggregator(tmp_path).aggregate(template_id="another_template")

    assert matching.scanned_runs == 1
    assert matching.ignored_runs == 2
    assert absent.scanned_runs == 0
    assert absent.ignored_runs == 2


def test_aggregation_is_bounded_to_most_recent_runs(tmp_path: Path) -> None:
    for index in range(3):
        write_summary(
            tmp_path,
            f"run_{index}",
            {
                "state": "COMPLETED",
                "template": "inventory_feedback@1",
                "record_count": index,
                "download_count": 0,
                "duration_ms": index,
            },
        )

    report = RunMetricsAggregator(tmp_path, max_runs=2).aggregate()

    assert report.scanned_runs == 2
