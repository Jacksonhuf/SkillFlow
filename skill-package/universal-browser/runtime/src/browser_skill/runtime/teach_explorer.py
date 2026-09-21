from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from browser_skill.browser.base import BrowserAdapter
from browser_skill.errors import ErrorCode, SkillError
from browser_skill.models import (
    BrowserSnapshot,
    BrowserTemplate,
    MappingDiscoveryReport,
    SourcePage,
)
from browser_skill.runtime.discovery import MappingDiscoveryService
from browser_skill.runtime.policy import ActionPolicy


@dataclass(slots=True)
class TeachExplorationResult:
    report: MappingDiscoveryReport
    visited_urls: list[str] = field(default_factory=list)
    attempted_hints: list[str] = field(default_factory=list)
    steps: int = 0
    budget_exhausted: bool = False


class TeachExplorer:
    """Bounded, declaration-driven exploration for Teach mapping discovery.

    Page content never supplies actions. Only template-declared page hints and the declared
    read-only detail semantics can cause a click, and every observed URL is checked against the
    template host allowlist.
    """

    def __init__(self, *, max_steps: int = 12) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be positive")
        self.max_steps = max_steps
        self.discovery = MappingDiscoveryService()
        self.policy = ActionPolicy()

    async def explore(
        self,
        adapter: BrowserAdapter,
        template: BrowserTemplate,
        initial: BrowserSnapshot,
    ) -> TeachExplorationResult:
        self._require_safe_snapshot(initial, template)
        snapshots = [self._tag(initial, SourcePage.LIST)]
        visited = self._visited(initial)
        attempted: list[str] = []
        steps = 0
        current = initial

        for hint in template.learned.page_hints:
            if steps >= self.max_steps:
                break
            normalized = hint.strip()
            if not normalized or normalized in attempted:
                continue
            attempted.append(normalized)
            found = await adapter.find(normalized)
            steps += 1
            if not found.ok:
                continue
            target = self._target(found.data)
            if not target:
                continue
            clicked = await adapter.click(target, observe=True)
            steps += 1
            if not clicked.ok or steps >= self.max_steps:
                continue
            current = await adapter.snapshot(interactive=True, diff=True)
            steps += 1
            self._require_safe_snapshot(current, template)
            snapshots.append(self._tag(current, SourcePage.LIST))
            self._append_url(visited, current.url)
            if self.discovery.discover_many(template, snapshots).publishable_candidate:
                break

        report = self.discovery.discover_many(template, snapshots)
        if not report.publishable_candidate and self._needs_detail(template, report):
            detail_result = await self._explore_one_detail(
                adapter, template, snapshots, visited, attempted, steps
            )
            steps = detail_result
            report = self.discovery.discover_many(template, snapshots)

        return TeachExplorationResult(
            report=report,
            visited_urls=visited,
            attempted_hints=attempted,
            steps=steps,
            budget_exhausted=steps >= self.max_steps and not report.publishable_candidate,
        )

    async def _explore_one_detail(
        self,
        adapter: BrowserAdapter,
        template: BrowserTemplate,
        snapshots: list[BrowserSnapshot],
        visited: list[str],
        attempted: list[str],
        steps: int,
    ) -> int:
        for semantic in template.workflow.detail_link_semantic:
            if steps >= self.max_steps:
                break
            attempted.append(semantic)
            found = await adapter.find(semantic)
            steps += 1
            target = self._target(found.data) if found.ok else None
            if not target:
                continue
            clicked = await adapter.click(target, observe=True)
            steps += 1
            if not clicked.ok or steps >= self.max_steps:
                continue
            detail = await adapter.snapshot(interactive=True, diff=True)
            steps += 1
            self._require_safe_snapshot(detail, template)
            snapshots.append(self._tag(detail, SourcePage.DETAIL))
            self._append_url(visited, detail.url)
            # Returning is diagnostic exploration only; failure leaves the user on a read-only page.
            if steps < self.max_steps:
                await adapter.do_action("page", "back")
                steps += 1
            break
        return steps

    def _require_safe_snapshot(self, snapshot: BrowserSnapshot, template: BrowserTemplate) -> None:
        if not snapshot.url:
            raise SkillError(
                ErrorCode.PAGE_NOT_FOUND,
                "Teach exploration received a snapshot without a page URL",
                stage="teach_exploration",
            )
        self.policy.require_url_allowed(snapshot.url, template)

    @staticmethod
    def _tag(snapshot: BrowserSnapshot, source: SourcePage) -> BrowserSnapshot:
        elements = [{**element, "_source_page": source.value} for element in snapshot.elements]
        return snapshot.model_copy(update={"elements": elements}, deep=True)

    @staticmethod
    def _target(data: Any) -> str | None:
        if isinstance(data, dict):
            value = data.get("target") or data.get("ref")
            return str(value) if value else None
        return str(data) if data else None

    @staticmethod
    def _needs_detail(template: BrowserTemplate, report: MappingDiscoveryReport) -> bool:
        missing = set(report.missing_required_fields) | set(report.missing_required_attachments)
        return any(
            field.key in missing and field.source == SourcePage.DETAIL
            for field in template.target.fields
        ) or any(
            attachment.key in missing and attachment.source == SourcePage.DETAIL
            for attachment in template.target.attachments
        )

    @staticmethod
    def _visited(snapshot: BrowserSnapshot) -> list[str]:
        return [snapshot.url] if snapshot.url else []

    @staticmethod
    def _append_url(visited: list[str], url: str) -> None:
        if url and url not in visited:
            visited.append(url)
