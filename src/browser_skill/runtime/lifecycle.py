from __future__ import annotations

import json
from pathlib import Path

from browser_skill.errors import ErrorCode, SkillError
from browser_skill.models import BrowserTemplate
from browser_skill.outputs.paths import contained_path, safe_filename
from browser_skill.runtime.test_evidence import accepts_test_run_evidence
from browser_skill.templates.store import TemplateStore


class TemplateLifecycleService:
    """Apply test evidence and explicit confirmation to template publication."""

    def __init__(self, store: TemplateStore, runs_root: Path) -> None:
        self.store = store
        self.runs_root = runs_root.resolve()

    def publish(
        self,
        template_id: str,
        version: int,
        *,
        test_run_id: str,
        confirmed: bool,
    ) -> BrowserTemplate:
        if not confirmed:
            raise SkillError(
                ErrorCode.ACTION_NOT_ALLOWED,
                "Publishing a template requires explicit user confirmation",
                stage="publish",
            )
        safe_run_id = safe_filename(test_run_id, fallback="invalid")
        if safe_run_id != test_run_id:
            raise SkillError(ErrorCode.UNSAFE_OUTPUT_PATH, "Invalid test run identifier")
        summary_path = contained_path(self.runs_root, test_run_id, "summary.json")
        if not summary_path.is_file():
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Test Run evidence was not found")
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Test Run evidence is invalid") from exc
        expected = f"{template_id}@{version}"
        if not accepts_test_run_evidence(summary, expected_template=expected):
            raise SkillError(
                ErrorCode.VALIDATION_FAILED,
                "试跑证据无效：须为同一模板版本，且状态为 COMPLETED，"
                "或为 PARTIAL 且必填校验已通过（常见原因：可选附件未下载，status 为 missing）。",
                stage="publish",
            )
        return self.store.publish(template_id, version, test_passed=True)
