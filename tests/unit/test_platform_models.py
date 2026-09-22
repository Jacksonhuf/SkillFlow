from __future__ import annotations

from copy import deepcopy

import pytest

from browser_skill.models import BrowserTemplate, LearnedSpec, TemplateStatus
from browser_skill.templates.learned_store import LearnedProfileStore
from browser_skill.templates.store import TemplateStore


def test_learned_profile_round_trip(tmp_path, template_data) -> None:
    store = LearnedProfileStore(tmp_path)
    learned = LearnedSpec(page_hints=["盘点反馈"])
    path = store.save("inventory_feedback", 1, learned)
    assert path.is_file()
    assert store.load("inventory_feedback", 1) == learned


def test_schema_2_stores_learned_separately(tmp_path, template_data) -> None:
    data = deepcopy(template_data)
    data["schema_version"] = "2.0"
    data["status"] = TemplateStatus.DRAFT
    data["learned"] = {"page_hints": ["资产管理"], "field_mappings": {}, "attachment_mappings": {}}
    template = BrowserTemplate.model_validate(data)
    store = TemplateStore(tmp_path)
    store.save(template)
    yaml_text = (tmp_path / template.template_id / "1.yaml").read_text(encoding="utf-8")
    assert "资产管理" not in yaml_text
    loaded = store.load(template.template_id, require_published=False)
    assert loaded.learned.page_hints == ["资产管理"]


def test_acquisition_planner_prefers_learned_source() -> None:
    from browser_skill.acquire.strategies import AcquisitionPlanner
    from browser_skill.models import AcquisitionSource, LearnedMapping, SourcePage

    mapping = LearnedMapping(
        page=SourcePage.LIST,
        strategy="semantic",
        hints=["订单号"],
        preferred_source=AcquisitionSource.NETWORK,
        endpoint_hint="/api/orders",
    )
    chain = AcquisitionPlanner().fallback_chain(mapping)
    assert chain[0] == AcquisitionSource.NETWORK
