"""Safe template metadata for consoles, CLIs, and agents (no learned internals)."""

from __future__ import annotations

from typing import Any

from browser_skill.models import BrowserTemplate
from browser_skill.pipeline.deliver import delivery_channel_summaries


def template_detail_dict(template: BrowserTemplate) -> dict[str, Any]:
    return {
        "template_id": template.template_id,
        "version": template.version,
        "name": template.name,
        "description": template.description,
        "status": template.status.value,
        "schema_version": template.schema_version,
        "entry_url": str(template.system.entry_url),
        "variables": [
            {
                "name": name,
                "type": spec.type.value,
                "required": spec.required,
                "default": spec.default,
                "prompt": spec.prompt,
                "options": spec.options,
                "sensitive": spec.sensitive,
                "multiple": spec.multiple,
            }
            for name, spec in template.variables.items()
        ],
        "run": {
            "mode": template.run.mode.value,
            "driver_variable": template.run.driver_variable,
            "url_template": template.system.url_template,
            "accept_full_urls": template.run.accept_full_urls,
        },
        "fields": [
            {"key": f.key, "name": f.name, "type": f.type.value, "required": f.required}
            for f in template.target.fields
        ],
        "attachments": [
            {"key": a.key, "name": a.name, "required": a.required, "multiple": a.multiple}
            for a in template.target.attachments
        ],
        "pipeline": {
            "processing": template.processing.enabled,
            "report": template.report.enabled,
            "delivery": template.delivery.enabled,
            "analysis": template.analysis.enabled,
        },
        "delivery_channels": delivery_channel_summaries(template.delivery),
    }
