import json
from copy import deepcopy
from pathlib import Path

import pytest

from browser_skill.errors import SkillError
from browser_skill.models import BrowserTemplate, TemplateStatus
from browser_skill.templates.store import TemplateStore


def test_store_round_trip_and_stable_listing(tmp_path: Path, template_data) -> None:
    store = TemplateStore(tmp_path)
    data = deepcopy(template_data)
    template = BrowserTemplate.model_validate(data)
    store.save(template)
    assert store.load(template.template_id) == template
    assert [item.template_id for item in store.list()] == [template.template_id]


def test_store_rejects_mutating_existing_version(tmp_path: Path, template_data) -> None:
    store = TemplateStore(tmp_path)
    template = BrowserTemplate.model_validate(template_data)
    store.save(template)
    changed = template.model_copy(update={"name": "Changed"})
    with pytest.raises(SkillError, match="immutable"):
        store.save(changed)


def test_publish_requires_passing_test(tmp_path: Path, template_data) -> None:
    data = deepcopy(template_data)
    data["status"] = TemplateStatus.TESTING
    template = BrowserTemplate.model_validate(data)
    store = TemplateStore(tmp_path)
    store.save(template)
    with pytest.raises(SkillError):
        store.publish(template.template_id, template.version, test_passed=False)


def test_unpublished_listing_uses_latest_while_normal_listing_uses_published(
    tmp_path: Path, template_data
) -> None:
    store = TemplateStore(tmp_path)
    published = BrowserTemplate.model_validate(template_data)
    store.save(published)
    draft = published.model_copy(
        update={"version": 2, "status": TemplateStatus.DRAFT, "name": "新版草稿"}
    )
    store.save(draft)
    assert store.list()[0].version == 1
    assert store.list(include_unpublished=True)[0].version == 2


def test_store_rejects_symlinked_template_directory(tmp_path: Path, template_data) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    store_root = tmp_path / "templates"
    store_root.mkdir()
    template_id = str(template_data["template_id"])
    (store_root / template_id).symlink_to(outside, target_is_directory=True)
    store = TemplateStore(store_root)

    with pytest.raises(SkillError, match="symlink"):
        store.load(template_id)


@pytest.mark.parametrize("filename", ["metadata.json", "1.yaml"])
def test_store_rejects_symlinked_template_files(
    tmp_path: Path, template_data, filename: str
) -> None:
    store_root = tmp_path / "templates"
    template_id = str(template_data["template_id"])
    template_dir = store_root / template_id
    template_dir.mkdir(parents=True)
    outside = tmp_path / f"outside-{filename.replace('.', '-')}"
    outside.write_text("{}", encoding="utf-8")
    (template_dir / filename).symlink_to(outside)
    store = TemplateStore(store_root)

    with pytest.raises(SkillError, match="symlink"):
        store.load(template_id, 1, require_published=False)


@pytest.mark.parametrize(
    "metadata",
    [
        [],
        {"latest_version": "not-a-version"},
        {"latest_version": True},
        {"latest_version": 0},
        {"published_version": "not-a-version"},
        {"template_id": "different-template", "latest_version": 1},
    ],
)
def test_store_rejects_malformed_metadata_versions(
    tmp_path: Path, template_data, metadata: object
) -> None:
    store_root = tmp_path / "templates"
    template_id = str(template_data["template_id"])
    template_dir = store_root / template_id
    template_dir.mkdir(parents=True)
    (template_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    store = TemplateStore(store_root)

    with pytest.raises(SkillError, match="Invalid metadata"):
        store.next_version(template_id)
