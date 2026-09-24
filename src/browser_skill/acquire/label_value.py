"""Label/value pairs from rendered page text (``innerText``).

Detail pages usually present business data as description lists or two-column tables. Once
rendered to text they appear as ``订单金额: ¥1,200``, ``客户名称<TAB>张三贸易`` or a short label
line followed by its value line. This module turns that text into pairs so both the probe (to
propose fields) and the runtime (to read them) share one interpretation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_MAX_LABEL = 24
_MAX_VALUE = 200
_COLON = re.compile(r"^\s*([^:：\t]{1,24}?)\s*[:：]\s*(.*?)\s*$")
_LABEL_NOISE = re.compile(r"[\d%¥$€£]|https?://|www\.")
_LABEL_TAIL = re.compile(r"[。！？!?,，;；]$")
_SCHEME = re.compile(r"^\w+://")


@dataclass(frozen=True, slots=True)
class LabelValue:
    label: str
    value: str
    confidence: float


def looks_like_label(text: str) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) > _MAX_LABEL:
        return False
    if _LABEL_NOISE.search(stripped) or _LABEL_TAIL.search(stripped):
        return False
    return not stripped.startswith(("@", "#", "/"))


def _colon_pair(line: str) -> tuple[str, str] | None:
    if _SCHEME.match(line):
        return None
    match = _COLON.match(line)
    if match and looks_like_label(match.group(1)):
        return match.group(1), match.group(2)
    return None


def parse_label_values(text: str) -> list[LabelValue]:
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    pairs: list[LabelValue] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        colon = _colon_pair(line)
        if colon is not None:
            label, value = colon
            if not value and index + 1 < len(lines) and _colon_pair(lines[index + 1]) is None:
                value = lines[index + 1]
                index += 1
            if value:
                pairs.append(LabelValue(label, value[:_MAX_VALUE], 0.9))
            index += 1
            continue
        if "\t" in line:
            parts = [part.strip() for part in line.split("\t") if part.strip()]
            if len(parts) % 2 == 0 and all(
                looks_like_label(parts[i]) for i in range(0, len(parts), 2)
            ):
                for i in range(0, len(parts), 2):
                    pairs.append(LabelValue(parts[i], parts[i + 1][:_MAX_VALUE], 0.8))
            index += 1
            continue
        # A bare label line followed by a value line; only trusted when the value carries data
        # (digits) so navigation menus rendered as consecutive words are not mistaken for pairs.
        if looks_like_label(line) and index + 1 < len(lines):
            candidate = lines[index + 1]
            if (
                re.search(r"\d", candidate)
                and _colon_pair(candidate) is None
                and "\t" not in candidate
            ):
                pairs.append(LabelValue(line, candidate[:_MAX_VALUE], 0.5))
                index += 2
                continue
        index += 1
    return pairs


def find_label_value(pairs: list[LabelValue], semantics: list[str]) -> str | None:
    """Value whose label equals (preferred) or contains one of ``semantics``."""
    wanted = [item.casefold() for item in semantics if item]
    for pair in pairs:
        if pair.label.casefold() in wanted:
            return pair.value
    for pair in pairs:
        folded = pair.label.casefold()
        if any(item in folded for item in wanted):
            return pair.value
    return None
