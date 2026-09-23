from __future__ import annotations

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
from browser_skill.console import instance as console_instance
from browser_skill.console.instance import (
    _legacy_token_console_at,
    _legacy_ui_at,
    stop_prior_console_on_port,
)
from browser_skill.console.server import ConsoleServer
from browser_skill.models import BrowserSnapshot, BrowserTemplate
from browser_skill.templates.store import TemplateStore


@pytest.fixture
def running_console(tmp_path: Path, template_data: dict[str, Any]) -> Iterator[ConsoleServer]:
    templates = tmp_path / "templates"
    TemplateStore(templates).save(BrowserTemplate.model_validate(template_data))
    adapter = FakeBrowserAdapter({"snapshot": [BrowserSnapshot(url="https://x", text="")]} )
    app = BrowserSkillApp(templates, tmp_path / "runs", adapter)
    server = ConsoleServer(app, port=0)
    server.start()
    try:
        yield server
    finally:
        server.shutdown()


def _post(server: ConsoleServer, path: str) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.port}{path}",
        data=b"{}",
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_shutdown_endpoint_stops_server(running_console: ConsoleServer) -> None:
    status, body = _post(running_console, "/api/shutdown")
    assert status == 200
    assert body["ok"] is True
    time.sleep(0.3)
    deadline = time.time() + 5.0
    while time.time() < deadline:
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{running_console.port}/api/meta", timeout=0.5
            )
        except (OSError, urllib.error.URLError):
            return
        time.sleep(0.1)
    pytest.fail("server still responding after shutdown")


def test_new_console_replaces_listener_on_same_port(
    tmp_path: Path, template_data: dict[str, Any]
) -> None:
    templates = tmp_path / "templates"
    TemplateStore(templates).save(BrowserTemplate.model_validate(template_data))
    adapter = FakeBrowserAdapter({"snapshot": [BrowserSnapshot(url="https://x", text="")]} )
    app = BrowserSkillApp(templates, tmp_path / "runs", adapter)
    first = ConsoleServer(app, port=0)
    first.start()
    port = first.port
    try:
        second = ConsoleServer(app, port=port)
        assert second.port == port
        assert second.prior_instance_note is not None
        assert "旧控制台" in second.prior_instance_note
        second.start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/meta", timeout=2) as resp:
                meta = json.loads(resp.read())["meta"]
            from browser_skill import __version__

            assert meta["version"] == __version__
        finally:
            second.shutdown()
    finally:
        first.shutdown()


def test_legacy_token_and_ui_probes() -> None:
    import threading
    from http import HTTPStatus
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class LegacyHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path.startswith("/api/"):
                self.send_response(HTTPStatus.UNAUTHORIZED)
                self.end_headers()
                self.wfile.write(b'{"ok":false,"message":"Unauthorized"}')
                return
            self.send_response(HTTPStatus.OK)
            self.end_headers()
            self.wfile.write(b"<html><div id=tokenGate></div></html>")

        def log_message(self, *_args: object) -> None:
            return

    legacy = ThreadingHTTPServer(("127.0.0.1", 0), LegacyHandler)
    thread = threading.Thread(target=legacy.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{legacy.server_address[1]}/"
    try:
        assert _legacy_token_console_at(base)
        assert _legacy_ui_at(base)
    finally:
        legacy.shutdown()
        legacy.server_close()
        thread.join(timeout=2)


def test_stop_prior_clears_legacy_token_console(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console_instance, "_pids_listening_on_loopback", lambda _port: [4242])
    monkeypatch.setattr(console_instance, "_legacy_token_console_at", lambda _base: True)
    monkeypatch.setattr(console_instance, "_legacy_ui_at", lambda _base: False)
    monkeypatch.setattr(console_instance, "_meta_at", lambda _base: None)
    monkeypatch.setattr(console_instance, "_wait_port_free", lambda _port: True)
    stopped: list[int] = []
    monkeypatch.setattr(console_instance, "_terminate_pid", lambda pid: stopped.append(pid))

    result = stop_prior_console_on_port("127.0.0.1", 8765)
    assert result.stopped is True
    assert stopped == [4242]
    assert "token" in (result.message or "")
