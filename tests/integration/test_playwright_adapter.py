"""Drive the Playwright adapter against a local site with a real (headless) Chrome.

Skipped automatically when Playwright or a Chrome/Chromium binary is not installed.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import threading
from collections.abc import Iterator
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from browser_skill.models import (
    AcquisitionSource,
    BrowserTemplate,
    LearnedMapping,
    RunState,
    SourcePage,
)
from browser_skill.runtime.runner import Runner

pytestmark = pytest.mark.integration

playwright = pytest.importorskip("playwright")

_CHROME = next(
    (
        path
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")
        if (path := shutil.which(name))
    ),
    None,
)
if _CHROME is None:  # pragma: no cover - depends on the environment
    pytest.skip("no Chrome/Chromium binary on PATH", allow_module_level=True)

_ROWS = {
    1: [("S-1", "SN-1", "P100"), ("S-2", "SN-2", "P200")],
    2: [("S-3", "SN-3", "P300")],
}

_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>盘点</title></head><body>
<div>退出登录 样机盘点反馈</div>
<input placeholder="日期" id="date"><button id="q" onclick="load(1)">查询</button>
<table id="t"><thead><tr><th>样机编号</th><th>SN</th><th>产品型号</th><th>凭证</th></tr></thead>
<tbody></tbody></table>
<div class="pager"><span id="pg"></span><button id="next" onclick="nextPage()">下一页</button></div>
<a id="dl" href="/file.bin" download="proof.bin">下载凭证</a>
<button id="alert" onclick="alert('boom')">弹窗</button>
<script>
let page = 1;
async function load(p) {
  page = p;
  const r = await fetch('/api/inventory/list?page=' + p);
  const j = await r.json();
  const tb = document.querySelector('tbody'); tb.innerHTML = '';
  for (const it of j.data.list) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${it.sampleId}</td><td>${it.sn}</td><td>${it.productModel}</td>` +
      `<td><a href="/file.bin?sn=${it.sn}" download>凭证</a></td>`;
    tb.appendChild(tr);
  }
  document.getElementById('pg').textContent = '第 ' + p + ' 页';
  document.getElementById('next').disabled = !j.data.hasMore;
}
function nextPage() { load(page + 1); }
load(1);
</script></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args: Any) -> None:
        return

    def _send(self, body: bytes, content_type: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # http.server API name
        if self.path.startswith("/api/inventory/list"):
            page = int(self.path.split("page=")[1])
            rows = _ROWS.get(page, [])
            payload = {
                "code": 0,
                "data": {
                    "list": [{"sampleId": a, "sn": b, "productModel": c} for a, b, c in rows],
                    "hasMore": page < max(_ROWS),
                },
            }
            self._send(json.dumps(payload).encode("utf-8"), "application/json")
        elif self.path.startswith("/file.bin"):
            self._send(
                b"PROOF" * 100,
                "application/octet-stream",
                {"Content-Disposition": 'attachment; filename="proof.bin"'},
            )
        else:
            self._send(_PAGE.encode("utf-8"), "text/html; charset=utf-8")


@pytest.fixture(scope="module")
def site() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()


def _adapter(tmp_path: Path) -> Any:
    from browser_skill.browser.playwright_adapter import PlaywrightAdapter

    return PlaywrightAdapter(
        executable_path=_CHROME,
        headless=True,
        launch_args=["--no-sandbox", "--disable-gpu"],
        downloads_dir=tmp_path / "downloads",
    )


def test_adapter_primitives_against_local_chrome(site: str, tmp_path: Path) -> None:
    async def scenario() -> None:
        adapter = _adapter(tmp_path)
        try:
            assert (await adapter.status()).ok
            assert (await adapter.capabilities()).network is True
            assert (await adapter.open(site + "/")).ok

            snapshot = await adapter.snapshot()
            assert snapshot.title == "盘点" and "退出登录" in snapshot.text
            headers = [e["text"] for e in snapshot.elements if e.get("role") == "columnheader"]
            assert headers == ["样机编号", "SN", "产品型号", "凭证"]
            cells = [
                e["text"]
                for e in snapshot.elements
                if e.get("role") == "cell" and e.get("column_index") == 1
            ]
            assert cells == ["SN-1", "SN-2"]
            evidence = [e for e in snapshot.elements if e.get("text") == "凭证" and "ref" in e]
            assert [e["row_index"] for e in evidence] == [1, 2]

            found = await adapter.find("下一页")
            assert found.ok and found.data["target"].startswith("@e")
            assert (await adapter.click(found.data["target"])).ok
            second = await adapter.snapshot()
            assert [e["text"] for e in second.elements if e.get("role") == "cell"][:3] == [
                "S-3",
                "SN-3",
                "P300",
            ]
            # Last page: the disabled "下一页" button is neither listed nor findable
            assert not any(e.get("text") == "下一页" for e in second.elements)
            assert (await adapter.find("下一页")).ok is False

            network = await adapter.network_requests()
            urls = [entry["url"].split("?")[1] for entry in network.data if "api" in entry["url"]]
            assert urls == ["page=1", "page=2"]
            assert network.data[-1]["body"]["data"]["list"][0]["sn"] == "SN-3"

            target = tmp_path / "out" / "proof.bin"
            download = await adapter.download("#dl", target)
            assert download.ok and target.read_bytes().startswith(b"PROOF")
            assert (await adapter.list_downloads()).data[-1]["state"] == "completed"

            assert (await adapter.click("#alert")).ok
            status = await adapter.get_dialog_status()
            assert status.data["open"] is True and status.data["message"] == "boom"
            await adapter.dismiss_dialog()
            assert (await adapter.get_dialog_status()).data["open"] is False

            assert (await adapter.fill("#date", "2026-09-01")).ok
            refreshed = await adapter.snapshot()
            assert any(e.get("value") == "2026-09-01" for e in refreshed.elements)
            tabs = await adapter.list_tabs()
            assert tabs.ok and tabs.data[0]["active"] is True
        finally:
            await adapter.close()

    asyncio.run(scenario())


def _network_template(template_data: dict[str, Any], site: str) -> BrowserTemplate:
    data = deepcopy(template_data)
    data["system"] = {
        "entry_url": site + "/",
        "preferred_tab_url_contains": "127.0.0.1",
        "allowed_hosts": ["127.0.0.1"],
    }
    data["target"]["attachments"] = []
    data["target"]["pagination"] = {
        "strategy": "next_button",
        "semantic": ["下一页"],
        "max_pages": 5,
    }
    data["workflow"]["hints"] = [
        {"action": "set_filter", "target": "日期", "value": "${date}"},
        {"action": "query", "target": "查询"},
    ]

    def mapping(key: str) -> dict[str, Any]:
        return LearnedMapping(
            page=SourcePage.LIST,
            strategy="semantic",
            hints=[key],
            confidence=0.9,
            preferred_source=AcquisitionSource.NETWORK,
            endpoint_hint="/api/inventory/list",
            json_path=f"$.data.list[*].{key}",
        ).model_dump(mode="json")

    data["learned"]["field_mappings"] = {
        "sample_id": mapping("sampleId"),
        "sn": mapping("sn"),
        "product_model": mapping("productModel"),
    }
    return BrowserTemplate.model_validate(data)


def test_runner_paginates_over_network_with_playwright(
    site: str, tmp_path: Path, template_data: dict[str, Any]
) -> None:
    template = _network_template(template_data, site)

    async def scenario() -> Any:
        adapter = _adapter(tmp_path)
        try:
            return await Runner(adapter, tmp_path / "runs").run(template, {"date": "2026-09-01"})
        finally:
            await adapter.close()

    response = asyncio.run(scenario())
    assert response.ok, response.message
    assert response.state == RunState.COMPLETED
    run_dir = tmp_path / "runs" / str(response.run_id)
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert [record["sn"] for record in run["records"]] == ["SN-1", "SN-2", "SN-3"]
    events = (run_dir / "execution.jsonl").read_text(encoding="utf-8")
    assert '"event": "network_extraction"' in events
    assert '"network_pages": 2' in events


def test_runner_falls_back_to_dom_table_without_learned_network(
    site: str, tmp_path: Path, template_data: dict[str, Any]
) -> None:
    template = _network_template(template_data, site)
    template.learned.field_mappings = {}
    template.target.fields[0].semantic = ["样机编号"]

    async def scenario() -> Any:
        adapter = _adapter(tmp_path)
        try:
            return await Runner(adapter, tmp_path / "runs").run(template, {"date": "2026-09-01"})
        finally:
            await adapter.close()

    response = asyncio.run(scenario())
    assert response.ok, response.message
    run_dir = tmp_path / "runs" / str(response.run_id)
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert [record["sn"] for record in run["records"]] == ["SN-1", "SN-2", "SN-3"]
    assert run["records"][0]["sample_id"] == "S-1"
