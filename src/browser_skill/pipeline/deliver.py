"""Deliver stage: hand the finished business package to people and systems.

Channels: ``local`` (copy into a shared folder), ``webhook`` (JSON POST), ``email`` (SMTP with the
result files attached) and ``wecom`` (企业微信群机器人: markdown summary plus the result file).
Every channel returns a small dict and never raises; delivery problems are reported in
``pipeline.json`` but do not fail the run.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import smtplib
import ssl
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit, urlunsplit

from browser_skill.models import BrowserTemplate, DeliveryChannelSpec, DownloadStatus, RunContext

_WEBHOOK_TIMEOUT_SECONDS = 10
_UPLOAD_TIMEOUT_SECONDS = 60
_DEFAULT_MAX_ATTACHMENT_MB = 20
_WECOM_MAX_FILE_MB = 20
_RESULT_ARTIFACTS = ("xlsx", "csv", "json", "report")

SMTP_HOST_ENV = "UNIVERSAL_BROWSER_SMTP_HOST"
SMTP_PORT_ENV = "UNIVERSAL_BROWSER_SMTP_PORT"
SMTP_USER_ENV = "UNIVERSAL_BROWSER_SMTP_USER"
SMTP_PASSWORD_ENV = "UNIVERSAL_BROWSER_SMTP_PASSWORD"
SMTP_FROM_ENV = "UNIVERSAL_BROWSER_SMTP_FROM"
SMTP_SECURITY_ENV = "UNIVERSAL_BROWSER_SMTP_SECURITY"  # starttls (default) | ssl | none


# --------------------------------------------------------------------------- shared helpers


def _summary_lines(
    context: RunContext, analysis: dict[str, Any] | None, *, max_findings: int = 5
) -> list[str]:
    ok_files = sum(item.status == DownloadStatus.OK for item in context.downloaded_files)
    lines = [
        f"模板：{context.template_snapshot.name}（{context.template_id}@{context.template_version}）",
        f"运行：{context.run_id}",
        f"状态：{context.state.value}",
        f"记录数：{len(context.records)}，附件：{ok_files}/{len(context.downloaded_files)}",
    ]
    if context.variables:
        lines.append("变量：" + "，".join(f"{k}={v}" for k, v in context.variables.items()))
    if analysis and not analysis.get("skipped"):
        lines.append(f"分析：{analysis.get('severity', 'ok')}")
        text = str(analysis.get("ai_summary") or analysis.get("summary") or "").strip()
        if text:
            lines.extend(text.splitlines()[:max_findings])
    return lines


def _artifact_files(context: RunContext, artifacts: dict[str, str]) -> list[tuple[str, Path]]:
    files: list[tuple[str, Path]] = []
    root = context.workspace.resolve()
    for name in _RESULT_ARTIFACTS:
        relative = artifacts.get(name)
        if not relative:
            continue
        path = (context.workspace / relative).resolve()
        if path.is_file() and root in path.parents:
            files.append((name, path))
    return files


def _render(pattern: str, context: RunContext) -> str:
    text = pattern.replace("{template_id}", context.template_id)
    text = text.replace("{template_name}", context.template_snapshot.name)
    text = text.replace("{run_id}", context.run_id)
    text = text.replace("{date}", datetime.now(UTC).strftime("%Y-%m-%d"))
    for key, value in context.variables.items():
        text = text.replace("{" + key + "}", str(value))
    return text


def _post_json(url: str, payload: dict[str, Any], *, timeout: float) -> tuple[int, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        status = int(getattr(response, "status", 200))
        raw = response.read()
    body: Any = None
    if raw:
        try:
            body = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            body = raw.decode("utf-8", errors="replace")[:500]
    return status, body


# --------------------------------------------------------------------------- local / webhook


def _deliver_local(
    channel: DeliveryChannelSpec,
    context: RunContext,
    artifacts: dict[str, str],
) -> dict[str, Any]:
    if not channel.target:
        return {"type": "local", "ok": False, "error": "target directory is empty"}
    destination = Path(channel.target).expanduser() / context.run_id
    copied: list[str] = []
    try:
        destination.mkdir(parents=True, exist_ok=True)
        for name, relative in artifacts.items():
            source = (context.workspace / relative).resolve()
            if not source.is_file() or context.workspace.resolve() not in source.parents:
                continue
            shutil.copy2(source, destination / Path(relative).name)
            copied.append(name)
        attachments_dir = context.workspace / context.template_snapshot.output.attachments_dir
        if attachments_dir.is_dir():
            shutil.copytree(
                attachments_dir,
                destination / attachments_dir.name,
                dirs_exist_ok=True,
            )
            copied.append("attachments")
    except OSError as exc:
        return {"type": "local", "ok": False, "target": str(destination), "error": str(exc)}
    return {"type": "local", "ok": True, "target": str(destination), "copied": copied}


def _deliver_webhook(
    channel: DeliveryChannelSpec,
    context: RunContext,
    artifacts: dict[str, str],
    analysis: dict[str, Any] | None,
) -> dict[str, Any]:
    if not channel.target.startswith(("http://", "https://")):
        return {"type": "webhook", "ok": False, "error": "target must be an http(s) URL"}
    payload = {
        "event": "run_finished",
        "run_id": context.run_id,
        "template": f"{context.template_id}@{context.template_version}",
        "state": context.state.value,
        "record_count": len(context.records),
        "download_count": sum(item.status == "ok" for item in context.downloaded_files),
        "artifacts": artifacts,
        "workspace": context.workspace.as_posix(),
        "analysis": analysis,
    }
    try:
        status, _body = _post_json(channel.target, payload, timeout=_WEBHOOK_TIMEOUT_SECONDS)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"type": "webhook", "ok": False, "target": channel.target, "error": str(exc)}
    return {
        "type": "webhook",
        "ok": 200 <= status < 300,
        "target": channel.target,
        "status": status,
    }


# --------------------------------------------------------------------------- email

SmtpConnect = Callable[[str, int, str], smtplib.SMTP]


def _smtp_connect(host: str, port: int, security: str) -> smtplib.SMTP:
    if security == "ssl":
        return smtplib.SMTP_SSL(host, port, timeout=30, context=ssl.create_default_context())
    client = smtplib.SMTP(host, port, timeout=30)
    if security == "starttls":
        client.starttls(context=ssl.create_default_context())
    return client


def _smtp_settings() -> dict[str, Any] | None:
    host = os.environ.get(SMTP_HOST_ENV, "").strip()
    if not host:
        return None
    security = os.environ.get(SMTP_SECURITY_ENV, "starttls").strip().casefold() or "starttls"
    default_port = 465 if security == "ssl" else 587
    try:
        port = int(os.environ.get(SMTP_PORT_ENV, "") or default_port)
    except ValueError:
        port = default_port
    user = os.environ.get(SMTP_USER_ENV, "").strip()
    return {
        "host": host,
        "port": port,
        "security": security,
        "user": user,
        "password": os.environ.get(SMTP_PASSWORD_ENV, ""),
        "sender": os.environ.get(SMTP_FROM_ENV, "").strip() or user,
    }


def _recipients(target: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,;，；\s]+", target) if item.strip()]


def _deliver_email(
    channel: DeliveryChannelSpec,
    context: RunContext,
    artifacts: dict[str, str],
    analysis: dict[str, Any] | None,
    *,
    connect: SmtpConnect | None = None,
) -> dict[str, Any]:
    connect = connect or _smtp_connect  # resolved at call time so hosts/tests can swap it
    recipients = _recipients(channel.target)
    if not recipients:
        return {"type": "email", "ok": False, "error": "target must list recipient addresses"}
    settings = _smtp_settings()
    if settings is None:
        return {
            "type": "email",
            "ok": False,
            "target": channel.target,
            "error": f"SMTP not configured (set {SMTP_HOST_ENV} and related variables)",
        }
    if not settings["sender"]:
        return {"type": "email", "ok": False, "target": channel.target, "error": "no sender"}
    subject_pattern = str(channel.options.get("subject") or "{template_name} {date} 运行结果")
    message = EmailMessage()
    message["Subject"] = _render(subject_pattern, context)
    message["From"] = settings["sender"]
    message["To"] = ", ".join(recipients)
    message.set_content("\n".join(_summary_lines(context, analysis)) + "\n")
    attached: list[str] = []
    skipped: list[str] = []
    if bool(channel.options.get("attach", True)):
        limit = float(channel.options.get("max_attachment_mb", _DEFAULT_MAX_ATTACHMENT_MB))
        budget = int(limit * 1024 * 1024)
        for _name, path in _artifact_files(context, artifacts):
            size = path.stat().st_size
            if size > budget:
                skipped.append(path.name)
                continue
            budget -= size
            mime, _ = mimetypes.guess_type(path.name)
            maintype, subtype = (mime or "application/octet-stream").split("/", 1)
            message.add_attachment(
                path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name
            )
            attached.append(path.name)
    try:
        with connect(settings["host"], settings["port"], settings["security"]) as client:
            if settings["user"]:
                client.login(settings["user"], settings["password"])
            client.send_message(message)
    except (smtplib.SMTPException, OSError, ValueError) as exc:
        return {
            "type": "email",
            "ok": False,
            "target": channel.target,
            "error": f"{type(exc).__name__}: {exc}"[:500],
        }
    return {
        "type": "email",
        "ok": True,
        "target": channel.target,
        "recipients": recipients,
        "subject": str(message["Subject"]),
        "attached": attached,
        "skipped": skipped,
    }


# --------------------------------------------------------------------------- 企业微信 (WeCom)


def _wecom_upload_url(send_url: str) -> str | None:
    parts = urlsplit(send_url)
    key = parse_qs(parts.query).get("key", [""])[0]
    if not key or not parts.path.endswith("/send"):
        return None
    path = parts.path[: -len("/send")] + "/upload_media"
    return urlunsplit((parts.scheme, parts.netloc, path, f"key={key}&type=file", ""))


def _multipart(field: str, filename: str, payload: bytes) -> tuple[bytes, str]:
    boundary = f"----UniversalBrowser{uuid.uuid4().hex}"
    mime, _ = mimetypes.guess_type(filename)
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field}"; filename="{filename}"; '
        f"filelength={len(payload)}\r\n"
        f"Content-Type: {mime or 'application/octet-stream'}\r\n\r\n"
    ).encode()
    body = head + payload + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def _wecom_upload(upload_url: str, path: Path) -> str:
    body, content_type = _multipart("media", path.name, path.read_bytes())
    request = urllib.request.Request(
        upload_url, data=body, headers={"Content-Type": content_type}, method="POST"
    )
    with urllib.request.urlopen(request, timeout=_UPLOAD_TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    if not isinstance(payload, dict) or payload.get("errcode", 0) != 0:
        raise ValueError(f"upload_media failed: {payload}")
    return str(payload["media_id"])


def _deliver_wecom(
    channel: DeliveryChannelSpec,
    context: RunContext,
    artifacts: dict[str, str],
    analysis: dict[str, Any] | None,
) -> dict[str, Any]:
    if not channel.target.startswith(("http://", "https://")):
        return {"type": "wecom", "ok": False, "error": "target must be the robot webhook URL"}
    title_pattern = str(channel.options.get("title") or "{template_name} 运行结果")
    severity = str((analysis or {}).get("severity", "ok")) if analysis else "ok"
    colour = {"ok": "info", "info": "info", "warning": "warning", "error": "warning"}[
        severity if severity in {"ok", "info", "warning", "error"} else "ok"
    ]
    lines = [f"### {_render(title_pattern, context)}"]
    for index, line in enumerate(_summary_lines(context, analysis)):
        # Line 3 is the record/attachment count: colour it by analysis severity.
        lines.append(f'> <font color="{colour}">{line}</font>' if index == 3 else f"> {line}")
    mentions = channel.options.get("mentioned_mobile_list") or []
    payload: dict[str, Any] = {
        "msgtype": "markdown",
        "markdown": {"content": "\n".join(lines)[:4000]},
    }
    if mentions:
        payload["markdown"]["mentioned_mobile_list"] = [str(item) for item in mentions]
    result: dict[str, Any] = {"type": "wecom", "target": channel.target}
    try:
        status, body = _post_json(channel.target, payload, timeout=_WEBHOOK_TIMEOUT_SECONDS)
        errcode = body.get("errcode", 0) if isinstance(body, dict) else 0
        result["ok"] = 200 <= status < 300 and errcode == 0
        if not result["ok"]:
            result["error"] = f"status {status}, errcode {errcode}"
            return result
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {**result, "ok": False, "error": str(exc)[:500]}
    if not bool(channel.options.get("attach_result", True)):
        return result
    upload_url = _wecom_upload_url(channel.target)
    files = [
        (name, path)
        for name, path in _artifact_files(context, artifacts)
        if name in {"xlsx", "csv"} and path.stat().st_size <= _WECOM_MAX_FILE_MB * 1024 * 1024
    ]
    if upload_url is None or not files:
        result["attached"] = []
        return result
    _name, path = files[0]
    try:
        media_id = _wecom_upload(upload_url, path)
        status, body = _post_json(
            channel.target,
            {"msgtype": "file", "file": {"media_id": media_id}},
            timeout=_WEBHOOK_TIMEOUT_SECONDS,
        )
        errcode = body.get("errcode", 0) if isinstance(body, dict) else 0
        if 200 <= status < 300 and errcode == 0:
            result["attached"] = [path.name]
        else:
            result["attached"] = []
            result["attachment_error"] = f"status {status}, errcode {errcode}"
    except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
        result["attached"] = []
        result["attachment_error"] = str(exc)[:500]
    return result


# --------------------------------------------------------------------------- entry point


def deliver(
    template: BrowserTemplate,
    context: RunContext,
    artifacts: dict[str, str],
    *,
    analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    spec = template.delivery
    if not spec.enabled:
        return {"delivered": False, "reason": "delivery disabled"}
    results: list[dict[str, Any]] = []
    for channel in spec.channels:
        if not channel.enabled:
            continue
        if channel.type == "local":
            results.append(_deliver_local(channel, context, artifacts))
        elif channel.type == "webhook":
            results.append(_deliver_webhook(channel, context, artifacts, analysis))
        elif channel.type == "email":
            results.append(_deliver_email(channel, context, artifacts, analysis))
        elif channel.type == "wecom":
            results.append(_deliver_wecom(channel, context, artifacts, analysis))
        else:  # pragma: no cover - the model restricts the literal
            results.append(
                {
                    "type": channel.type,
                    "ok": False,
                    "target": channel.target,
                    "error": "Channel adapter not available in skill runtime",
                }
            )
    return {
        "delivered": any(item.get("ok") for item in results),
        "channels": results,
    }
