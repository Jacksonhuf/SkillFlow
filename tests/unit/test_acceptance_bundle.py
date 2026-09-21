import json
from pathlib import Path

import pytest

from browser_skill.platform.acceptance import validate_acceptance_bundle


def test_rejects_missing_scenario() -> None:
    payload = {
        "schema_version": "1.0",
        "environment": {"platform_version": "p", "plugin_version": "c"},
        "capability_probe": {
            "ready": True,
            "status_ok": True,
            "missing_capability_flags": [],
            "missing_operations": [],
        },
        "scenarios": [{"id": "menu_and_variables", "passed": True}],
    }
    path = Path("bundle.json")
    path.write_text(json.dumps(payload), encoding="utf-8")
    try:
        result = validate_acceptance_bundle(path)
        assert result.ok is False
        assert any("missing required scenario" in error for error in result.errors)
    finally:
        path.unlink(missing_ok=True)


@pytest.mark.parametrize(
    "fixture_name",
    ["sample-acceptance-bundle.json"],
)
def test_fixture_bundles_validate(fixture_name: str) -> None:
    bundle = Path(__file__).resolve().parents[2] / "fixtures" / "platform" / fixture_name
    result = validate_acceptance_bundle(bundle)
    assert result.ok is True
