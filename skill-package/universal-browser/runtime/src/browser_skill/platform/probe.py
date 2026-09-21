from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from browser_skill.browser.base import BrowserAdapter
from browser_skill.models import BrowserCapabilities, StrictModel


class PlatformProbeReport(StrictModel):
    ready: bool
    status_ok: bool
    capabilities: BrowserCapabilities
    missing_capability_flags: list[str]
    missing_operations: list[str]
    missing_recommended_flags: list[str]
    platform_version: str | None = None
    plugin_version: str | None = None
    text: str


def default_contract_path() -> Path:
    return Path(__file__).resolve().parents[3] / "fixtures" / "platform" / "minimum-contract.json"


def load_minimum_contract(path: Path | None = None) -> dict[str, Any]:
    contract_path = path or default_contract_path()
    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Platform contract fixture must be a JSON object")
    return payload


async def _capabilities_payload(adapter: BrowserAdapter) -> dict[str, Any]:
    payload_fn = getattr(adapter, "capabilities_payload", None)
    if callable(payload_fn):
        raw = await payload_fn()
        return raw if isinstance(raw, dict) else {}
    capabilities = await adapter.capabilities()
    return capabilities.model_dump(mode="json")


async def probe_adapter(
    adapter: BrowserAdapter,
    *,
    contract_path: Path | None = None,
    mode: Literal["platform_tool", "local_cli"] = "platform_tool",
) -> PlatformProbeReport:
    contract = load_minimum_contract(contract_path)
    required_flags = list(contract.get("required_capability_flags", []))
    recommended_flags = list(contract.get("recommended_capability_flags", []))
    required_operations = list(contract.get("required_operations", []))

    status = await adapter.status()
    capabilities = await adapter.capabilities()
    payload = await _capabilities_payload(adapter)

    missing_flags = [
        name for name in required_flags if not bool(getattr(capabilities, name, False))
    ]
    missing_recommended = [
        name for name in recommended_flags if not bool(getattr(capabilities, name, False))
    ]

    operations_raw = payload.get("operations")
    operations = operations_raw if isinstance(operations_raw, dict) else None
    if mode == "platform_tool":
        if operations is None:
            missing_operations = list(required_operations)
        else:
            missing_operations = [
                name for name in required_operations if not bool(operations.get(name))
            ]
    else:
        missing_operations = []

    platform_version = payload.get("platform_version")
    plugin_version = payload.get("plugin_version")
    if not isinstance(platform_version, str):
        platform_version = None
    if not isinstance(plugin_version, str):
        plugin_version = None

    ready = status.ok and not missing_flags and not missing_operations
    lines = [
        "Platform chrome-use contract probe:",
        f"status_ok={'yes' if status.ok else 'no'}",
    ]
    if missing_flags:
        lines.append(f"missing capability flags: {', '.join(missing_flags)}")
    if missing_operations:
        lines.append(f"missing operations: {', '.join(missing_operations)}")
    if missing_recommended:
        lines.append(f"recommended flags absent: {', '.join(missing_recommended)}")
    if ready:
        lines.append("result: ready for internal acceptance scenarios.")
    else:
        lines.append("result: not ready; fix the platform plugin contract before release.")

    return PlatformProbeReport(
        ready=ready,
        status_ok=status.ok,
        capabilities=capabilities,
        missing_capability_flags=missing_flags,
        missing_operations=missing_operations,
        missing_recommended_flags=missing_recommended,
        platform_version=platform_version,
        plugin_version=plugin_version,
        text="\n".join(lines),
    )
