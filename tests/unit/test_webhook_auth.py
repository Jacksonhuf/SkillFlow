from __future__ import annotations

from browser_skill.pipeline.webhook_auth import (
    WEBHOOK_SECRET_HEADER,
    validate_webhook_secret,
    webhook_auth_headers,
    webhook_secret_from_options,
)


def test_webhook_secret_from_options() -> None:
    assert webhook_secret_from_options({"webhook_secret": "abc"}) == "abc"
    assert webhook_secret_from_options({"secret": "legacy"}) == "legacy"
    assert webhook_secret_from_options({}) == ""


def test_validate_webhook_secret() -> None:
    headers = {WEBHOOK_SECRET_HEADER: "token-1"}
    assert validate_webhook_secret(headers, "token-1") is True
    assert validate_webhook_secret(headers, "wrong") is False
    assert validate_webhook_secret({}, "token-1") is False
    assert validate_webhook_secret(headers, "") is True


def test_webhook_auth_headers() -> None:
    assert webhook_auth_headers("") == {}
    assert webhook_auth_headers("x")[WEBHOOK_SECRET_HEADER] == "x"
