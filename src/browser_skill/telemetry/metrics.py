from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from browser_skill.models import RunMetricsReport


class RunMetricsAggregator:
    """Aggregate bounded, non-sensitive terminal summaries without reading result records."""

    def __init__(self, runs_root: Path, *, max_runs: int = 1_000) -> None:
        self.root = runs_root.resolve()
        self.max_runs = max(1, max_runs)

    def aggregate(self, *, template_id: str | None = None) -> RunMetricsReport:
        state_counts: dict[str, int] = {}
        template_counts: dict[str, int] = {}
        durations: list[int] = []
        field_rates: list[float] = []
        download_rates: list[float] = []
        records = downloads = repaired = recovered = ignored = 0
        scanned = 0
        for directory in self._run_directories():
            summary = directory / "summary.json"
            try:
                if summary.is_symlink() or not summary.is_file():
                    ignored += 1
                    continue
                payload = json.loads(summary.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("summary is not an object")
                template = str(payload.get("template", ""))
                current_template = template.rsplit("@", 1)[0]
                if template_id is not None and current_template != template_id:
                    continue
                state = str(payload["state"])
                duration = self._nonnegative_int(payload.get("duration_ms", 0))
                record_count = self._nonnegative_int(payload.get("record_count", 0))
                download_count = self._nonnegative_int(payload.get("download_count", 0))
            except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                ignored += 1
                continue
            scanned += 1
            state_counts[state] = state_counts.get(state, 0) + 1
            template_counts[current_template] = template_counts.get(current_template, 0) + 1
            durations.append(duration)
            records += record_count
            downloads += download_count
            if self._nonnegative_int(payload.get("repair_attempts", 0)):
                repaired += 1
            if payload.get("recovery_run_id"):
                recovered += 1
            validation = payload.get("validation")
            if isinstance(validation, dict):
                self._append_rate(field_rates, validation.get("field_completeness"))
                self._append_rate(download_rates, validation.get("download_success_rate"))
        return RunMetricsReport(
            scanned_runs=scanned,
            ignored_runs=ignored,
            state_counts=state_counts,
            template_counts=template_counts,
            total_records=records,
            total_downloads=downloads,
            average_duration_ms=sum(durations) / len(durations) if durations else 0.0,
            average_field_completeness=(
                sum(field_rates) / len(field_rates) if field_rates else 1.0
            ),
            average_download_success_rate=(
                sum(download_rates) / len(download_rates) if download_rates else 1.0
            ),
            repaired_runs=repaired,
            recovered_runs=recovered,
        )

    def _run_directories(self) -> list[Path]:
        if not self.root.is_dir():
            return []
        directories = [
            item
            for item in self.root.iterdir()
            if item.is_dir() and not item.is_symlink() and item.parent == self.root
        ]
        directories.sort(key=lambda item: item.stat().st_mtime_ns, reverse=True)
        return directories[: self.max_runs]

    @staticmethod
    def _nonnegative_int(value: Any) -> int:
        parsed = int(value)
        if parsed < 0:
            raise ValueError("metric must be nonnegative")
        return parsed

    @staticmethod
    def _append_rate(values: list[float], value: Any) -> None:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return
        if 0.0 <= parsed <= 1.0:
            values.append(parsed)
