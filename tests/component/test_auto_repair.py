import asyncio
from pathlib import Path

import pytest

from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.errors import SkillError
from browser_skill.models import BrowserSnapshot, RunState
from browser_skill.runtime.auto_repair import AutoRepairService
from browser_skill.runtime.run_store import RunStore
from browser_skill.runtime.runner import Runner
from browser_skill.templates.store import TemplateStore


def test_auto_repair_rediscovers_tests_publishes_and_links_original_run(
    tmp_path: Path, template
) -> None:
    templates_root = tmp_path / "templates"
    runs_root = tmp_path / "runs"
    store = TemplateStore(templates_root)
    store.save(template)
    adapter = FakeBrowserAdapter(
        {
            "snapshot": [
                BrowserSnapshot(
                    url="https://example.internal/home",
                    text="退出登录",
                    records=[{"sample_id": "S1", "sn": ""}],
                ),
                BrowserSnapshot(
                    url="https://example.internal/home",
                    text="退出登录",
                    elements=[{"text": "样机ID"}, {"text": "SN"}],
                ),
                BrowserSnapshot(
                    url="https://example.internal/home",
                    text="退出登录",
                    records=[{"sample_id": "S1", "sn": "SN1"}],
                ),
            ]
        }
    )
    failed = asyncio.run(Runner(adapter, runs_root).run(template, {}))
    assert failed.state == RunState.FAILED
    repaired = asyncio.run(AutoRepairService(adapter, store, runs_root).repair(str(failed.run_id)))
    assert repaired.state == RunState.COMPLETED
    assert repaired.repair_attempts == 1
    assert repaired.recovery_run_id
    assert repaired.repaired_template_version == 2
    assert store.load(template.template_id).version == 2
    persisted = RunStore(runs_root).load(str(failed.run_id))
    assert persisted.state == RunState.COMPLETED
    assert persisted.recovery_run_id == repaired.recovery_run_id


def test_auto_repair_is_limited_to_one_attempt(tmp_path: Path, template) -> None:
    templates_root = tmp_path / "templates"
    runs_root = tmp_path / "runs"
    store = TemplateStore(templates_root)
    store.save(template)
    adapter = FakeBrowserAdapter(
        {
            "snapshot": [
                BrowserSnapshot(
                    url="https://example.internal/home",
                    text="退出登录",
                    records=[{"sample_id": "S1", "sn": ""}],
                ),
                BrowserSnapshot(
                    url="https://example.internal/home",
                    text="退出登录",
                    elements=[{"text": "样机ID"}],
                ),
            ]
        }
    )
    failed = asyncio.run(Runner(adapter, runs_root).run(template, {}))
    service = AutoRepairService(adapter, store, runs_root)
    with pytest.raises(SkillError, match="rediscover"):
        asyncio.run(service.repair(str(failed.run_id)))
    persisted = RunStore(runs_root).load(str(failed.run_id))
    assert persisted.repair_attempts == 1
    assert persisted.state == RunState.FAILED
    with pytest.raises(SkillError, match="limited to one attempt"):
        asyncio.run(service.repair(str(failed.run_id)))
