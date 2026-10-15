#!/usr/bin/env python3
"""Minimal webhook receiver that can auto-run ``invoke.py retry-batch`` from delivery JSON.

Point a template ``delivery.webhook`` channel at ``http://127.0.0.1:<port>/`` (or your ingress).
On ``run_finished`` with ``batch.retry_suggestions``, optionally spawns retry jobs.

Environment:
  UNIVERSAL_BROWSER_WEBHOOK_AUTO_RETRY=1   — run ``retry-batch`` per suggestion (default: log only)
  UNIVERSAL_BROWSER_WEBHOOK_RETRY_BUCKETS  — comma-separated buckets to allow (default: all)
  UNIVERSAL_BROWSER_WEBHOOK_SECRET         — require header X-Universal-Browser-Webhook-Secret

Example:
  py scripts/examples/webhook_retry_listener.py --port 9876
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


def _skill_root() -> Path:
    scripts_dir = Path(__file__).resolve().parent.parent
    root = scripts_dir.parent
    if (root / "SKILL.md").is_file():
        return root
    raise SystemExit("Could not locate skill root (expected SKILL.md next to scripts/).")


def _ensure_runtime_path() -> None:
    runtime_src = _skill_root() / "runtime" / "src"
    if runtime_src.is_dir():
        sys.path.insert(0, str(runtime_src))


def _invoke_script() -> Path:
    path = _skill_root() / "scripts" / "invoke.py"
    if not path.is_file():
        raise SystemExit(f"Missing {path}")
    return path


def _allowed_buckets() -> set[str] | None:
    raw = os.environ.get("UNIVERSAL_BROWSER_WEBHOOK_RETRY_BUCKETS", "").strip()
    if not raw:
        return None
    return {part.strip() for part in raw.split(",") if part.strip()}


def _auto_retry_enabled() -> bool:
    return os.environ.get("UNIVERSAL_BROWSER_WEBHOOK_AUTO_RETRY", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _expected_secret() -> str:
    return os.environ.get("UNIVERSAL_BROWSER_WEBHOOK_SECRET", "").strip()


def _authorized(handler: BaseHTTPRequestHandler) -> bool:
    secret = _expected_secret()
    if not secret:
        return True
    _ensure_runtime_path()
    from browser_skill.pipeline.webhook_auth import validate_webhook_secret

    return validate_webhook_secret(handler.headers, secret)


def _retry_suggestions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    _ensure_runtime_path()
    from browser_skill.pipeline.webhook_retry import (
        extract_webhook_retry_suggestions,
        filter_retry_buckets,
    )

    return filter_retry_buckets(
        extract_webhook_retry_suggestions(payload),
        allowed_buckets=_allowed_buckets(),
    )


def _spawn_retry(run_id: str, bucket: str) -> dict[str, Any]:
    invoke = _invoke_script()
    cmd = [
        sys.executable,
        str(invoke),
        "retry-batch",
        run_id,
        "--bucket",
        bucket,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return {
        "run_id": run_id,
        "failure_bucket": bucket,
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout_tail": (proc.stdout or "")[-500:],
        "stderr_tail": (proc.stderr or "")[-500:],
    }


class _Handler(BaseHTTPRequestHandler):
    server_version = "UniversalBrowserWebhookRetry/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write(f"{self.address_string()} - {format % args}\n")

    def do_POST(self) -> None:
        if not _authorized(self):
            self.send_error(HTTPStatus.UNAUTHORIZED, "invalid webhook secret")
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length > 2 * 1024 * 1024:
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_error(HTTPStatus.BAD_REQUEST, "invalid JSON")
            return
        if not isinstance(payload, dict):
            self.send_error(HTTPStatus.BAD_REQUEST, "JSON object required")
            return

        suggestions = _retry_suggestions(payload)
        results: list[dict[str, Any]] = []
        if _auto_retry_enabled():
            for item in suggestions:
                run_id = str(item.get("run_id") or "")
                bucket = str(item.get("failure_bucket") or "failed")
                results.append(_spawn_retry(run_id, bucket))

        body = {
            "ok": True,
            "suggestions": suggestions,
            "auto_retry": _auto_retry_enabled(),
            "retry_results": results,
        }
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Webhook listener for batch retry_suggestions")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9876)
    args = parser.parse_args(argv)

    server = ThreadingHTTPServer((args.host, args.port), _Handler)
    print(f"Listening on http://{args.host}:{args.port}/ (auto_retry={_auto_retry_enabled()})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
