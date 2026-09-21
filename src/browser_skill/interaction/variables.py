from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from browser_skill.errors import ErrorCode, SkillError
from browser_skill.models import BrowserTemplate, VariableSpec, VariableType


class VariableResolver:
    def missing(self, template: BrowserTemplate, supplied: dict[str, Any]) -> list[str]:
        return [
            name
            for name, spec in template.variables.items()
            if spec.required and name not in supplied and spec.default is None
        ]

    def resolve(self, template: BrowserTemplate, supplied: dict[str, Any]) -> dict[str, Any]:
        unknown = set(supplied) - set(template.variables)
        if unknown:
            raise SkillError(ErrorCode.VARIABLE_INVALID, f"Unknown variables: {sorted(unknown)}")
        missing = self.missing(template, supplied)
        if missing:
            raise SkillError(
                ErrorCode.VARIABLE_MISSING,
                f"Missing required variables: {', '.join(missing)}",
                details={"variables": missing},
            )
        resolved: dict[str, Any] = {}
        for name, spec in template.variables.items():
            value = supplied.get(name, spec.default)
            if value is None:
                continue
            resolved[name] = self._coerce(name, spec, value)
        return resolved

    def redacted(self, template: BrowserTemplate, values: dict[str, Any]) -> dict[str, Any]:
        return {
            key: "***"
            if template.variables.get(key) and template.variables[key].sensitive
            else value
            for key, value in values.items()
        }

    def _coerce(self, name: str, spec: VariableSpec, value: Any) -> Any:
        try:
            if spec.type == VariableType.STRING:
                result: Any = str(value).strip()
            elif spec.type == VariableType.INTEGER:
                result = int(value)
            elif spec.type == VariableType.NUMBER:
                result = float(value)
            elif spec.type == VariableType.BOOLEAN:
                if isinstance(value, bool):
                    result = value
                elif str(value).casefold() in {"true", "1", "yes", "y", "是"}:
                    result = True
                elif str(value).casefold() in {"false", "0", "no", "n", "否"}:
                    result = False
                else:
                    raise ValueError("not a boolean")
            elif spec.type == VariableType.DATE:
                if isinstance(value, date):
                    result = value.isoformat()
                elif str(value).casefold() == "today":
                    result = date.today().isoformat()
                elif str(value).casefold() == "yesterday":
                    result = (date.today() - timedelta(days=1)).isoformat()
                else:
                    result = date.fromisoformat(str(value)).isoformat()
            else:
                result = str(value)
        except (TypeError, ValueError) as exc:
            raise SkillError(ErrorCode.VARIABLE_INVALID, f"Invalid value for {name}") from exc
        if spec.options and str(result) not in spec.options:
            raise SkillError(ErrorCode.VARIABLE_INVALID, f"{name} must be one of {spec.options}")
        if spec.validation:
            validation = spec.validation
            if validation.regex and re.fullmatch(validation.regex, str(result)) is None:
                raise SkillError(ErrorCode.VARIABLE_INVALID, f"{name} does not match its pattern")
            if validation.minimum is not None and float(result) < validation.minimum:
                raise SkillError(ErrorCode.VARIABLE_INVALID, f"{name} is below its minimum")
            if validation.maximum is not None and float(result) > validation.maximum:
                raise SkillError(ErrorCode.VARIABLE_INVALID, f"{name} is above its maximum")
        return result
