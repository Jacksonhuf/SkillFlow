"""Shared-secret helpers for ``delivery.webhook`` and example receivers."""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from typing import Any

WEBHOOK_SECRET_HEADER = "X-Universal-Browser-Webhook-Secret"


def webhook_secret_from_options(options: dict[str, Any] | None) -> str:
    if not options:
        return ""
    for key in ("webhook_secret", "secret"):
        raw = options.get(key)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    return ""


def webhook_auth_headers(secret: str) -> dict[str, str]:
    if not secret:
        return {}
    return {WEBHOOK_SECRET_HEADER: secret}


def validate_webhook_secret(headers: Mapping[str, str], expected: str) -> bool:
    if not expected:
        return True
    got = ""
    for name, value in headers.items():
        if name.lower() == WEBHOOK_SECRET_HEADER.lower():
            got = str(value).strip()
            break
    if not got:
        return False
    return secrets.compare_digest(got, expected)
