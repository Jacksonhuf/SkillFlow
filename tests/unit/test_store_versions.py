from __future__ import annotations

from pathlib import Path

import pytest

from browser_skill.errors import SkillError
from browser_skill.models import BrowserTemplate, TemplateStatus
from browser_skill.templates.store import TemplateStore


def test_list_versions_sorted(tmp_path: Path, template_data: dict[str, object]) -> None:
    store = TemplateStore(tmp_path)
    published = BrowserTemplate.model_validate(template_data)
    store.save(published)
    draft = published.model_copy(
        update={"version": 2, "status": TemplateStatus.DRAFT, "name": "草稿二"}
    )
    store.save(draft)
    rows = store.version_history(published.template_id)
    assert [row.version for row in rows] == [1, 2]
    assert rows[1].status == TemplateStatus.DRAFT


def test_list_versions_missing_template(tmp_path: Path) -> None:
    store = TemplateStore(tmp_path)
    with pytest.raises(SkillError, match="not found"):
        store.version_history("missing")
