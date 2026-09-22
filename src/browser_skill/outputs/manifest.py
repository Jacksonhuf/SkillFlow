from __future__ import annotations

from typing import Any

from browser_skill.models import BrowserTemplate, DownloadStatus, RunContext, ValidationReport


def _record_fingerprint(template: BrowserTemplate, record: dict[str, Any]) -> str | None:
    values = [str(record.get(key, "")) for key in template.target.record_key]
    return "|".join(values) if values and all(values) else None


def write_manifest(
    context: RunContext,
    report: ValidationReport,
    artifacts: dict[str, str],
) -> str:
    template = context.template_snapshot
    if not template.output.manifest:
        return ""
    from browser_skill.outputs.writer import RunWorkspace

    workspace = RunWorkspace.existing(context.workspace)
    bundles: list[dict[str, Any]] = []
    for index, record in enumerate(context.records):
        fingerprint = _record_fingerprint(template, record) or f"row_{index + 1}"
        key_values = {field: record.get(field) for field in template.target.record_key}
        files = [
            item.model_dump(mode="json")
            for item in context.downloaded_files
            if item.status == DownloadStatus.OK
            and (item.record_key is None or item.record_key == fingerprint)
        ]
        bundles.append(
            {
                "bundle_key": fingerprint,
                "record_key": key_values,
                "record": record,
                "files": files,
            }
        )
    payload = {
        "run_id": context.run_id,
        "template": f"{template.template_id}@{template.version}",
        "variables": context.variables,
        "validation_ok": report.ok,
        "record_count": len(context.records),
        "artifacts": artifacts,
        "bundles": bundles,
    }
    path = workspace.atomic_json("manifest.json", payload)
    return path.relative_to(workspace.path).as_posix()
