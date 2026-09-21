from __future__ import annotations

from typing import Any

AGENT_EXECUTION_CONTRACT: dict[str, Any] = {
    "mode": "template_runner_only",
    "must_use_standalone_invoke": True,
    "invoke_commands": {
        "list_templates": "start",
        "execute": "run <template_id> --var name=value",
        "after_login": "resume <run_id>",
    },
    "forbidden": [
        "improvised_scraping_without_invoke",
        "claiming_success_without_run_id",
        "js_injection_as_primary_extraction",
        "asking_user_to_install_chrome_use_cli",
        "user_facing_doctor_or_probe",
    ],
    "evidence_required": [
        "run_id",
        "runs_workspace_artifacts",
        "skill_response_json_from_invoke",
    ],
    "attachment_policy": (
        "Attachments are produced only by invoke run via template AttachmentDownloader; "
        "never by manual link extraction in chat."
    ),
}


def contract_payload() -> dict[str, Any]:
    return dict(AGENT_EXECUTION_CONTRACT)
