from __future__ import annotations

from browser_skill.models import BrowserSnapshot, ProbeWorkflowCandidate
from browser_skill.runtime.site_profiles import (
    augment_workflow_candidates,
    profile_for_host,
    profile_warnings,
)


def test_profile_for_huawei_host() -> None:
    assert profile_for_host("efinance.huawei.com") is not None
    warnings = profile_warnings("portal.huawei.com")
    assert warnings and "华为" in warnings[0]


def test_augment_workflow_adds_site_hint_when_text_present() -> None:
    snapshot = BrowserSnapshot(text="订单详情 附件管理 展开")
    candidates = augment_workflow_candidates("efinance.huawei.com", snapshot, [])
    targets = {item.target for item in candidates}
    assert "附件管理" in targets
    assert all(isinstance(item, ProbeWorkflowCandidate) for item in candidates)
