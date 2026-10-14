"""List-page search → detail navigation for detail_batch templates."""

from __future__ import annotations

from browser_skill.browser.base import BrowserAdapter
from browser_skill.errors import ErrorCode, SkillError
from browser_skill.models import BrowserSnapshot, BrowserTemplate
from browser_skill.runtime.locator import LocatorService
from browser_skill.runtime.policy import ActionPolicy
from browser_skill.runtime.url_batch import is_full_url


def list_navigation_active(template: BrowserTemplate, driver_value: str) -> bool:
    nav = template.run.list_navigation
    return bool(nav.enabled and not is_full_url(driver_value))


def snapshot_has_ref(snapshot: BrowserSnapshot, ref: str) -> bool:
    for element in snapshot.elements:
        el_ref = str(element.get("ref") or element.get("target") or "")
        if el_ref == ref:
            return True
    return False


async def resolve_navigation_target(
    adapter: BrowserAdapter,
    locator: LocatorService,
    snapshot: BrowserSnapshot,
    *,
    dom_ref: str | None,
    semantics: list[str],
    required: bool = True,
) -> str:
    if dom_ref and dom_ref.startswith("@e") and snapshot_has_ref(snapshot, dom_ref):
        return dom_ref
    located = await locator.locate(adapter, snapshot, semantics, required=required)
    assert located is not None
    return located.target


def detail_link_target(
    snapshot: BrowserSnapshot,
    driver_value: str,
    detail_semantics: list[str],
) -> str | None:
    """Pick a click target after list search: row value or a detail link on the same row."""
    needle = driver_value.strip()
    if not needle:
        return None
    folded = needle.casefold()
    detail_folded = [item.casefold() for item in detail_semantics if item.strip()]

    for element in snapshot.elements:
        href = str(element.get("href") or "")
        text = " ".join(
            str(element.get(key) or "") for key in ("text", "value", "aria_label", "title")
        )
        blob = f"{text} {href}".casefold()
        if folded not in blob:
            continue
        role = str(element.get("role") or "").casefold()
        if role in {"link", "button"} or href:
            ref = element.get("ref") or element.get("target")
            if ref:
                return str(ref)

    for element in snapshot.elements:
        text = " ".join(
            str(element.get(key) or "") for key in ("text", "value", "aria_label", "title")
        ).casefold()
        if not any(token in text for token in detail_folded):
            continue
        record_key = str(element.get("record_key") or "")
        if record_key and folded in record_key.casefold():
            ref = element.get("ref") or element.get("target")
            if ref:
                return str(ref)
        if folded in text:
            ref = element.get("ref") or element.get("target")
            if ref:
                return str(ref)

    return None


async def navigate_list_to_detail(
    adapter: BrowserAdapter,
    locator: LocatorService,
    template: BrowserTemplate,
    snapshot: BrowserSnapshot,
    driver_value: str,
    *,
    policy: ActionPolicy,
) -> BrowserSnapshot:
    nav = template.run.list_navigation
    if not nav.enabled:
        return snapshot

    input_target = await resolve_navigation_target(
        adapter,
        locator,
        snapshot,
        dom_ref=nav.search_input_ref,
        semantics=nav.search_input_semantic,
    )
    filled = await adapter.fill(input_target, driver_value)
    if not filled.ok:
        raise SkillError(
            ErrorCode.ELEMENT_NOT_FOUND,
            "无法在列表页填写搜索条件",
            stage="list_navigation",
            repairable=True,
        )

    action_target = await resolve_navigation_target(
        adapter,
        locator,
        snapshot,
        dom_ref=nav.search_action_ref,
        semantics=nav.search_action_semantic,
    )
    clicked = await adapter.click(action_target, observe=True)
    if not clicked.ok:
        raise SkillError(
            ErrorCode.ELEMENT_NOT_FOUND,
            "无法点击列表页的搜索/查询按钮",
            stage="list_navigation",
            repairable=True,
        )

    current = await adapter.snapshot(interactive=True)
    if current.url:
        policy.require_url_allowed(current.url, template)

    detail_target: str | None = None
    if nav.row_link_ref and snapshot_has_ref(current, nav.row_link_ref):
        detail_target = nav.row_link_ref
    if detail_target is None:
        detail_target = detail_link_target(current, driver_value, nav.row_link_semantic)
    if detail_target is None:
        detail_target = await resolve_navigation_target(
            adapter,
            locator,
            current,
            dom_ref=None,
            semantics=[f"{driver_value} {nav.row_link_semantic[0]}"],
        )

    opened = await adapter.click(detail_target, observe=True)
    if not opened.ok:
        raise SkillError(
            ErrorCode.NAVIGATION_FAILED,
            "搜索后无法打开详情页",
            stage="list_navigation",
            repairable=True,
        )

    detail = await adapter.snapshot(interactive=True)
    if detail.url:
        policy.require_url_allowed(detail.url, template)
    return detail
