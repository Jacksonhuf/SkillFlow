from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from browser_skill.browser.base import BrowserAdapter
from browser_skill.errors import ErrorCode, SkillError
from browser_skill.models import BrowserSnapshot

LocatorStrategy = Literal[
    "learned", "snapshot_exact", "snapshot_partial", "semantic_find", "dom_hint"
]


@dataclass(frozen=True, slots=True)
class LocatedTarget:
    target: str
    strategy: LocatorStrategy
    hint: str
    confidence: float


class LocatorService:
    """Resolve ephemeral action targets using a deterministic, ambiguity-safe priority order."""

    SAFE_TEXT_KEYS = ("text", "name", "label", "aria_label", "title")

    async def locate(
        self,
        adapter: BrowserAdapter,
        snapshot: BrowserSnapshot,
        semantics: list[str],
        *,
        learned_hints: list[str] | None = None,
        dom_hints: list[str] | None = None,
        record_key: str | None = None,
        required: bool = True,
    ) -> LocatedTarget | None:
        learned = self._unique(learned_hints or [])
        declared = [hint for hint in self._unique(semantics) if hint not in learned]
        for hint in learned:
            located = self._from_snapshot(
                snapshot,
                hint,
                strategy="learned",
                record_key=record_key,
            )
            if located:
                return located
        for hint in declared:
            located = self._from_snapshot(
                snapshot,
                hint,
                strategy="snapshot_exact",
                record_key=record_key,
            )
            if located:
                return located
        for hint in [*learned, *declared]:
            found = await adapter.find(hint)
            target = self._target(found.data) if found.ok else None
            if target:
                return LocatedTarget(
                    target=target,
                    strategy="semantic_find",
                    hint=hint,
                    confidence=0.6,
                )
        for hint in self._unique(dom_hints or []):
            return LocatedTarget(
                target=hint,
                strategy="dom_hint",
                hint="validated_dom_hint",
                confidence=0.4,
            )
        if required:
            raise SkillError(
                ErrorCode.ELEMENT_NOT_FOUND,
                "No unambiguous target matched the declared semantics",
                stage="locator",
                repairable=True,
                details={"semantics": declared, "learned_hint_count": len(learned)},
            )
        return None

    def _from_snapshot(
        self,
        snapshot: BrowserSnapshot,
        hint: str,
        *,
        strategy: Literal["learned", "snapshot_exact"],
        record_key: str | None,
    ) -> LocatedTarget | None:
        normalized = hint.strip().casefold()
        if not normalized:
            return None
        scoped = [
            element
            for element in snapshot.elements
            if record_key is None or str(element.get("record_key", "")) == record_key
        ]
        exact = [
            element
            for element in scoped
            if normalized in self._values(element, exact=True) and self._target(element) is not None
        ]
        if exact:
            target = self._one_target(exact, hint)
            return LocatedTarget(target, strategy, hint, 1.0 if strategy == "learned" else 0.95)
        partial = [
            element
            for element in scoped
            if any(normalized in value for value in self._values(element, exact=False))
            and self._target(element) is not None
        ]
        if partial:
            target = self._one_target(partial, hint)
            return LocatedTarget(target, "snapshot_partial", hint, 0.8)
        return None

    def _one_target(self, elements: list[dict[str, Any]], hint: str) -> str:
        targets = {target for element in elements if (target := self._target(element))}
        if len(targets) != 1:
            raise SkillError(
                ErrorCode.ELEMENT_NOT_FOUND,
                "Multiple page elements matched the same semantic target",
                stage="locator",
                repairable=True,
                details={"hint": hint, "candidate_count": len(targets)},
            )
        return next(iter(targets))

    def _values(self, element: dict[str, Any], *, exact: bool) -> set[str]:
        values = {
            str(element.get(key, "")).strip().casefold()
            for key in self.SAFE_TEXT_KEYS
            if element.get(key) is not None and element.get(key) != ""
        }
        return values if exact else {value for value in values if value}

    @staticmethod
    def _target(data: Any) -> str | None:
        if isinstance(data, dict):
            value = data.get("target") or data.get("ref")
            return str(value) if value else None
        return str(data) if data else None

    @staticmethod
    def _unique(values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            normalized = value.strip()
            if normalized and normalized not in result:
                result.append(normalized)
        return result
