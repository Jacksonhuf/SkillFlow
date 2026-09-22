from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from browser_skill.app import BrowserSkillApp
from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.console.server import ConsoleServer
from browser_skill.errors import SkillError
from browser_skill.models import BrowserSnapshot, BrowserTemplate
from browser_skill.templates.store import TemplateStore


@pytest.fixture
def console(tmp_path: Path, template_data: dict[str, Any]) -> Iterator[ConsoleServer]:
    templates = tmp_path / "templates"
    data = json.loads(json.dumps(template_data))
    data["target"]["attachments"] = []
    data["workflow"]["hints"] = []
    data["report"] = {"enabled": True}
    TemplateStore(templates).save(BrowserTemplate.model_validate(data))
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
    app = BrowserSkillApp(templates, tmp_path / "runs", adapter)
    server = ConsoleServer(app, port=0, token="test-token")
    server.start()
    try:
        yield server
    finally:
        server.shutdown()


def _call(
    server: ConsoleServer,
    path: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    token: str | None = "test-token",
) -> tuple[int, Any, dict[str, str]]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.port}{path}",
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    if token is not None:
        request.add_header("X-Console-Token", token)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read()
            headers = {k.lower(): v for k, v in response.headers.items()}
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        headers = {k.lower(): v for k, v in exc.headers.items()}
        status = exc.code
    if headers.get("content-type", "").startswith("application/json"):
        return status, json.loads(raw), headers
    return status, raw, headers


def _wait_job(server: ConsoleServer, job_id: str) -> dict[str, Any]:
    deadline = time.time() + 15
    while time.time() < deadline:
        status, payload, _ = _call(server, f"/api/jobs/{job_id}")
        assert status == 200
        if payload["job"]["status"] == "done":
            return payload["job"]["response"]
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_ui_is_served_without_token_but_api_requires_it(console: ConsoleServer) -> None:
    status, body, headers = _call(console, "/", token=None)
    assert status == 200
    assert "text/html" in headers["content-type"]
    assert b"Universal Browser" in body

    status, _, _ = _call(console, "/api/templates", token=None)
    assert status == 401
    status, _, _ = _call(console, "/api/templates", token="wrong")
    assert status == 401


def test_templates_and_detail(console: ConsoleServer) -> None:
    status, payload, _ = _call(console, "/api/templates")
    assert status == 200
    assert payload["templates"][0]["template_id"] == "inventory_feedback"

    status, payload, _ = _call(console, "/api/templates/inventory_feedback")
    assert status == 200
    names = {item["name"] for item in payload["template"]["variables"]}
    assert names == {"date", "owner"}
    assert payload["template"]["pipeline"]["report"] is True

    status, _, _ = _call(console, "/api/templates/missing")
    assert status == 404


def test_run_job_and_run_history_and_artifact_download(console: ConsoleServer) -> None:
    status, payload, _ = _call(
        console,
        "/api/jobs",
        method="POST",
        body={"action": "run", "template_id": "inventory_feedback", "variables": {}},
    )
    assert status == 202
    response = _wait_job(console, payload["job"]["job_id"])
    assert response["ok"] is True
    run_id = response["run_id"]
    assert "report" in response["data"]["artifacts"]

    status, payload, _ = _call(console, "/api/runs")
    assert status == 200
    assert payload["runs"][0]["run_id"] == run_id
    assert payload["runs"][0]["state"] == "COMPLETED"

    status, payload, _ = _call(console, f"/api/runs/{run_id}")
    assert status == 200
    assert payload["run"]["summary"]["record_count"] == 1
    assert payload["run"]["report_markdown"].startswith("#")
    assert payload["run"]["pipeline"]["stages"]["report"]["enabled"] is True

    status, body, headers = _call(console, f"/api/runs/{run_id}/files/report.md")
    assert status == 200
    assert "attachment" in headers["content-disposition"]
    assert body.startswith(b"#")

    status, _, _ = _call(console, f"/api/runs/{run_id}/files/../../pyproject.toml")
    assert status in {400, 404}
    status, _, _ = _call(console, f"/api/runs/{run_id}/files/%2e%2e/%2e%2e/pyproject.toml")
    assert status in {400, 404}


def test_sync_action_rejects_browser_actions_and_accepts_start(console: ConsoleServer) -> None:
    status, payload, _ = _call(console, "/api/action", method="POST", body={"action": "start"})
    assert status == 200
    assert payload["ok"] is True
    assert payload["data"]["templates"]

    status, payload, _ = _call(
        console, "/api/action", method="POST", body={"action": "run", "template_id": "x"}
    )
    assert status == 400
    assert "jobs" in payload["message"]

    status, payload, _ = _call(console, "/api/action", method="POST", body={"action": "nope"})
    assert status == 400


def test_sample_upload_then_analyze(console: ConsoleServer) -> None:
    csv_text = "订单号,供应商,金额\nSO001,Acme,10\nSO002,Beta,20\n"
    content = base64.b64encode(csv_text.encode("utf-8")).decode("ascii")
    status, payload, _ = _call(
        console,
        "/api/samples",
        method="POST",
        body={"filename": "../orders.csv", "content_base64": content},
    )
    assert status == 200
    assert "/" not in payload["sample_path"] and ".." not in payload["sample_path"]
    status, result, _ = _call(
        console,
        "/api/action",
        method="POST",
        body={"action": "analyze_sample", "sample_path": payload["sample_path"]},
    )
    assert status == 200
    assert result["ok"] is True
    assert result["data"]["inference"]["fields"]


def test_doctor_and_meta(console: ConsoleServer) -> None:
    status, payload, _ = _call(console, "/api/doctor")
    assert status == 200
    assert "ready" in payload["doctor"]
    status, payload, _ = _call(console, "/api/meta")
    assert status == 200
    assert payload["meta"]["runs_root"]


def test_console_refuses_non_loopback_bind(tmp_path: Path) -> None:
    app = BrowserSkillApp(tmp_path / "t", tmp_path / "r", FakeBrowserAdapter())
    with pytest.raises(SkillError):
        ConsoleServer(app, host="0.0.0.0", port=0)
