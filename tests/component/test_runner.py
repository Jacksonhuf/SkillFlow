import asyncio
import json
from pathlib import Path

from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.models import BrowserCapabilities, BrowserSnapshot, CommandResult, RunState
from browser_skill.runtime.runner import Runner


def test_runner_happy_path_creates_validated_outputs(tmp_path: Path, template) -> None:
    adapter = FakeBrowserAdapter(
        {
            "snapshot": [
                BrowserSnapshot(
                    url="https://example.internal/home",
                    text="退出登录 样机盘点反馈",
                    records=[{"sample_id": "S-1", "sn": "SN-1", "product_model": "P"}],
                )
            ]
        }
    )
    response = asyncio.run(Runner(adapter, tmp_path).run(template, {}))
    assert response.ok is True
    assert response.state == RunState.COMPLETED
    workspace = tmp_path / str(response.run_id)
    assert (workspace / "result.json").exists() or list(workspace.glob("*.json"))
    assert (workspace / "summary.json").exists()
    assert (workspace / "execution.jsonl").exists()
    summary = json.loads((workspace / "summary.json").read_text(encoding="utf-8"))
    assert summary["duration_ms"] >= 0
    assert summary["checkpoint_count"] >= 1
    assert summary["state_durations_ms"]


def test_runner_pauses_and_resumes_after_auth(tmp_path: Path, template) -> None:
    adapter = FakeBrowserAdapter(
        {
            "snapshot": [
                BrowserSnapshot(url="https://example.internal/login", text="用户名 登录"),
                BrowserSnapshot(
                    url="https://example.internal/home",
                    text="退出登录",
                    records=[{"sample_id": "S-1", "sn": "SN-1"}],
                ),
            ]
        }
    )
    runner = Runner(adapter, tmp_path)
    paused = asyncio.run(runner.run(template, {}))
    assert paused.state == RunState.WAIT_USER_AUTH
    resumed = asyncio.run(runner.resume(tmp_path / str(paused.run_id)))
    assert resumed.ok is True
    assert resumed.state == RunState.COMPLETED


def test_sensitive_variable_is_not_persisted(tmp_path: Path, template) -> None:
    template.variables["owner"] = template.variables["owner"].model_copy(update={"sensitive": True})
    adapter = FakeBrowserAdapter(
        {"snapshot": [BrowserSnapshot(url="https://example.internal/login", text="用户名 登录")]}
    )
    response = asyncio.run(Runner(adapter, tmp_path).run(template, {"owner": "top-secret"}))
    persisted = (tmp_path / str(response.run_id) / "run.json").read_text(encoding="utf-8")
    events = (tmp_path / str(response.run_id) / "execution.jsonl").read_text(encoding="utf-8")
    assert "top-secret" not in persisted
    assert "top-secret" not in events


def test_failed_run_writes_terminal_summary(tmp_path: Path, template) -> None:
    adapter = FakeBrowserAdapter(
        {"status": [CommandResult(ok=False, operation="status", safe_stderr="offline")]}
    )

    response = asyncio.run(Runner(adapter, tmp_path).run(template, {}))

    assert response.state == RunState.FAILED
    summary = json.loads(
        (tmp_path / str(response.run_id) / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["state"] == "FAILED"
    assert summary["error"]["code"] == "E_EXTENSION_OFFLINE"
    assert summary["duration_ms"] >= 0


def test_runner_processes_detail_fields_and_per_record_attachment(
    tmp_path: Path, template_data
) -> None:
    from copy import deepcopy

    from browser_skill.models import BrowserTemplate

    data = deepcopy(template_data)
    data["target"]["fields"][2]["source"] = "detail"
    data["target"]["fields"][2]["required"] = True
    data["workflow"]["hints"] = []
    template = BrowserTemplate.model_validate(data)
    list_page = BrowserSnapshot(
        url="https://example.internal/home",
        text="退出登录",
        records=[{"sample_id": "S1", "sn": "SN-1"}],
        elements=[{"record_key": "SN-1", "text": "查看详情", "ref": "@detail"}],
    )
    detail_page = BrowserSnapshot(
        url="https://example.internal/detail/1",
        text="SN-1",
        records=[{"product_model": "P-100"}],
        elements=[
            {
                "record_key": "SN-1",
                "text": "凭证附件",
                "ref": "@download",
                "filename": "evidence.pdf",
            }
        ],
    )
    adapter = FakeBrowserAdapter(
        {
            "snapshot": [
                list_page,
                detail_page,
                BrowserSnapshot(url="https://example.internal/home"),
            ]
        }
    )
    response = asyncio.run(Runner(adapter, tmp_path).run(template, {}))
    assert response.ok is True
    assert response.state == RunState.COMPLETED
    result_path = tmp_path / str(response.run_id) / response.data["artifacts"]["json"]
    assert "P-100" in result_path.read_text(encoding="utf-8")


def test_runner_workflow_uses_snapshot_locator_before_find(tmp_path: Path, template_data) -> None:
    from browser_skill.models import BrowserTemplate

    base = BrowserTemplate.model_validate(template_data)
    template = base.model_copy(
        update={"target": base.target.model_copy(update={"attachments": []})},
        deep=True,
    )
    adapter = FakeBrowserAdapter(
        {
            "snapshot": [
                BrowserSnapshot(
                    url="https://example.internal/home",
                    text="退出登录",
                    elements=[{"text": "盘点反馈", "ref": "@page"}],
                ),
                BrowserSnapshot(
                    url="https://example.internal/inventory",
                    text="退出登录 盘点反馈",
                    elements=[
                        {"label": "日期", "ref": "@date"},
                        {"text": "查询", "ref": "@query"},
                    ],
                ),
                BrowserSnapshot(
                    url="https://example.internal/inventory",
                    text="退出登录 盘点反馈",
                    records=[{"sample_id": "S1", "sn": "SN1"}],
                ),
            ]
        }
    )

    response = asyncio.run(Runner(adapter, tmp_path).run(template, {}))

    assert response.state == RunState.COMPLETED
    assert not any(call[0] == "find" for call in adapter.calls)
    assert any(call[0] == "fill" and call[1][0] == "@date" for call in adapter.calls)


def test_runner_rejects_workflow_navigation_outside_allowed_host(
    tmp_path: Path, template_data
) -> None:
    from browser_skill.models import BrowserTemplate

    template = BrowserTemplate.model_validate(template_data)
    adapter = FakeBrowserAdapter(
        {
            "snapshot": [
                BrowserSnapshot(
                    url="https://example.internal/home",
                    text="退出登录",
                    elements=[{"text": "盘点反馈", "ref": "@page"}],
                ),
                BrowserSnapshot(
                    url="https://evil.example/phishing",
                    text="盘点反馈",
                ),
            ]
        }
    )

    response = asyncio.run(Runner(adapter, tmp_path).run(template, {}))

    assert response.state == RunState.FAILED
    assert response.data["error"]["code"] == "E_ACTION_NOT_ALLOWED"


def test_optional_per_record_attachment_failure_writes_partial_result(
    tmp_path: Path, template_data
) -> None:
    from copy import deepcopy

    from browser_skill.models import BrowserTemplate

    data = deepcopy(template_data)
    data["workflow"]["hints"] = []
    template = BrowserTemplate.model_validate(data)
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

    response = asyncio.run(Runner(adapter, tmp_path).run(template, {}))

    assert response.ok is True
    assert response.state == RunState.PARTIAL
    assert response.data["validation"]["issues"] == []
    assert response.data["validation"]["download_success_rate"] == 0.0


def test_required_per_record_attachment_failure_never_completes(
    tmp_path: Path, template_data
) -> None:
    from copy import deepcopy

    from browser_skill.models import BrowserTemplate

    data = deepcopy(template_data)
    data["workflow"]["hints"] = []
    data["target"]["attachments"][0]["required"] = True
    template = BrowserTemplate.model_validate(data)
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

    response = asyncio.run(Runner(adapter, tmp_path).run(template, {}))

    assert response.ok is False
    assert response.state == RunState.FAILED
    validation = response.data["error"]["details"]["validation"]
    assert validation["issues"][0]["code"] == "required_attachment_missing"


def test_unexpected_browser_dialog_is_dismissed_and_run_stops(
    tmp_path: Path, template_data
) -> None:
    from copy import deepcopy

    from browser_skill.models import BrowserTemplate

    data = deepcopy(template_data)
    data["target"]["attachments"] = []
    data["workflow"]["hints"] = [{"action": "query", "target": "查询"}]
    template = BrowserTemplate.model_validate(data)
    adapter = FakeBrowserAdapter(
        {
            "capabilities": [BrowserCapabilities(snapshot=True, dialogs=True)],
            "snapshot": [
                BrowserSnapshot(
                    url="https://example.internal/home",
                    text="退出登录",
                    elements=[{"text": "查询", "ref": "@query"}],
                )
            ],
            "dialog_status": [CommandResult(ok=True, operation="dialog", data={"status": "open"})],
        }
    )

    response = asyncio.run(Runner(adapter, tmp_path).run(template, {}))

    assert response.state == RunState.FAILED
    assert response.data["error"]["code"] == "E_ACTION_NOT_ALLOWED"
    assert response.data["error"]["stage"] == "dialog"
    assert any(call[0] == "dialog_dismiss" for call in adapter.calls)


def test_resume_rechecks_extension_readiness(tmp_path: Path, template) -> None:
    adapter = FakeBrowserAdapter(
        {
            "status": [
                CommandResult(ok=True, operation="status"),
                CommandResult(ok=False, operation="status"),
            ],
            "snapshot": [BrowserSnapshot(url="https://example.internal/login", text="用户名 登录")],
        }
    )
    runner = Runner(adapter, tmp_path)
    paused = asyncio.run(runner.run(template, {}))

    resumed = asyncio.run(runner.resume(tmp_path / str(paused.run_id)))

    assert paused.state == RunState.WAIT_USER_AUTH
    assert resumed.state == RunState.FAILED
    assert resumed.data["error"]["code"] == "E_EXTENSION_OFFLINE"
