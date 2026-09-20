import asyncio
import json
from pathlib import Path

import pytest

from browser_skill.app import BrowserSkillApp
from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.errors import SkillError
from browser_skill.models import BrowserSnapshot, RunContext, RunState, SkillRequest
from browser_skill.outputs.writer import RunWorkspace
from browser_skill.runtime.recovery import RunRecoveryService
from browser_skill.runtime.run_store import RunStore


def interrupted_run(runs_root: Path, template, *, state: RunState = RunState.EXTRACTING) -> str:
    run_id = "run_interrupted"
    workspace = RunWorkspace(runs_root, run_id)
    context = RunContext(
        run_id=run_id,
        template_id=template.template_id,
        template_version=template.version,
        template_snapshot=template,
        variables={"date": "2026-09-19"},
        workspace=workspace.path,
        state=state,
    )
    workspace.atomic_json("run.json", context.model_dump(mode="json"))
    return run_id


def test_confirmed_recovery_replays_from_entry_as_linked_child(tmp_path: Path, template) -> None:
    run_id = interrupted_run(tmp_path, template)
    adapter = FakeBrowserAdapter(
        {
            "snapshot": [
                BrowserSnapshot(
                    url="https://example.internal/home",
                    text="退出登录",
                    records=[{"sample_id": "S1", "sn": "SN1"}],
                )
            ]
        }
    )

    recovered = asyncio.run(RunRecoveryService(adapter, tmp_path).recover(run_id, confirmed=True))

    assert recovered.child.state == RunState.COMPLETED
    assert recovered.child.run_id != run_id
    original = RunStore(tmp_path).load(run_id)
    assert original.state == RunState.FAILED
    assert original.recovery_run_id == recovered.child.run_id
    summary = json.loads((tmp_path / run_id / "summary.json").read_text(encoding="utf-8"))
    assert summary["error"]["code"] == "E_RUN_INTERRUPTED"
    assert summary["recovery_run_id"] == recovered.child.run_id


def test_recovery_requires_confirmation_and_rejects_auth_pause(tmp_path: Path, template) -> None:
    run_id = interrupted_run(tmp_path, template)
    service = RunRecoveryService(FakeBrowserAdapter(), tmp_path)

    with pytest.raises(SkillError, match="explicit confirmation"):
        asyncio.run(service.recover(run_id, confirmed=False))

    auth_run = interrupted_run(tmp_path / "auth", template, state=RunState.WAIT_USER_AUTH)
    with pytest.raises(SkillError, match="must use resume"):
        asyncio.run(
            RunRecoveryService(FakeBrowserAdapter(), tmp_path / "auth").recover(
                auth_run, confirmed=True
            )
        )


def test_app_recovery_returns_child_run_interaction(tmp_path: Path, template) -> None:
    runs_root = tmp_path / "runs"
    run_id = interrupted_run(runs_root, template)
    adapter = FakeBrowserAdapter(
        {
            "snapshot": [
                BrowserSnapshot(
                    url="https://example.internal/home",
                    text="退出登录",
                    records=[{"sample_id": "S1", "sn": "SN1"}],
                )
            ]
        }
    )
    app = BrowserSkillApp(tmp_path / "templates", runs_root, adapter)

    response = asyncio.run(
        app.handle(SkillRequest(action="recover", run_id=run_id, confirmed=True))
    )

    assert response.ok is True
    assert response.state == RunState.COMPLETED
    assert response.data["interrupted_run_id"] == run_id
    assert response.data["interaction"]["kind"] == "run_result"
