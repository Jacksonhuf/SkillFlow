"""Turn detail_batch driver values into concrete, policy-checked page URLs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote

from browser_skill.errors import ErrorCode, SkillError
from browser_skill.models import BrowserTemplate, RunMode
from browser_skill.runtime.policy import ActionPolicy

_PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")
_HTTP_PREFIXES = ("http://", "https://")


@dataclass(frozen=True)
class BatchItem:
    """One unit of work in a detail_batch run."""

    index: int
    value: str
    url: str


def is_full_url(value: str) -> bool:
    return value.strip().lower().startswith(_HTTP_PREFIXES)


def render_url_template(template: BrowserTemplate, variables: dict[str, object]) -> str:
    pattern = template.system.url_template
    if not pattern:
        raise SkillError(
            ErrorCode.VARIABLE_INVALID,
            "Template has no url_template; supply full detail URLs instead",
            stage="policy",
        )

    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in variables or variables[name] is None:
            raise SkillError(
                ErrorCode.VARIABLE_MISSING,
                f"url_template needs variable '{name}'",
                details={"variables": [name]},
            )
        return quote(str(variables[name]), safe="")

    return _PLACEHOLDER.sub(_sub, pattern)


def plan_batch_items(
    template: BrowserTemplate,
    resolved: dict[str, object],
    driver_values: list[str],
    *,
    policy: ActionPolicy | None = None,
) -> list[BatchItem]:
    """Build the ordered URL list for a detail_batch run.

    Each driver value is either a full detail URL (when ``run.accept_full_urls``) or a business
    id substituted into ``system.url_template``. Every resulting URL must stay inside
    ``allowed_hosts``; a value that fails this check aborts planning rather than being skipped,
    because a wrong host is a template/config error rather than a per-item data problem.
    """
    if template.run.mode != RunMode.DETAIL_BATCH or template.run.driver_variable is None:
        raise SkillError(
            ErrorCode.VARIABLE_INVALID,
            "plan_batch_items requires a detail_batch template",
            stage="policy",
        )
    guard = policy or ActionPolicy()
    driver = template.run.driver_variable
    items: list[BatchItem] = []
    for index, value in enumerate(driver_values):
        if is_full_url(value):
            if not template.run.accept_full_urls:
                raise SkillError(
                    ErrorCode.VARIABLE_INVALID,
                    f"{driver} does not accept full URLs for this template",
                    details={"variable": driver, "value": value},
                )
            url = value.strip()
        else:
            scoped = dict(resolved)
            scoped[driver] = value
            url = render_url_template(template, scoped)
        guard.require_url_allowed(url, template)
        items.append(BatchItem(index=index, value=value, url=url))
    return items
