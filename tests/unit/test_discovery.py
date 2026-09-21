from browser_skill.models import BrowserSnapshot
from browser_skill.runtime.discovery import MappingDiscoveryService


def test_discovers_semantic_mappings_without_persisting_refs(template) -> None:
    snapshot = BrowserSnapshot(
        url="https://example.internal/home",
        title="盘点反馈",
        text="退出登录",
        elements=[
            {"ref": "@e1", "role": "columnheader", "text": "样机ID"},
            {"ref": "@e2", "role": "columnheader", "aria_label": "序列号"},
        ],
    )
    report = MappingDiscoveryService().discover(template, snapshot)
    assert report.publishable_candidate is True
    assert set(report.matched_fields) == {"sample_id", "sn"}
    dumped = report.learned.model_dump_json()
    assert "@e1" not in dumped
    assert "@e2" not in dumped
    assert report.learned.page_hints == []


def test_reports_missing_required_targets_without_inventing_mapping(template) -> None:
    snapshot = BrowserSnapshot(
        url="https://example.internal/home",
        text="退出登录",
        elements=[{"text": "SN"}],
    )
    report = MappingDiscoveryService().discover(template, snapshot)
    assert report.publishable_candidate is False
    assert report.missing_required_fields == ["sample_id"]
    assert "sample_id" not in report.learned.field_mappings
