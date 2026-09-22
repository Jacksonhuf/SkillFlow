"""Vision fallback: locate a control on a screenshot when DOM/semantic strategies fail.

The skill runtime does not ship a vision model. A host (Agent platform, local console plugin)
injects a ``VisionProvider``; the runtime handles screenshots, confidence gating and turning the
answer into a clickable ``xy:<x>,<y>`` target that adapters understand. Without a provider the
fallback is inert and the locator raises ``E_ELEMENT_NOT_FOUND`` exactly as before.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from typing import Any, Protocol

from browser_skill.models import CommandResult

_XY_TARGET = re.compile(r"^xy:(?P<x>-?\d+(?:\.\d+)?),(?P<y>-?\d+(?:\.\d+)?)$")


@dataclass(frozen=True, slots=True)
class VisionTarget:
    """Where the model believes the described control is, in CSS pixels of the viewport."""

    x: float
    y: float
    confidence: float = 0.0
    label: str = ""

    @property
    def target(self) -> str:
        return f"xy:{round(self.x)},{round(self.y)}"


def parse_xy_target(target: str) -> tuple[float, float] | None:
    match = _XY_TARGET.match(target.strip())
    if match is None:
        return None
    return float(match.group("x")), float(match.group("y"))


class VisionProvider(Protocol):
    name: str

    async def locate(
        self,
        screenshot_png: bytes,
        description: str,
        *,
        page_url: str = "",
        viewport: tuple[int, int] | None = None,
    ) -> VisionTarget | None: ...


class NullVisionProvider:
    """Default provider: never answers, so the fallback stays disabled."""

    name = "none"

    async def locate(
        self,
        screenshot_png: bytes,
        description: str,
        *,
        page_url: str = "",
        viewport: tuple[int, int] | None = None,
    ) -> VisionTarget | None:
        return None


class ScriptedVisionProvider:
    """Deterministic provider for tests and dry runs: description -> target."""

    name = "scripted"

    def __init__(self, answers: dict[str, VisionTarget]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, int]] = []

    async def locate(
        self,
        screenshot_png: bytes,
        description: str,
        *,
        page_url: str = "",
        viewport: tuple[int, int] | None = None,
    ) -> VisionTarget | None:
        self.calls.append((description, len(screenshot_png)))
        return self.answers.get(description)


def decode_screenshot(result: CommandResult) -> tuple[bytes, tuple[int, int] | None] | None:
    """Accept raw bytes, base64 text, or ``{"png_base64"|"data"|"image": ..., width, height}``."""
    if not result.ok or result.data is None:
        return None
    data: Any = result.data
    viewport: tuple[int, int] | None = None
    if isinstance(data, dict):
        width, height = data.get("width"), data.get("height")
        if isinstance(width, int) and isinstance(height, int):
            viewport = (width, height)
        data = data.get("png_base64") or data.get("data") or data.get("image")
    if isinstance(data, bytes):
        return (data, viewport) if data else None
    if isinstance(data, str) and data:
        try:
            return base64.b64decode(data, validate=False), viewport
        except ValueError:
            return None
    return None


class VisionFallback:
    """Last rung of the acquisition ladder: screenshot -> provider -> ``xy`` target."""

    def __init__(self, provider: VisionProvider, *, min_confidence: float = 0.6) -> None:
        self.provider = provider
        self.min_confidence = min_confidence
        self.attempts: list[dict[str, Any]] = []

    @property
    def enabled(self) -> bool:
        return not isinstance(self.provider, NullVisionProvider)

    async def locate(self, adapter: Any, description: str, *, page_url: str = "") -> str | None:
        if not self.enabled:
            return None
        screenshot = getattr(adapter, "screenshot", None)
        if not callable(screenshot):
            self.attempts.append({"hint": description, "outcome": "no_screenshot_capability"})
            return None
        decoded = decode_screenshot(await screenshot())
        if decoded is None:
            self.attempts.append({"hint": description, "outcome": "screenshot_failed"})
            return None
        png, viewport = decoded
        answer = await self.provider.locate(png, description, page_url=page_url, viewport=viewport)
        if answer is None or answer.confidence < self.min_confidence:
            self.attempts.append(
                {
                    "hint": description,
                    "outcome": "rejected" if answer else "no_answer",
                    "confidence": answer.confidence if answer else None,
                    "provider": self.provider.name,
                }
            )
            return None
        self.attempts.append(
            {
                "hint": description,
                "outcome": "located",
                "confidence": answer.confidence,
                "target": answer.target,
                "provider": self.provider.name,
            }
        )
        return answer.target
