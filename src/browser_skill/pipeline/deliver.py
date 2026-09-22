from __future__ import annotations

import json
import shutil
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from browser_skill.models import BrowserTemplate, DeliveryChannelSpec, RunContext

_WEBHOOK_TIMEOUT_SECONDS = 10


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
    }
    request = urllib.request.Request(
        channel.target,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_WEBHOOK_TIMEOUT_SECONDS) as response:  # noqa: S310
            status = int(getattr(response, "status", 200))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"type": "webhook", "ok": False, "target": channel.target, "error": str(exc)}
    return {"type": "webhook", "ok": 200 <= status < 300, "target": channel.target, "status": status}


def deliver(
    template: BrowserTemplate,
    context: RunContext,
    artifacts: dict[str, str],
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
            results.append(_deliver_webhook(channel, context, artifacts))
        else:
            results.append(
                {
                    "type": channel.type,
                    "ok": False,
                    "target": channel.target,
                    "placeholder": True,
                    "error": "Channel adapter not available in skill runtime",
                }
            )
    return {
        "delivered": any(item.get("ok") for item in results),
        "channels": results,
    }
