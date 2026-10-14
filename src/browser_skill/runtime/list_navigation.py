"""List-page search → detail navigation for detail_batch templates."""

from __future__ import annotations

from typing import Any

from browser_skill.browser.base import BrowserAdapter
from browser_skill.errors import ErrorCode, SkillError
from browser_skill.models import BrowserSnapshot, BrowserTemplate
from browser_skill.runtime.locator import LocatorService
from browser_skill.runtime.policy import ActionPolicy
from browser_skill.runtime.url_batch import is_full_url


def list_navigation_active(template: BrowserTemplate, driver_value: str) -> bool:
    nav = template.run.list_navigation
    return bool(nav.enabled and not is_full_url(driver_value))


def _frame_matches(element: dict[str, Any], frame_index: int | None) -> bool:
    if frame_index is None:
        return True
    el_frame = element.get("frame_index")
    if el_frame in (None, 0) and frame_index == 0:
        return True
    return el_frame == frame_index


def snapshot_has_ref(
    snapshot: BrowserSnapshot,
    ref: str,
    *,
    frame_index: int | None = None,
) -> bool:
    for element in snapshot.elements:
        el_ref = str(element.get("ref") or element.get("target") or "")
        if el_ref == ref and _frame_matches(element, frame_index):
            return True
    return False


def _label_matches(display: str, sample: str) -> bool:
    if not display or not sample:
        return False
    left, right = display.strip(), sample.strip()
    if left == right:
        return True
    return len(right) >= 4 and (left.startswith(right) or right.startswith(left))


def reconcile_list_nav_steps_with_snapshot(
    steps: list[dict[str, Any]],
    snapshot: BrowserSnapshot,
) -> tuple[list[dict[str, Any]], int]:
    """Update step ``ref`` when a fresh snapshot maps the same label to a new @eN."""
    realigned = 0
    out: list[dict[str, Any]] = []
    for step in steps:
        updated = dict(step)
        label = str(updated.get("label") or "").strip()
        old_ref = str(updated.get("ref") or "").strip()
        frame_raw = updated.get("frame_index")
        frame = frame_raw if isinstance(frame_raw, int) and frame_raw >= 0 else None
        if label:
            new_ref = ref_for_label_on_snapshot(snapshot, label, frame_index=frame)
            if new_ref and new_ref != old_ref:
                updated["ref"] = new_ref
                realigned += 1
        out.append(updated)
    return out, realigned


def ref_for_label_on_snapshot(
    snapshot: BrowserSnapshot,
    label: str,
    *,
    frame_index: int | None = None,
) -> str | None:
    sample = label.strip()
    if not sample:
        return None
    keys = ("text", "value", "aria_label", "title", "name", "placeholder")
    for element in snapshot.elements:
        if not _frame_matches(element, frame_index):
            continue
        for key in keys:
            raw = element.get(key)
            if raw in (None, ""):
                continue
            if _label_matches(str(raw), sample):
                ref = element.get("ref") or element.get("target")
                if ref:
                    return str(ref)
    return None


async def resolve_navigation_target(
    adapter: BrowserAdapter,
    locator: LocatorService,
    snapshot: BrowserSnapshot,
    *,
    dom_ref: str | None,
    label_sample: str | None,
    semantics: list[str],
    required: bool = True,
    frame_index: int | None = None,
) -> str:
    if dom_ref and dom_ref.startswith("@e") and snapshot_has_ref(
        snapshot, dom_ref, frame_index=frame_index
    ):
        return dom_ref
    if label_sample:
        by_label = ref_for_label_on_snapshot(snapshot, label_sample, frame_index=frame_index)
        if by_label:
            return by_label
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
        label_sample=nav.search_input_label,
        semantics=nav.search_input_semantic,
        frame_index=nav.search_input_frame_index,
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
        label_sample=nav.search_action_label,
        semantics=nav.search_action_semantic,
        frame_index=nav.search_action_frame_index,
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
    if nav.row_link_ref and snapshot_has_ref(
        current, nav.row_link_ref, frame_index=nav.row_link_frame_index
    ):
        detail_target = nav.row_link_ref
    if detail_target is None and nav.row_link_label:
        detail_target = ref_for_label_on_snapshot(
            current, nav.row_link_label, frame_index=nav.row_link_frame_index
        )
    if detail_target is None:
        detail_target = detail_link_target(current, driver_value, nav.row_link_semantic)
    if detail_target is None:
        detail_target = await resolve_navigation_target(
            adapter,
            locator,
            current,
            dom_ref=None,
            label_sample=nav.row_link_label,
            semantics=[f"{driver_value} {nav.row_link_semantic[0]}"],
            frame_index=nav.row_link_frame_index,
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
