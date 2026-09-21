from __future__ import annotations

from enum import StrEnum
from typing import ClassVar
from urllib.parse import urlparse

from browser_skill.errors import ErrorCode, SkillError
from browser_skill.models import BrowserTemplate


class ActionRisk(StrEnum):
    READ = "read"
    NAVIGATE = "navigate"
    QUERY = "query"
    DOWNLOAD = "download"
    MUTATE = "mutate"
    UNKNOWN = "unknown"


class ActionPolicy:
    DENIED_WORDS: ClassVar[set[str]] = {
        "submit",
        "finalize",
        "delete",
        "approve",
        "purchase",
        "pay",
        "send",
        "publish",
        "upload",
        "execute_script",
        "network_route",
    }

    def require_allowed(self, action: str, *, declared: bool = True) -> None:
        if not declared or action.casefold() in self.DENIED_WORDS:
            raise SkillError(
                ErrorCode.ACTION_NOT_ALLOWED,
                f"Action is not allowed by the MVP policy: {action}",
                stage="policy",
            )

    def require_url_allowed(self, url: str, template: BrowserTemplate) -> None:
        parsed = urlparse(url)
        allowed = set(template.system.allowed_hosts)
        if parsed.scheme not in {"https", "http"} or parsed.hostname not in allowed:
            raise SkillError(
                ErrorCode.ACTION_NOT_ALLOWED,
                "Navigation target is outside the template host scope",
                stage="policy",
            )
