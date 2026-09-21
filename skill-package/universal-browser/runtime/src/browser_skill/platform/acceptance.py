from __future__ import annotations

import json
from pathlib import Path

from browser_skill.models import StrictModel
from browser_skill.platform.probe import load_minimum_contract


class AcceptanceValidationResult(StrictModel):
    ok: bool
    errors: list[str]
    warnings: list[str]
    text: str


def validate_acceptance_bundle(
    path: Path,
    *,
    contract_path: Path | None = None,
    require_sign_off: bool = False,
) -> AcceptanceValidationResult:
    contract = load_minimum_contract(contract_path)
    required_scenarios = list(contract.get("required_acceptance_scenarios", []))
    errors: list[str] = []
    warnings: list[str] = []

    if not path.exists() or not path.is_file():
        return AcceptanceValidationResult(
            ok=False,
            errors=[f"Evidence bundle not found: {path}"],
            warnings=[],
            text="Acceptance bundle validation failed: file missing.",
        )

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return AcceptanceValidationResult(
            ok=False,
            errors=[f"Invalid JSON: {exc}"],
            warnings=[],
            text="Acceptance bundle validation failed: invalid JSON.",
        )

    if not isinstance(payload, dict):
        errors.append("Evidence bundle root must be a JSON object.")
        payload = {}

    if payload.get("schema_version") != "1.0":
        errors.append("schema_version must be '1.0'.")

    environment = payload.get("environment")
    if not isinstance(environment, dict):
        errors.append("environment object is required.")
        environment = {}

    for key in ("platform_version", "plugin_version"):
        value = environment.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"environment.{key} must be a non-empty string.")

    probe = payload.get("capability_probe")
    if not isinstance(probe, dict):
        errors.append("capability_probe object is required.")
        probe = {}

    if probe.get("ready") is not True:
        errors.append("capability_probe.ready must be true for release sign-off evidence.")
    if probe.get("status_ok") is not True:
        errors.append("capability_probe.status_ok must be true.")
    for field in ("missing_capability_flags", "missing_operations"):
        value = probe.get(field)
        if not isinstance(value, list) or value:
            errors.append(f"capability_probe.{field} must be an empty list when ready.")

    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, list):
        errors.append("scenarios must be a list.")
        scenarios = []

    seen: set[str] = set()
    for index, item in enumerate(scenarios):
        if not isinstance(item, dict):
            errors.append(f"scenarios[{index}] must be an object.")
            continue
        scenario_id = item.get("id")
        if not isinstance(scenario_id, str) or not scenario_id:
            errors.append(f"scenarios[{index}].id must be a non-empty string.")
            continue
        if scenario_id in seen:
            errors.append(f"duplicate scenario id: {scenario_id}")
        seen.add(scenario_id)
        if item.get("passed") is not True:
            errors.append(f"scenario {scenario_id} must have passed=true.")

    for scenario_id in required_scenarios:
        if scenario_id not in seen:
            errors.append(f"missing required scenario: {scenario_id}")

    sign_off = payload.get("sign_off")
    if require_sign_off:
        if not isinstance(sign_off, dict):
            errors.append("sign_off object is required when require_sign_off=true.")
        else:
            if sign_off.get("approved") is not True:
                errors.append("sign_off.approved must be true.")
            for key in ("reviewer", "date"):
                value = sign_off.get(key)
                if not isinstance(value, str) or not value.strip():
                    errors.append(f"sign_off.{key} must be a non-empty string.")
    elif isinstance(sign_off, dict) and sign_off.get("approved") is True:
        for key in ("reviewer", "date"):
            value = sign_off.get(key)
            if not isinstance(value, str) or not value.strip():
                warnings.append(f"sign_off.{key} should be set when approved=true.")

    ok = not errors
    if ok:
        text = (
            "Acceptance evidence bundle is structurally valid and covers all required scenarios. "
            "This validates documentation only; it does not replace authorized "
            "real-browser testing."
        )
    else:
        text = "Acceptance evidence bundle validation failed:\n- " + "\n- ".join(errors)

    return AcceptanceValidationResult(ok=ok, errors=errors, warnings=warnings, text=text)
