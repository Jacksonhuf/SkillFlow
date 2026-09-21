from __future__ import annotations

from typing import Any

_ELEMENT_KEYS = (
    "ref",
    "target",
    "id",
    "text",
    "name",
    "label",
    "aria_label",
    "title",
    "role",
    "filename",
    "record_key",
)


def _element_from_mapping(item: dict[str, Any]) -> dict[str, Any]:
    element = {key: item[key] for key in _ELEMENT_KEYS if key in item and item[key] not in (None, "")}
    if "target" not in element and "ref" in element:
        element["target"] = element["ref"]
    if "text" not in element:
        for key in ("name", "label", "aria_label", "title"):
            if key in element:
                element["text"] = element[key]
                break
    return element


def _walk_nodes(value: Any, out: list[dict[str, Any]]) -> None:
    if isinstance(value, dict):
        if any(key in value for key in ("ref", "target", "role", "name", "aria_label")):
            normalized = _element_from_mapping(value)
            if normalized:
                out.append(normalized)
        for child in value.values():
            _walk_nodes(child, out)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                normalized = _element_from_mapping(item)
                if normalized:
                    out.append(normalized)
                _walk_nodes(item, out)
            else:
                _walk_nodes(item, out)


def coerce_snapshot_elements(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize chrome-use / platform snapshot JSON into BrowserSnapshot.elements."""
    direct = payload.get("elements")
    if isinstance(direct, list) and direct:
        return [_element_from_mapping(item) for item in direct if isinstance(item, dict)]

    for key in ("interactive", "nodes", "items", "controls"):
        candidate = payload.get(key)
        if isinstance(candidate, list) and candidate:
            elements = [
                _element_from_mapping(item) for item in candidate if isinstance(item, dict)
            ]
            if elements:
                return elements

    nested = payload.get("snapshot")
    if isinstance(nested, dict):
        return coerce_snapshot_elements(nested)

    collected: list[dict[str, Any]] = []
    _walk_nodes(payload.get("tree") or payload.get("accessibility") or payload, collected)
    if collected:
        return collected
    return []
