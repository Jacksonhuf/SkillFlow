from __future__ import annotations

import asyncio
import json
import threading
from copy import deepcopy
from email import message_from_bytes
from email.policy import default as default_policy
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlsplit

import pytest

from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.models import BrowserSnapshot, BrowserTemplate
from browser_skill.pipeline import deliver as deliver_module
from browser_skill.runtime.runner import Runner


def _template(template_data: dict[str, Any], channels: list[dict[str, Any]]) -> BrowserTemplate:
    data = deepcopy(template_data)
    data["schema_version"] = "2.0"
    data["target"]["attachments"] = []
    data["workflow"]["hints"] = []
    data["analysis"] = {"enabled": True}
    data["report"] = {"enabled": True}
    data["delivery"] = {"enabled": True, "channels": channels}
    return BrowserTemplate.model_validate(data)


def _adapter() -> FakeBrowserAdapter:
    return FakeBrowserAdapter(
        {
            "snapshot": [
                BrowserSnapshot(
                    url="https://example.internal/home",
                    text="退出登录 样机盘点反馈",
                    records=[{"sample_id": "S-1", "sn": "SN-1", "product_model": "P100"}],
                )
            ]
        }
    )


class _FakeSMTP:
    instances: ClassVar[list[_FakeSMTP]] = []

    def __init__(self, host: str, port: int, security: str) -> None:
        self.host, self.port, self.security = host, port, security
        self.logins: list[tuple[str, str]] = []
        self.sent: list[bytes] = []
        _FakeSMTP.instances.append(self)

    def __enter__(self) -> _FakeSMTP:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def login(self, user: str, password: str) -> None:
        self.logins.append((user, password))

    def send_message(self, message: Any) -> None:
        self.sent.append(message.as_bytes())


@pytest.fixture
def smtp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(deliver_module.SMTP_HOST_ENV, "smtp.example.internal")
    monkeypatch.setenv(deliver_module.SMTP_PORT_ENV, "2525")
    monkeypatch.setenv(deliver_module.SMTP_USER_ENV, "robot@example.internal")
    monkeypatch.setenv(deliver_module.SMTP_PASSWORD_ENV, "secret")
    monkeypatch.setenv(deliver_module.SMTP_SECURITY_ENV, "starttls")
    monkeypatch.delenv(deliver_module.SMTP_FROM_ENV, raising=False)
    monkeypatch.setattr(deliver_module, "_smtp_connect", _FakeSMTP)
    _FakeSMTP.instances.clear()


def test_email_delivery_sends_summary_with_result_attachments(
    tmp_path: Path, template_data, smtp_env: None
) -> None:
    template = _template(
        template_data,
        [
            {
                "type": "email",
                "target": "a@example.internal; b@example.internal",
                "enabled": True,
                "options": {"subject": "盘点 {date} {template_name}", "max_attachment_mb": 1},
            }
        ],
    )
    response = asyncio.run(
        Runner(_adapter(), tmp_path / "runs").run(template, {"date": "2026-09-01"})
    )
    assert response.ok, response.message
    channel = response.data["pipeline"]["stages"]["deliver"]["channels"][0]
    assert channel["ok"] is True, channel
    assert channel["recipients"] == ["a@example.internal", "b@example.internal"]
    assert set(channel["attached"]) >= {"report.md"} and channel["skipped"] == []

    smtp = _FakeSMTP.instances[0]
    assert (smtp.host, smtp.port, smtp.security) == ("smtp.example.internal", 2525, "starttls")
    assert smtp.logins == [("robot@example.internal", "secret")]
    message = message_from_bytes(smtp.sent[0], policy=default_policy)
    assert message["From"] == "robot@example.internal"
    assert message["Subject"].startswith("盘点 ") and "样机盘点反馈" in message["Subject"]
    body = message.get_body(preferencelist=("plain",)).get_content()
    assert "记录数：1" in body and "分析：ok" in body
    names = [part.get_filename() for part in message.iter_attachments()]
    assert "report.md" in names and any(name.endswith(".csv") for name in names)


def test_email_without_smtp_config_is_reported_not_raised(
    tmp_path: Path, template_data, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(deliver_module.SMTP_HOST_ENV, raising=False)
    template = _template(
        template_data, [{"type": "email", "target": "a@example.internal", "enabled": True}]
    )
    response = asyncio.run(Runner(_adapter(), tmp_path / "runs").run(template, {}))
    assert response.ok
    channel = response.data["pipeline"]["stages"]["deliver"]["channels"][0]
    assert channel["ok"] is False and "SMTP not configured" in channel["error"]


class _WeComRobot(BaseHTTPRequestHandler):
    messages: ClassVar[list[dict[str, Any]]] = []
    uploads: ClassVar[list[dict[str, Any]]] = []

    def log_message(self, *_args: Any) -> None:
        return

    def do_POST(self) -> None:
        parts = urlsplit(self.path)
        key = parse_qs(parts.query).get("key", [""])[0]
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        if key != "robot-key":
            self._reply({"errcode": 93000, "errmsg": "invalid webhook url"})
            return
        if parts.path.endswith("/upload_media"):
            content_type = self.headers.get("Content-Type", "")
            filename = raw.split(b'filename="', 1)[1].split(b'"', 1)[0].decode()
            _WeComRobot.uploads.append({"filename": filename, "content_type": content_type})
            self._reply({"errcode": 0, "media_id": "MEDIA-1"})
        else:
            _WeComRobot.messages.append(json.loads(raw))
            self._reply({"errcode": 0, "errmsg": "ok"})

    def _reply(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_wecom_delivery_posts_markdown_and_uploads_result_file(
    tmp_path: Path, template_data
) -> None:
    server = HTTPServer(("127.0.0.1", 0), _WeComRobot)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _WeComRobot.messages.clear()
    _WeComRobot.uploads.clear()
    base = f"http://127.0.0.1:{server.server_port}/cgi-bin/webhook/send"
    try:
        template = _template(
            template_data,
            [
                {
                    "type": "wecom",
                    "target": base + "?key=robot-key",
                    "enabled": True,
                    "options": {"mentioned_mobile_list": ["13800000000"]},
                },
                {"type": "wecom", "target": base + "?key=wrong", "enabled": True},
            ],
        )
        response = asyncio.run(Runner(_adapter(), tmp_path / "runs").run(template, {}))
    finally:
        server.shutdown()
        server.server_close()
    assert response.ok, response.message
    channels = response.data["pipeline"]["stages"]["deliver"]["channels"]
    assert channels[0]["ok"] is True and channels[0]["attached"][0].endswith(".csv")
    assert channels[1]["ok"] is False and "errcode 93000" in channels[1]["error"]

    markdown, file_message = _WeComRobot.messages[:2]
    assert markdown["msgtype"] == "markdown"
    assert "样机盘点反馈 运行结果" in markdown["markdown"]["content"]
    assert "记录数：1" in markdown["markdown"]["content"]
    assert markdown["markdown"]["mentioned_mobile_list"] == ["13800000000"]
    assert file_message == {"msgtype": "file", "file": {"media_id": "MEDIA-1"}}
    assert _WeComRobot.uploads[0]["filename"].endswith(".csv")
    assert _WeComRobot.uploads[0]["content_type"].startswith("multipart/form-data; boundary=")


def test_wecom_upload_url_derivation() -> None:
    assert (
        deliver_module._wecom_upload_url("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=K")
        == "https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media?key=K&type=file"
    )
    assert deliver_module._wecom_upload_url("https://example.internal/hook") is None
