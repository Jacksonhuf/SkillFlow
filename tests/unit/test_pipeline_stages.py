from __future__ import annotations

import asyncio
import json
import threading
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, ClassVar

from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.models import BrowserSnapshot, BrowserTemplate, RunState
from browser_skill.pipeline.process import apply_processing
from browser_skill.runtime.runner import Runner


def _template_with(template_data: dict[str, Any], **sections: Any) -> BrowserTemplate:
    data = deepcopy(template_data)
    data["schema_version"] = "2.0"
    data["target"]["attachments"] = []
    data["workflow"]["hints"] = []
    data.update(sections)
    return BrowserTemplate.model_validate(data)


def _adapter() -> FakeBrowserAdapter:
    return FakeBrowserAdapter(
        {
            "snapshot": [
                BrowserSnapshot(
                    url="https://example.internal/home",
                    text="退出登录 样机盘点反馈",
                    records=[
                        {"sample_id": "S-1", "sn": "SN-1", "product_model": " 1,200 "},
                        {"sample_id": "S-1", "sn": "SN-1", "product_model": ""},
                    ],
                )
            ]
        }
    )


def test_processing_steps_transform_records(template_data) -> None:
    template = _template_with(
        template_data,
        processing={
            "enabled": True,
            "steps": [
                {"action": "coerce_type", "params": {"field": "product_model", "type": "number"}},
                {"action": "default_value", "params": {"field": "product_model", "value": 0}},
                {"action": "dedupe_records", "params": {}},
                {"action": "rename_field", "params": {"from": "sn", "to": "serial"}},
            ],
        },
    )
    records = [
        {"sample_id": "S-1", "sn": "SN-1", "product_model": " 1,200 "},
        {"sample_id": "S-1", "sn": "SN-1", "product_model": ""},
        {"sample_id": "S-2", "sn": "SN-2", "product_model": ""},
    ]
    result = apply_processing(template, records)
    assert result == [
        {"sample_id": "S-1", "serial": "SN-1", "product_model": 1200.0},
        {"sample_id": "S-2", "serial": "SN-2", "product_model": 0},
    ]
    assert records[0]["product_model"] == " 1,200 "


def test_processing_disabled_passes_through(template_data) -> None:
    template = _template_with(template_data)
    records = [{"sample_id": "S-1", "sn": "SN-1"}]
    assert apply_processing(template, records) is records


def test_run_writes_report_manifest_and_local_delivery(tmp_path: Path, template_data) -> None:
    target = tmp_path / "delivered"
    template = _template_with(
        template_data,
        processing={"enabled": True, "steps": [{"action": "dedupe_records", "params": {}}]},
        report={"enabled": True, "title_pattern": "盘点 {date}", "include_summary": True},
        delivery={
            "enabled": True,
            "channels": [{"type": "local", "target": str(target), "enabled": True}],
        },
    )
    runs = tmp_path / "runs"
    response = asyncio.run(Runner(_adapter(), runs).run(template, {"date": "2026-09-01"}))
    assert response.ok, response.message
    assert response.state == RunState.COMPLETED
    workspace = runs / str(response.run_id)
    artifacts = response.data["artifacts"]
    assert {"report", "manifest", "pipeline"} <= set(artifacts)
    report_text = (workspace / "report.md").read_text(encoding="utf-8")
    assert report_text.startswith("# 盘点 2026-09-01")
    assert "记录数：1" in report_text
    manifest = json.loads((workspace / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["record_count"] == 1
    assert manifest["bundles"][0]["bundle_key"] == "SN-1"
    pipeline = json.loads((workspace / "pipeline.json").read_text(encoding="utf-8"))
    assert pipeline["stages"]["deliver"]["delivered"] is True
    assert (target / str(response.run_id) / "report.md").is_file()
    summary = json.loads((workspace / "summary.json").read_text(encoding="utf-8"))
    assert "report" in summary["artifacts"]


class _Hook(BaseHTTPRequestHandler):
    received: ClassVar[list[dict[str, Any]]] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        _Hook.received.append(json.loads(self.rfile.read(length)))
        self.send_response(204)
        self.end_headers()

    def log_message(self, *_args: Any) -> None:
        return


def test_webhook_delivery_posts_summary_and_failure_does_not_break_run(
    tmp_path: Path, template_data
) -> None:
    server = HTTPServer(("127.0.0.1", 0), _Hook)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/hook"
        template = _template_with(
            template_data,
            delivery={
                "enabled": True,
                "channels": [
                    {"type": "webhook", "target": url, "enabled": True},
                    {"type": "webhook", "target": "http://127.0.0.1:9/dead", "enabled": True},
                ],
            },
        )
        response = asyncio.run(Runner(_adapter(), tmp_path).run(template, {}))
    finally:
        server.shutdown()
        server.server_close()
    assert response.ok
    channels = response.data["pipeline"]["stages"]["deliver"]["channels"]
    assert channels[0]["ok"] is True
    assert channels[1]["ok"] is False and "error" in channels[1]
    assert _Hook.received and _Hook.received[0]["run_id"] == response.run_id
