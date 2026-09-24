from __future__ import annotations

import json
from typing import Any

import pytest

from browser_skill.errors import SkillError
from browser_skill.interaction.variables import VariableResolver
from browser_skill.models import BrowserTemplate, RunMode
from browser_skill.runtime.url_batch import plan_batch_items, render_url_template


def _batch_template(template_data: dict[str, Any], **overrides: Any) -> BrowserTemplate:
    data = json.loads(json.dumps(template_data))
    data["schema_version"] = "2.0"
    data["system"]["url_template"] = "https://example.internal/orders/{order_no}/detail?tab=files"
    data["variables"] = {
        "order_no": {
            "type": "string",
            "required": True,
            "multiple": True,
            "prompt": "订单号",
            "validation": {"regex": r"ORD-\d{4}"},
        }
    }
    data["run"] = {"mode": "detail_batch", "driver_variable": "order_no"}
    data["target"]["fields"].append(
        {
            "key": "order_no",
            "name": "订单号",
            "type": "string",
            "required": True,
            "semantic": ["订单号"],
            "source": "detail",
        }
    )
    data["target"]["record_key"] = ["order_no"]
    for key, value in overrides.items():
        section, _, field = key.partition("__")
        if field:
            data[section][field] = value
        else:
            data[section] = value
    return BrowserTemplate.model_validate(data)


def test_legacy_template_defaults_to_list_mode(template_data: dict[str, Any]) -> None:
    template = BrowserTemplate.model_validate(template_data)
    assert template.run.mode == RunMode.LIST
    assert template.run.driver_variable is None
    assert template.system.url_template is None
    assert template.system.url_template_variables() == []


def test_batch_template_validates_and_lists_placeholders(template_data: dict[str, Any]) -> None:
    template = _batch_template(template_data)
    assert template.run.mode == RunMode.DETAIL_BATCH
    assert template.system.url_template_variables() == ["order_no"]


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"run": {"mode": "detail_batch"}}, "driver_variable"),
        ({"run": {"mode": "detail_batch", "driver_variable": "nope"}}, "unknown variable"),
        ({"run": {"mode": "list", "driver_variable": "order_no"}}, "only valid"),
    ],
)
def test_batch_template_rejects_bad_run_spec(
    template_data: dict[str, Any], patch: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _batch_template(template_data, **patch)


def test_url_template_host_must_be_allowed(template_data: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="allowed_hosts"):
        _batch_template(template_data, system__url_template="https://evil.example/{order_no}")


def test_url_template_placeholders_must_be_declared(template_data: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="undeclared"):
        _batch_template(
            template_data, system__url_template="https://example.internal/{order_no}/{tenant}"
        )


def test_driver_variable_requires_multiple(template_data: dict[str, Any]) -> None:
    variables = {
        "order_no": {"type": "string", "required": True, "prompt": "订单号"},
    }
    with pytest.raises(ValueError, match="multiple"):
        _batch_template(template_data, variables=variables)


def test_resolver_splits_multi_values_and_dedupes(template_data: dict[str, Any]) -> None:
    template = _batch_template(template_data)
    resolver = VariableResolver()
    resolved = resolver.resolve(template, {"order_no": "ORD-0001\nORD-0002, ORD-0001\n\n"})
    assert resolved["order_no"] == ["ORD-0001", "ORD-0002", "ORD-0001"]
    assert resolver.driver_values(template, resolved) == ["ORD-0001", "ORD-0002"]


def test_resolver_accepts_lists_and_enforces_pattern(template_data: dict[str, Any]) -> None:
    template = _batch_template(template_data)
    resolver = VariableResolver()
    resolved = resolver.resolve(template, {"order_no": ["ORD-0001", "ORD-0002"]})
    assert resolved["order_no"] == ["ORD-0001", "ORD-0002"]
    with pytest.raises(SkillError):
        resolver.resolve(template, {"order_no": ["not-an-order"]})


def test_resolver_lets_full_urls_bypass_regex(template_data: dict[str, Any]) -> None:
    template = _batch_template(template_data)
    resolved = VariableResolver().resolve(
        template, {"order_no": "https://example.internal/orders/123/detail"}
    )
    assert resolved["order_no"] == ["https://example.internal/orders/123/detail"]


def test_driver_values_respect_max_items(template_data: dict[str, Any]) -> None:
    template = _batch_template(
        template_data,
        run={"mode": "detail_batch", "driver_variable": "order_no", "max_items": 2},
    )
    resolver = VariableResolver()
    resolved = resolver.resolve(template, {"order_no": ["ORD-0001", "ORD-0002", "ORD-0003"]})
    with pytest.raises(SkillError, match="at most"):
        resolver.driver_values(template, resolved)


def test_render_url_template_encodes_values(template_data: dict[str, Any]) -> None:
    template = _batch_template(template_data)
    url = render_url_template(template, {"order_no": "ORD 0001/x"})
    assert url == "https://example.internal/orders/ORD%200001%2Fx/detail?tab=files"


def test_plan_batch_items_mixes_ids_and_full_urls(template_data: dict[str, Any]) -> None:
    template = _batch_template(template_data)
    items = plan_batch_items(
        template,
        {"order_no": ["ORD-0001", "https://example.internal/orders/999/detail"]},
        ["ORD-0001", "https://example.internal/orders/999/detail"],
    )
    assert [item.url for item in items] == [
        "https://example.internal/orders/ORD-0001/detail?tab=files",
        "https://example.internal/orders/999/detail",
    ]
    assert [item.index for item in items] == [0, 1]


def test_plan_batch_items_rejects_foreign_host_url(template_data: dict[str, Any]) -> None:
    template = _batch_template(template_data)
    with pytest.raises(SkillError, match="outside the template host scope"):
        plan_batch_items(template, {}, ["https://evil.example/orders/1"])


def test_plan_batch_items_can_forbid_full_urls(template_data: dict[str, Any]) -> None:
    template = _batch_template(
        template_data,
        run={"mode": "detail_batch", "driver_variable": "order_no", "accept_full_urls": False},
    )
    with pytest.raises(SkillError, match="does not accept full URLs"):
        plan_batch_items(template, {}, ["https://example.internal/orders/1"])
