"""Optional host-specific hints for probe / attachment workflow (no runtime fork)."""

from __future__ import annotations

from dataclasses import dataclass

from browser_skill.models import BrowserSnapshot, ProbeWorkflowCandidate


@dataclass(frozen=True, slots=True)
class SiteProfile:
    host_suffix: str
    attachment_expand_hints: tuple[str, ...]
    extra_warnings: tuple[str, ...]


_PROFILES: tuple[SiteProfile, ...] = (
    SiteProfile(
        "huawei.com",
        ("附件", "附件管理", "展开", "查看更多", "下载列表"),
        (
            "华为类门户常在折叠区或 Tab 中放附件；请使用「运行前点击」录制或手动添加展开步骤。",
        ),
    ),
    SiteProfile(
        "efinance.",
        ("附件", "凭证", "展开", "下载"),
        ("财务类详情页附件可能需要先展开折叠面板，再重新探测或录制点击步骤。",),
    ),
)


def profile_for_host(host: str) -> SiteProfile | None:
    folded = (host or "").casefold().strip()
    if not folded:
        return None
    for item in _PROFILES:
        suffix = item.host_suffix.casefold()
        if folded.endswith(suffix) or suffix in folded:
            return item
    return None


def profile_warnings(host: str) -> list[str]:
    profile = profile_for_host(host)
    if profile is None:
        return []
    return list(profile.extra_warnings)


def augment_workflow_candidates(
    host: str,
    snapshot: BrowserSnapshot,
    candidates: list[ProbeWorkflowCandidate],
) -> list[ProbeWorkflowCandidate]:
    profile = profile_for_host(host)
    if profile is None:
        return candidates
    haystack = snapshot.text.casefold()
    seen = {item.target.casefold() for item in candidates}
    out = list(candidates)
    for hint in profile.attachment_expand_hints:
        folded = hint.casefold()
        if folded not in haystack or folded in seen:
            continue
        seen.add(folded)
        out.append(
            ProbeWorkflowCandidate(
                target=hint,
                phase="attachments",
                reason="站点常见附件区入口（建议勾选）",
                recommended=True,
            )
        )
    out.sort(key=lambda item: (not item.recommended, item.target))
    return out[:15]
