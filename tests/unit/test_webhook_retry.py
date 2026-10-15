from __future__ import annotations

from browser_skill.pipeline.webhook_retry import (
    extract_webhook_retry_suggestions,
    filter_retry_buckets,
)


def test_extract_retry_suggestions_from_webhook_payload() -> None:
    payload = {
        "event": "run_finished",
        "run_id": "run-1",
        "batch": {
            "retry_suggestions": [
                {
                    "action": "retry_batch",
                    "run_id": "run-1",
                    "failure_bucket": "list_navigation",
                    "cli": "browser-skill retry-batch run-1 --bucket list_navigation",
                },
                {"action": "noop"},
            ],
        },
    }
    items = extract_webhook_retry_suggestions(payload)
    assert len(items) == 1
    assert items[0]["failure_bucket"] == "list_navigation"


def test_filter_retry_buckets() -> None:
    suggestions = [
        {"failure_bucket": "list_navigation", "run_id": "a"},
        {"failure_bucket": "failed", "run_id": "a"},
    ]
    filtered = filter_retry_buckets(suggestions, allowed_buckets={"list_navigation"})
    assert len(filtered) == 1
