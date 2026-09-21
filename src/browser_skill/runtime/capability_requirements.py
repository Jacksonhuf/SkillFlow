from __future__ import annotations

from browser_skill.errors import ErrorCode, SkillError
from browser_skill.models import BrowserCapabilities, BrowserTemplate


def missing_capabilities_for_template(
    capabilities: BrowserCapabilities,
    template: BrowserTemplate,
) -> list[str]:
    missing: list[str] = []
    if not capabilities.snapshot:
        missing.append("snapshot")
    if not capabilities.find:
        missing.append("find")
    if template.target.attachments:
        if not capabilities.download:
            missing.append("download")
        if not capabilities.downloads:
            missing.append("downloads")
    return missing


def ensure_template_runtime_capabilities(
    capabilities: BrowserCapabilities,
    template: BrowserTemplate,
) -> None:
    missing = missing_capabilities_for_template(capabilities, template)
    if not missing:
        return
    user_message = "当前浏览器环境不满足该模板的运行要求，请稍后重试或联系管理员升级 chrome-use。"
    raise SkillError(
        ErrorCode.CHROME_USE_UNAVAILABLE,
        user_message,
        stage="preflight",
        retryable=True,
        details={
            "missing_capabilities": missing,
            "template_id": template.template_id,
            "template_version": template.version,
            "attachment_count": len(template.target.attachments),
        },
    )
