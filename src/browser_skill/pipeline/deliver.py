from __future__ import annotations

from pathlib import Path
from typing import Any

from browser_skill.models import BrowserTemplate, DeliverySpec, RunContext


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
            results.append(
                {
                    "type": "local",
                    "workspace": context.workspace.as_posix(),
                    "artifacts": artifacts,
                }
            )
        else:
            results.append(
                {
                    "type": channel.type,
                    "target": channel.target,
                    "placeholder": True,
                    "message": "Channel adapter not configured in skill runtime",
                }
            )
    return {"delivered": bool(results), "channels": results}
