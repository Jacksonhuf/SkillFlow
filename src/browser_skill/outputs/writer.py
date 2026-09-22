from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from browser_skill.errors import ErrorCode, SkillError
from browser_skill.models import OutputFormat, RunContext, ValidationReport
from browser_skill.outputs.paths import contained_path, safe_filename
from browser_skill.outputs.xlsx import XlsxWriter
from browser_skill.outputs.manifest import write_manifest


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date, Path)):
        return str(value)
    raise TypeError(f"Not JSON serializable: {type(value).__name__}")


class RunWorkspace:
    def __init__(self, root: Path, run_id: str) -> None:
        self.root = root.resolve()
        self.path = contained_path(self.root, safe_filename(run_id, fallback="run"))
        self.path.mkdir(parents=True, exist_ok=False)

    @classmethod
    def existing(cls, path: Path) -> RunWorkspace:
        instance = cls.__new__(cls)
        instance.path = path.resolve()
        instance.root = instance.path.parent
        return instance

    def resolve(self, *parts: str) -> Path:
        return contained_path(self.path, *parts)

    def append_jsonl(self, name: str, payload: dict[str, Any]) -> None:
        path = self.resolve(name)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=_json_default) + "\n")

    def atomic_json(self, name: str, payload: Any) -> Path:
        return self._atomic_text(
            self.resolve(name),
            json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        )

    def atomic_text(self, name: str, content: str) -> Path:
        return self._atomic_text(self.resolve(name), content)

    @staticmethod
    def _atomic_text(path: Path, content: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            return path
        finally:
            Path(temporary).unlink(missing_ok=True)


class OutputWriter:
    def __init__(self, xlsx_writer: XlsxWriter | None = None) -> None:
        self.xlsx_writer = xlsx_writer or XlsxWriter()

    def write(self, context: RunContext, report: ValidationReport) -> dict[str, str]:
        workspace = RunWorkspace.existing(context.workspace)
        output = context.template_snapshot.output
        artifacts: dict[str, str] = {}
        try:
            if output.format in {OutputFormat.JSON, OutputFormat.BOTH}:
                name = self._render_name(output.filename_pattern, context.variables, ".json")
                path = workspace.atomic_json(
                    name,
                    {
                        "run_id": context.run_id,
                        "template_id": context.template_id,
                        "template_version": context.template_version,
                        "records": context.records,
                        "attachments": [
                            item.model_dump(mode="json") for item in context.downloaded_files
                        ],
                    },
                )
                artifacts["json"] = path.relative_to(workspace.path).as_posix()
            if output.format in {OutputFormat.CSV, OutputFormat.BOTH}:
                name = self._render_name(output.filename_pattern, context.variables, ".csv")
                path = workspace.resolve(name)
                columns = output.columns or [
                    field.key for field in context.template_snapshot.target.fields
                ]
                fd, temporary = tempfile.mkstemp(
                    prefix=f".{path.name}.", dir=path.parent, text=True
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
                        writer.writeheader()
                        writer.writerows(context.records)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary, path)
                finally:
                    Path(temporary).unlink(missing_ok=True)
                artifacts["csv"] = path.relative_to(workspace.path).as_posix()
            if output.format == OutputFormat.XLSX:
                name = self._render_name(output.filename_pattern, context.variables, ".xlsx")
                path = workspace.resolve(name)
                columns = output.columns or [
                    field.key for field in context.template_snapshot.target.fields
                ]
                self.xlsx_writer.write(path, columns=columns, records=context.records)
                artifacts["xlsx"] = path.relative_to(workspace.path).as_posix()
            manifest_path = write_manifest(context, report, artifacts)
            if manifest_path:
                artifacts["manifest"] = manifest_path
            self.write_summary(context, report=report, artifacts=artifacts)
            artifacts["summary"] = "summary.json"
            return artifacts
        except (OSError, ValueError) as exc:
            raise SkillError(ErrorCode.OUTPUT_WRITE_FAILED, "Unable to write run output") from exc

    def write_summary(
        self,
        context: RunContext,
        *,
        report: ValidationReport | None = None,
        artifacts: dict[str, str] | None = None,
        error: dict[str, Any] | None = None,
    ) -> Path:
        """Write the terminal audit summary for successful and failed Runs."""
        workspace = RunWorkspace.existing(context.workspace)
        finished = context.finished_at or datetime.now(UTC)
        duration_ms = max(0, int((finished - context.started_at).total_seconds() * 1000))
        state_durations: dict[str, int] = {}
        checkpoints = context.checkpoints
        for index, checkpoint in enumerate(checkpoints):
            end = checkpoints[index + 1].created_at if index + 1 < len(checkpoints) else finished
            elapsed = max(0, int((end - checkpoint.created_at).total_seconds() * 1000))
            state_durations[checkpoint.state.value] = (
                state_durations.get(checkpoint.state.value, 0) + elapsed
            )
        payload = {
            "run_id": context.run_id,
            "state": context.state.value,
            "template": f"{context.template_id}@{context.template_version}",
            "record_count": len(context.records),
            "download_count": sum(item.status == "ok" for item in context.downloaded_files),
            "pagination_complete": context.pagination_complete,
            "repair_attempts": context.repair_attempts,
            "recovery_run_id": context.recovery_run_id,
            "duration_ms": duration_ms,
            "checkpoint_count": len(checkpoints),
            "state_durations_ms": state_durations,
            "validation": report.model_dump(mode="json") if report else None,
            "error": error,
            "artifacts": artifacts or {},
        }
        try:
            return workspace.atomic_json("summary.json", payload)
        except (OSError, ValueError) as exc:
            raise SkillError(ErrorCode.OUTPUT_WRITE_FAILED, "Unable to write run summary") from exc

    @staticmethod
    def _render_name(pattern: str, variables: dict[str, Any], suffix: str) -> str:
        rendered = pattern
        for key, value in variables.items():
            rendered = rendered.replace("{" + key + "}", str(value))
        rendered = safe_filename(rendered, fallback="result")
        if Path(rendered).suffix.lower() != suffix:
            rendered = f"{Path(rendered).stem}{suffix}"
        return rendered


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
