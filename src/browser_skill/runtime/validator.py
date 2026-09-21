from __future__ import annotations

from browser_skill.models import (
    BrowserTemplate,
    DownloadedFile,
    DownloadStatus,
    ValidationIssue,
    ValidationReport,
)


class ResultValidator:
    def validate(
        self,
        template: BrowserTemplate,
        records: list[dict[str, object]],
        files: list[DownloadedFile],
        *,
        pagination_complete: bool,
    ) -> ValidationReport:
        issues: list[ValidationIssue] = []
        required_fields = [field for field in template.target.fields if field.required]
        total_required = len(required_fields) * len(records)
        present_required = 0
        for index, record in enumerate(records):
            record_key = self._record_key(template, record, fallback=str(index + 1))
            for field in required_fields:
                if record.get(field.key) not in {None, ""}:
                    present_required += 1
                else:
                    issues.append(
                        ValidationIssue(
                            code="required_field_missing",
                            message=f"Required field missing: {field.name}",
                            record_key=record_key,
                        )
                    )
        count = len(records)
        if count < template.validation.min_records:
            issues.append(
                ValidationIssue(code="min_records", message="Minimum record count not met")
            )
        if template.validation.max_records is not None and count > template.validation.max_records:
            issues.append(
                ValidationIssue(code="max_records", message="Maximum record count exceeded")
            )
        if template.validation.pagination_complete and not pagination_complete:
            issues.append(ValidationIssue(code="pagination", message="Pagination is incomplete"))
        if template.validation.unique_record_keys and template.target.record_key:
            keys = [self._record_key(template, record) for record in records]
            if None in keys or len(keys) != len(set(keys)):
                issues.append(
                    ValidationIssue(
                        code="record_key", message="Record keys are missing or duplicated"
                    )
                )

        file_index = {(item.record_key, item.attachment_key): item for item in files}
        required_attachments = [item for item in template.target.attachments if item.required]
        for attachment in required_attachments:
            expected_keys: list[str | None]
            if attachment.per_record:
                expected_keys = [self._record_key(template, record) for record in records]
            else:
                expected_keys = [None]
            for record_key in expected_keys:
                downloaded = file_index.get((record_key, attachment.key))
                if (
                    downloaded is None
                    or downloaded.status != DownloadStatus.OK
                    or downloaded.size <= 0
                ):
                    issues.append(
                        ValidationIssue(
                            code="required_attachment_missing",
                            message=f"Required attachment missing: {attachment.name}",
                            record_key=record_key,
                        )
                    )
        optional_failure = any(
            item.status != DownloadStatus.OK
            and not next(
                (
                    spec.required
                    for spec in template.target.attachments
                    if spec.key == item.attachment_key
                ),
                True,
            )
            for item in files
        )
        required_issues = [issue for issue in issues if issue.required]
        ok_files = sum(item.status == DownloadStatus.OK for item in files)
        return ValidationReport(
            ok=not required_issues,
            partial=not required_issues and optional_failure,
            issues=issues,
            record_count=count,
            download_count=ok_files,
            field_completeness=(present_required / total_required if total_required else 1.0),
            download_success_rate=(ok_files / len(files) if files else 1.0),
        )

    @staticmethod
    def _record_key(
        template: BrowserTemplate, record: dict[str, object], fallback: str | None = None
    ) -> str | None:
        if not template.target.record_key:
            return fallback
        values = [str(record.get(key, "")) for key in template.target.record_key]
        return "|".join(values) if all(values) else fallback
