"""Local-only web console for the Universal Browser Skill.

Binds to 127.0.0.1, protects every /api/* call with a per-process token, and reuses
``BrowserSkillApp.handle`` so the UI, the Agent and the CLI behave identically.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import mimetypes
import secrets
import threading
import webbrowser
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Queue
from typing import Any, TypeVar, cast
from urllib.parse import parse_qs, unquote, urlsplit

from pydantic import ValidationError

from browser_skill.app import BrowserSkillApp
from browser_skill.errors import ErrorCode, SkillError
from browser_skill.models import SkillRequest, SkillResponse
from browser_skill.outputs.paths import contained_path, safe_filename
from browser_skill.platform.probe import probe_adapter

T = TypeVar("T")

_UI_PATH = Path(__file__).with_name("ui.html")
_MAX_BODY_BYTES = 20 * 1024 * 1024
_SYNC_ACTIONS = {
    "start",
    "status",
    "cancel",
    "metrics",
    "analyze_sample",
    "create",
    "publish",
    "validate_acceptance",
}


class JobRegistry:
    """Serial background executor: one browser task at a time, results kept in memory.

    All browser work runs on a single long-lived event loop owned by the worker thread, so
    adapters that keep a live connection (Playwright) stay valid across jobs.
    """

    def __init__(self, app: BrowserSkillApp) -> None:
        self.app = app
        self._jobs: dict[str, dict[str, Any]] = {}
        self._requests: dict[str, SkillRequest] = {}
        self._queue: Queue[str | _SyncCall | None] = Queue()
        self._lock = threading.Lock()
        self._worker = threading.Thread(target=self._loop, name="console-jobs", daemon=True)
        self._worker.start()

    def run_sync(self, factory: Callable[[], Coroutine[Any, Any, T]], timeout: float = 120) -> T:
        """Run a coroutine on the worker loop from another thread and wait for the result."""
        call = _SyncCall(factory)
        self._queue.put(call)
        return cast(T, call.result(timeout))

    def submit(self, request: SkillRequest) -> dict[str, Any]:
        job_id = f"job_{datetime.now(UTC):%Y%m%dT%H%M%SZ}_{secrets.token_hex(3)}"
        job = {
            "job_id": job_id,
            "status": "queued",
            "action": request.action,
            "submitted_at": datetime.now(UTC).isoformat(),
            "response": None,
        }
        with self._lock:
            self._jobs[job_id] = job
        self._requests[job_id] = request
        self._queue.put(job_id)
        return dict(job)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(job) for job in self._jobs.values()]

    def stop(self) -> None:
        self._queue.put(None)

    def _loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            while True:
                item = self._queue.get()
                if item is None:
                    return
                if isinstance(item, _SyncCall):
                    item.run(loop)
                    continue
                self._run_job(loop, item)
        finally:
            close = getattr(self.app.adapter, "close", None)
            if callable(close):
                with contextlib.suppress(Exception):
                    loop.run_until_complete(close())
            loop.close()

    def _run_job(self, loop: asyncio.AbstractEventLoop, job_id: str) -> None:
        request = self._requests.pop(job_id, None)
        if request is None:
            return
        self._set(job_id, status="running", started_at=datetime.now(UTC).isoformat())
        try:
            response = loop.run_until_complete(self.app.handle(request))
            payload = response.model_dump(mode="json")
        except Exception as exc:
            payload = SkillResponse(ok=False, message=str(exc)).model_dump(mode="json")
        self._set(
            job_id,
            status="done",
            finished_at=datetime.now(UTC).isoformat(),
            response=payload,
        )

    def _set(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].update(fields)


class _SyncCall:
    def __init__(self, factory: Callable[[], Coroutine[Any, Any, Any]]) -> None:
        self.factory = factory
        self._done = threading.Event()
        self._result: Any = None
        self._error: BaseException | None = None

    def run(self, loop: asyncio.AbstractEventLoop) -> None:
        try:
            self._result = loop.run_until_complete(self.factory())
        except BaseException as exc:  # propagated to the waiting thread
            self._error = exc
        finally:
            self._done.set()

    def result(self, timeout: float) -> Any:
        if not self._done.wait(timeout):
            raise TimeoutError("console job worker did not respond in time")
        if self._error is not None:
            raise self._error
        return self._result


class ConsoleServer:
    def __init__(
        self,
        app: BrowserSkillApp,
        *,
        host: str = "127.0.0.1",
        port: int = 8765,
        token: str | None = None,
    ) -> None:
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise SkillError(ErrorCode.ACTION_NOT_ALLOWED, "Console only binds to loopback")
        self.app = app
        self.token = token or secrets.token_urlsafe(24)
        self.jobs = JobRegistry(app)
        self._server = ThreadingHTTPServer((host, port), _Handler)
        self._server.daemon_threads = True
        setattr(self._server, "console", self)  # noqa: B010
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?token={self.token}"

    def start(self) -> str:
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="console-http", daemon=True
        )
        self._thread.start()
        return self.url

    def serve_forever(self, *, open_browser: bool = True) -> None:
        url = self.start()
        if open_browser:
            webbrowser.open(url)
        try:
            while self._thread is not None and self._thread.is_alive():
                self._thread.join(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self.jobs.stop()
        self._server.shutdown()
        self._server.server_close()

    # ----- API implementation -------------------------------------------------

    def templates(self, *, include_unpublished: bool) -> list[dict[str, Any]]:
        items = self.app.store.list(include_unpublished=include_unpublished)
        return [
            {
                "display_index": index,
                "template_id": item.template_id,
                "version": item.version,
                "name": item.name,
                "description": item.description,
                "status": item.status.value,
            }
            for index, item in enumerate(items, 1)
        ]

    def template_detail(self, template_id: str) -> dict[str, Any]:
        template = self.app.store.load(template_id, require_published=False)
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
                }
                for name, spec in template.variables.items()
            ],
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
        }

    def runs(self, limit: int = 50) -> list[dict[str, Any]]:
        root = self.app.runs_root
        results: list[dict[str, Any]] = []
        if not root.is_dir():
            return results
        for directory in sorted(root.iterdir(), reverse=True):
            if not directory.is_dir() or not directory.name.startswith("run_"):
                continue
            summary_path = directory / "summary.json"
            run_path = directory / "run.json"
            entry: dict[str, Any] = {"run_id": directory.name}
            try:
                if summary_path.is_file():
                    summary = json.loads(summary_path.read_text(encoding="utf-8"))
                    entry.update(
                        {
                            "state": summary.get("state"),
                            "template": summary.get("template"),
                            "record_count": summary.get("record_count"),
                            "download_count": summary.get("download_count"),
                            "duration_ms": summary.get("duration_ms"),
                            "validation_ok": (summary.get("validation") or {}).get("ok"),
                            "error": (summary.get("error") or {}).get("message"),
                            "artifacts": summary.get("artifacts") or {},
                        }
                    )
                elif run_path.is_file():
                    run = json.loads(run_path.read_text(encoding="utf-8"))
                    entry.update(
                        {
                            "state": run.get("state"),
                            "template": f"{run.get('template_id')}@{run.get('template_version')}",
                            "record_count": len(run.get("records") or []),
                        }
                    )
                else:
                    continue
            except (OSError, json.JSONDecodeError):
                entry["state"] = "UNREADABLE"
            results.append(entry)
            if len(results) >= limit:
                break
        return results

    def run_detail(self, run_id: str) -> dict[str, Any]:
        workspace = self.app.run_store.workspace(run_id)
        if not workspace.is_dir():
            raise SkillError(ErrorCode.TEMPLATE_NOT_FOUND, "Run not found")
        detail: dict[str, Any] = {"run_id": run_id}
        for name in ("summary", "manifest", "pipeline"):
            path = workspace / f"{name}.json"
            if path.is_file():
                try:
                    detail[name] = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    detail[name] = None
        run_path = workspace / "run.json"
        if run_path.is_file():
            try:
                run = json.loads(run_path.read_text(encoding="utf-8"))
                detail["state"] = run.get("state")
                detail["variables"] = run.get("variables")
                detail["records_preview"] = (run.get("records") or [])[:20]
            except (OSError, json.JSONDecodeError):
                pass
        report_path = workspace / "report.md"
        if report_path.is_file():
            detail["report_markdown"] = report_path.read_text(encoding="utf-8")
        return detail

    def artifact(self, run_id: str, relative: str) -> Path:
        workspace = self.app.run_store.workspace(run_id)
        parts = [part for part in relative.split("/") if part]
        path = contained_path(workspace, *parts)
        if not path.is_file():
            raise SkillError(ErrorCode.TEMPLATE_NOT_FOUND, "Artifact not found")
        return path

    def save_sample(self, filename: str, content_base64: str) -> dict[str, Any]:
        safe = safe_filename(filename, fallback="sample")
        try:
            raw = base64.b64decode(content_base64, validate=True)
        except (ValueError, TypeError) as exc:
            raise SkillError(ErrorCode.VARIABLE_INVALID, "Invalid sample encoding") from exc
        if len(raw) > _MAX_BODY_BYTES:
            raise SkillError(ErrorCode.VARIABLE_INVALID, "Sample file is too large")
        destination = contained_path(self.app.samples_root, safe)
        destination.write_bytes(raw)
        return {"sample_path": safe, "size": len(raw)}

    async def doctor(self) -> dict[str, Any]:
        report = await probe_adapter(self.app.adapter, mode="local_cli")
        payload = report.model_dump(mode="json")
        executable = getattr(self.app.adapter, "executable", None)
        if executable is not None:
            payload["chrome_use_executable"] = str(executable)
        return payload


class _Handler(BaseHTTPRequestHandler):
    server_version = "UniversalBrowserConsole/1.0"

    @property
    def console(self) -> ConsoleServer:
        return cast(ConsoleServer, getattr(self.server, "console"))  # noqa: B009

    def log_message(self, *_args: Any) -> None:
        return

    # ----- helpers -------------------------------------------------------------

    def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message: str, status: HTTPStatus, **extra: Any) -> None:
        self._send_json({"ok": False, "message": message, **extra}, status)

    def _authorized(self) -> bool:
        provided = self.headers.get("X-Console-Token", "")
        return secrets.compare_digest(provided, self.console.token)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        if length > _MAX_BODY_BYTES:
            raise SkillError(ErrorCode.VARIABLE_INVALID, "Request body is too large")
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SkillError(ErrorCode.VARIABLE_INVALID, "Request body must be JSON") from exc
        if not isinstance(payload, dict):
            raise SkillError(ErrorCode.VARIABLE_INVALID, "Request body must be a JSON object")
        return cast(dict[str, Any], payload)

    def _serve_ui(self) -> None:
        if not _UI_PATH.is_file():
            self._error("UI asset missing", HTTPStatus.NOT_FOUND)
            return
        body = _UI_PATH.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
            "connect-src 'self'; img-src 'self' data:",
        )
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, path: Path) -> None:
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header(
            "Content-Disposition", f'attachment; filename="{safe_filename(path.name)}"'
        )
        self.end_headers()
        self.wfile.write(data)

    def _request_from(self, payload: dict[str, Any]) -> SkillRequest:
        try:
            return SkillRequest.model_validate(payload)
        except ValidationError as exc:
            raise SkillError(
                ErrorCode.VARIABLE_INVALID,
                "Invalid request",
                details={"errors": json.loads(exc.json())},
            ) from exc

    # ----- routing -------------------------------------------------------------

    def do_GET(self) -> None:
        parts = urlsplit(self.path)
        path = parts.path
        query = parse_qs(parts.query)
        if path in {"/", "/index.html"}:
            self._serve_ui()
            return
        if not path.startswith("/api/"):
            self._error("Not found", HTTPStatus.NOT_FOUND)
            return
        if not self._authorized():
            self._error("Unauthorized", HTTPStatus.UNAUTHORIZED)
            return
        try:
            self._route_get(path, query)
        except SkillError as exc:
            status = (
                HTTPStatus.NOT_FOUND
                if exc.code in {ErrorCode.TEMPLATE_NOT_FOUND, ErrorCode.UNSAFE_OUTPUT_PATH}
                else HTTPStatus.BAD_REQUEST
            )
            self._error(exc.message, status, error=exc.as_dict())

    def _route_get(self, path: str, query: dict[str, list[str]]) -> None:
        console = self.console
        segments = [unquote(part) for part in path.split("/") if part][1:]
        if segments == ["templates"]:
            include_all = query.get("all", ["0"])[0] in {"1", "true"}
            templates = console.templates(include_unpublished=include_all)
            self._send_json({"ok": True, "templates": templates})
        elif len(segments) == 2 and segments[0] == "templates":
            self._send_json({"ok": True, "template": console.template_detail(segments[1])})
        elif segments == ["runs"]:
            self._send_json({"ok": True, "runs": console.runs()})
        elif len(segments) == 2 and segments[0] == "runs":
            self._send_json({"ok": True, "run": console.run_detail(segments[1])})
        elif len(segments) >= 4 and segments[0] == "runs" and segments[2] == "files":
            self._serve_file(console.artifact(segments[1], "/".join(segments[3:])))
        elif segments == ["jobs"]:
            self._send_json({"ok": True, "jobs": console.jobs.list()})
        elif len(segments) == 2 and segments[0] == "jobs":
            job = console.jobs.get(segments[1])
            if job is None:
                self._error("Job not found", HTTPStatus.NOT_FOUND)
            else:
                self._send_json({"ok": True, "job": job})
        elif segments == ["doctor"]:
            self._send_json({"ok": True, "doctor": console.jobs.run_sync(console.doctor)})
        elif segments == ["meta"]:
            self._send_json(
                {
                    "ok": True,
                    "meta": {
                        "templates_root": str(console.app.store.root),
                        "runs_root": str(console.app.runs_root),
                        "samples_root": str(console.app.samples_root),
                    },
                }
            )
        else:
            self._error("Not found", HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if not path.startswith("/api/"):
            self._error("Not found", HTTPStatus.NOT_FOUND)
            return
        if not self._authorized():
            self._error("Unauthorized", HTTPStatus.UNAUTHORIZED)
            return
        try:
            payload = self._read_json()
            self._route_post(path, payload)
        except SkillError as exc:
            self._error(exc.message, HTTPStatus.BAD_REQUEST, error=exc.as_dict())

    def _route_post(self, path: str, payload: dict[str, Any]) -> None:
        console = self.console
        if path == "/api/jobs":
            request = self._request_from(payload)
            self._send_json({"ok": True, "job": console.jobs.submit(request)}, HTTPStatus.ACCEPTED)
        elif path == "/api/action":
            request = self._request_from(payload)
            if request.action not in _SYNC_ACTIONS:
                self._error(
                    f"Action {request.action} must be submitted through /api/jobs",
                    HTTPStatus.BAD_REQUEST,
                )
                return
            response = asyncio.run(console.app.handle(request))
            self._send_json(response.model_dump(mode="json"))
        elif path == "/api/samples":
            filename = str(payload.get("filename", ""))
            content = str(payload.get("content_base64", ""))
            if not filename or not content:
                self._error("filename and content_base64 are required", HTTPStatus.BAD_REQUEST)
                return
            self._send_json({"ok": True, **console.save_sample(filename, content)})
        else:
            self._error("Not found", HTTPStatus.NOT_FOUND)


def serve_console(
    app: BrowserSkillApp,
    *,
    port: int = 8765,
    open_browser: bool = True,
    token: str | None = None,
) -> None:
    server = ConsoleServer(app, port=port, token=token)
    print(f"Universal Browser 本地控制台: {server.url}")
    print("仅本机可访问；关闭请按 Ctrl+C。")
    server.serve_forever(open_browser=open_browser)
