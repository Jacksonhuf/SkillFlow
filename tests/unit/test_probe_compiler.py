from __future__ import annotations

from typing import Any

import pytest

from browser_skill.errors import SkillError
from browser_skill.models import (
    AcquisitionSource,
    ProbeAttachmentCandidate,
    ProbeDraftInput,
    ProbeFieldCandidate,
    RunMode,
    TemplateStatus,
)
from browser_skill.runtime.probe_compiler import ProbeDraftCompiler

SAMPLE_URL = "https://portal.example.com/orders/ORD-2024-0917/detail?tab=files"


def _draft(**overrides: Any) -> ProbeDraftInput:
    data: dict[str, Any] = {
        "template_id": "order_files",
        "name": "订单附件下载",
        "sample_url": SAMPLE_URL,
        "url_template": "https://portal.example.com/orders/{order_no}/detail?tab=files",
        "driver_variable": "order_no",
        "fields": [
            {
                "key": "order_no",
                "name": "订单号",
                "sample": "ORD-2024-0917",
                "source": "url",
                "strategy": "semantic",
            },
            {
                "key": "customer_name",
                "name": "客户名称",
                "sample": "张三贸易",
                "source": "network",
                "strategy": "semantic",
                "confidence": 0.95,
                "endpoint_hint": "/api/orders/{order_no}",
                "json_path": "$.data.customerName",
                "aliases": ["customer_name"],
            },
            {
                "key": "amount",
                "name": "金额",
                "sample": "1200.00",
                "source": "dom",
                "type": "number",
                "confidence": 0.9,
            },
        ],
        "attachments": [
            {"key": "invoice", "name": "发票", "count": 2, "types": ["pdf", "jpg"]},
        ],
    }
    data.update(overrides)
    return ProbeDraftInput.model_validate(data)


def test_compile_produces_valid_detail_batch_draft() -> None:
    template = ProbeDraftCompiler().compile(_draft(), version=1)

    assert template.schema_version == "2.0"
    assert template.status == TemplateStatus.DRAFT
    assert template.run.mode == RunMode.DETAIL_BATCH
    assert template.run.driver_variable == "order_no"
    assert template.system.allowed_hosts == ["portal.example.com"]
    assert template.system.url_template_variables() == ["order_no"]
    assert template.variables["order_no"].multiple is True
    assert template.variables["order_no"].required is True
    assert template.target.record_key == ["order_no"]
    keys = [field.key for field in template.target.fields]
    assert keys == ["order_no", "customer_name", "amount"]
    by_key = {field.key: field for field in template.target.fields}
    assert by_key["order_no"].required is True
    assert by_key["amount"].required is False
    assert by_key["customer_name"].semantic == ["客户名称", "customer_name"]
    assert all(field.source == "detail" for field in template.target.fields)
    mapping = template.learned.field_mappings["customer_name"]
    assert mapping.preferred_source == AcquisitionSource.NETWORK
    assert mapping.endpoint_hint == "/api/orders/{order_no}"
    assert mapping.json_path == "$.data.customerName"
    assert template.learned.field_mappings["amount"].strategy == "label_value"
    assert "order_no" not in template.learned.field_mappings
    attachment = template.target.attachments[0]
    assert attachment.filename_pattern == "{order_no}_{original_name}"
    assert attachment.multiple is True
    assert attachment.file_types == ["pdf", "jpg"]
    assert attachment.destination_subdir == "attachments/invoice"
    assert template.learned.attachment_mappings["invoice"].hints == ["发票"]
    assert template.output.columns == keys
    assert template.output.filename_pattern == "order_files"
    # login check accepts either the logout marker or landing on the detail section
    assert any(signal.url_contains == "/orders" for signal in template.auth.login_check.any)


def test_driver_field_is_added_when_not_ticked() -> None:
    draft = _draft(
        fields=[
            {"key": "amount", "name": "金额", "sample": "1", "source": "dom"},
        ],
        driver_prompt="订单号",
    )

    template = ProbeDraftCompiler().compile(draft, version=1)

    assert [field.key for field in template.target.fields] == ["order_no", "amount"]
    assert template.target.fields[0].name == "订单号"
    assert template.variables["order_no"].prompt == "订单号"


def test_required_keys_and_run_overrides_are_applied() -> None:
    draft = _draft(
        required_keys=["customer_name"],
        run={
            "per_item_delay_ms": 0,
            "on_item_error": "stop",
            "capture_tables": True,
            "mode": "list",
        },
        driver_regex=r"ORD-\d{4}-\d{4}",
    )

    template = ProbeDraftCompiler().compile(draft, version=3)

    assert template.version == 3
    by_key = {field.key: field for field in template.target.fields}
    assert by_key["customer_name"].required is True
    assert template.run.mode == RunMode.DETAIL_BATCH  # mode cannot be overridden
    assert template.run.on_item_error == "stop"
    assert template.run.capture_tables is True
    assert template.run.per_item_delay_ms == 0
    assert template.variables["order_no"].validation is not None
    assert template.variables["order_no"].validation.regex == r"ORD-\d{4}-\d{4}"


def test_missing_url_template_means_full_urls_only() -> None:
    template = ProbeDraftCompiler().compile(_draft(url_template=None), version=1)

    assert template.system.url_template is None
    assert template.run.accept_full_urls is True


def test_url_template_without_driver_placeholder_is_rejected() -> None:
    with pytest.raises(SkillError) as raised:
        ProbeDraftCompiler().compile(
            _draft(url_template="https://portal.example.com/orders/{other}"), version=1
        )

    assert raised.value.code.value == "E_TEMPLATE_INVALID"


def test_record_key_must_reference_selected_fields() -> None:
    with pytest.raises(SkillError):
        ProbeDraftCompiler().compile(_draft(record_key=["missing"]), version=1)


def test_duplicate_candidate_keys_are_collapsed() -> None:
    draft = _draft(
        fields=[
            ProbeFieldCandidate(key="amount", name="金额", sample="1", source="dom"),
            ProbeFieldCandidate(key="amount", name="金额2", sample="2", source="dom"),
        ],
        attachments=[ProbeAttachmentCandidate(key="contract", name="合同")],
    )

    template = ProbeDraftCompiler().compile(draft, version=1)

    assert [field.key for field in template.target.fields] == ["order_no", "amount"]
    assert template.target.attachments[0].multiple is False
