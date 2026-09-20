import json
from pathlib import Path

import pytest

from browser_skill.errors import ErrorCode, SkillError
from browser_skill.models import BrowserTemplate, TemplateStatus
from browser_skill.runtime.lifecycle import TemplateLifecycleService
from browser_skill.templates.store import TemplateStore


def write_summary(
    runs_root: Path,
    run_id: str,
    *,
    template: str,
    state: str,
) -> None:
    directory = runs_root / run_id
    directory.mkdir(parents=True)
    (directory / "summary.json").write_text(
        json.dumps({"template": template, "state": state}),
        encoding="utf-8",
    )


def test_publish_requires_confirmation_and_exact_completed_evidence(
    tmp_path: Path, template_data
) -> None:
    data = dict(template_data)
    data["status"] = TemplateStatus.TESTING
    template = BrowserTemplate.model_validate(data)
    store = TemplateStore(tmp_path / "templates")
    store.save(template)
    runs_root = tmp_path / "runs"
    write_summary(
        runs_root,
        "run_test",
        template="inventory_feedback@1",
        state="COMPLETED",
    )
    service = TemplateLifecycleService(store, runs_root)
    with pytest.raises(SkillError) as raised:
        service.publish(
            template.template_id,
            template.version,
            test_run_id="run_test",
            confirmed=False,
        )
    assert raised.value.code == ErrorCode.ACTION_NOT_ALLOWED
    published = service.publish(
        template.template_id,
        template.version,
        test_run_id="run_test",
        confirmed=True,
    )
    assert published.status == TemplateStatus.PUBLISHED


def test_publish_rejects_different_version_evidence(tmp_path: Path, template_data) -> None:
    data = dict(template_data)
    data["status"] = TemplateStatus.TESTING
    template = BrowserTemplate.model_validate(data)
    store = TemplateStore(tmp_path / "templates")
    store.save(template)
    runs_root = tmp_path / "runs"
    write_summary(
        runs_root,
        "run_wrong",
        template="inventory_feedback@999",
        state="COMPLETED",
    )
    with pytest.raises(SkillError) as raised:
        TemplateLifecycleService(store, runs_root).publish(
            template.template_id,
            template.version,
            test_run_id="run_wrong",
            confirmed=True,
        )
    assert raised.value.code == ErrorCode.VALIDATION_FAILED


def test_publish_rejects_unsafe_run_identifier(tmp_path: Path, template_data) -> None:
    template = BrowserTemplate.model_validate(template_data)
    store = TemplateStore(tmp_path / "templates")
    store.save(template)
    with pytest.raises(SkillError) as raised:
        TemplateLifecycleService(store, tmp_path / "runs").publish(
            template.template_id,
            template.version,
            test_run_id="../../outside",
            confirmed=True,
        )
    assert raised.value.code == ErrorCode.UNSAFE_OUTPUT_PATH
