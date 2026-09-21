from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    TEMPLATE_NOT_FOUND = "E_TEMPLATE_NOT_FOUND"
    TEMPLATE_INVALID = "E_TEMPLATE_INVALID"
    TEMPLATE_SELECTOR_AMBIGUOUS = "E_TEMPLATE_SELECTOR_AMBIGUOUS"
    VARIABLE_MISSING = "E_VARIABLE_MISSING"
    VARIABLE_INVALID = "E_VARIABLE_INVALID"
    CHROME_USE_UNAVAILABLE = "E_CHROME_USE_UNAVAILABLE"
    EXTENSION_OFFLINE = "E_EXTENSION_OFFLINE"
    AUTH_REQUIRED = "E_AUTH_REQUIRED"
    AUTH_TIMEOUT = "E_AUTH_TIMEOUT"
    PAGE_NOT_FOUND = "E_PAGE_NOT_FOUND"
    NAVIGATION_FAILED = "E_NAVIGATION_FAILED"
    ELEMENT_NOT_FOUND = "E_ELEMENT_NOT_FOUND"
    FIELD_MAPPING_FAILED = "E_FIELD_MAPPING_FAILED"
    PAGINATION_INCOMPLETE = "E_PAGINATION_INCOMPLETE"
    DOWNLOAD_FAILED = "E_DOWNLOAD_FAILED"
    DOWNLOAD_INCOMPLETE = "E_DOWNLOAD_INCOMPLETE"
    VALIDATION_FAILED = "E_VALIDATION_FAILED"
    ACTION_NOT_ALLOWED = "E_ACTION_NOT_ALLOWED"
    UNSAFE_OUTPUT_PATH = "E_UNSAFE_OUTPUT_PATH"
    REPAIR_FAILED = "E_REPAIR_FAILED"
    REPAIR_REQUIRES_TEACH = "E_REPAIR_REQUIRES_TEACH"
    OUTPUT_WRITE_FAILED = "E_OUTPUT_WRITE_FAILED"
    RUN_CANCELLED = "E_RUN_CANCELLED"
    RUN_INTERRUPTED = "E_RUN_INTERRUPTED"
    RUN_RECOVERY_NOT_ALLOWED = "E_RUN_RECOVERY_NOT_ALLOWED"


@dataclass(slots=True)
class SkillError(Exception):
    code: ErrorCode
    message: str
    stage: str | None = None
    retryable: bool = False
    repairable: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "stage": self.stage,
            "retryable": self.retryable,
            "repairable": self.repairable,
            "details": self.details,
        }
