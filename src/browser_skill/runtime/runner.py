from __future__ import annotations

import json
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from browser_skill.browser.base import BrowserAdapter
from browser_skill.execution_contract import contract_payload
from browser_skill.errors import ErrorCode, SkillError
from browser_skill.interaction.variables import VariableResolver
from browser_skill.models import (
    AuthState,
    BrowserCapabilities,
    BrowserSnapshot,
    BrowserTemplate,
    Checkpoint,
    RunContext,
    RunState,
    SkillResponse,
)
from browser_skill.outputs.writer import OutputWriter, RunWorkspace
from browser_skill.runtime.auth import AuthClassifier
from browser_skill.runtime.capability_requirements import ensure_template_runtime_capabilities
from browser_skill.runtime.detail import DetailCollector
from browser_skill.runtime.downloader import AttachmentDownloader
from browser_skill.runtime.extractor import RecordExtractor
from browser_skill.runtime.locator import LocatorService
from browser_skill.runtime.policy import ActionPolicy
from browser_skill.runtime.run_store import RunStore
from browser_skill.runtime.state_machine import can_transition
from browser_skill.runtime.validator import ResultValidator

EventHook = Callable[[dict[str, Any]], Awaitable[None]]


class Runner:
    def __init__(
        self,
        adapter: BrowserAdapter,
        runs_root: Path,
        *,
        variable_resolver: VariableResolver | None = None,
        auth_classifier: AuthClassifier | None = None,
        validator: ResultValidator | None = None,
        downloader: AttachmentDownloader | None = None,
        extractor: RecordExtractor | None = None,
        detail_collector: DetailCollector | None = None,
        output_writer: OutputWriter | None = None,
        policy: ActionPolicy | None = None,
        locator: LocatorService | None = None,
    ) -> None:
        self.adapter = adapter
        self.runs_root = runs_root
        self.variables = variable_resolver or VariableResolver()
        self.auth = auth_classifier or AuthClassifier()
        self.validator = validator or ResultValidator()
        self.downloader = downloader or AttachmentDownloader()
        self.extractor = extractor or RecordExtractor()
        self.detail_collector = detail_collector or DetailCollector(self.downloader)
        self.output_writer = output_writer or OutputWriter()
        self.policy = policy or ActionPolicy()
        self.locator = locator or LocatorService()
        self.run_store = RunStore(runs_root)

    async def run(
        self,
        template: BrowserTemplate,
        supplied_variables: dict[str, Any],
        *,
        dry_run: bool = False,
    ) -> SkillResponse:
        values = self.variables.resolve(template, supplied_variables)
        run_id = f"run_{datetime.now(UTC):%Y%m%dT%H%M%SZ}_{secrets.token_hex(4)}"
        workspace = RunWorkspace(self.runs_root, run_id)
        context = RunContext(
            run_id=run_id,
            template_id=template.template_id,
            template_version=template.version,
            template_snapshot=template,
            variables=values,
            workspace=workspace.path,
        )
        self._event(
            workspace, context, "run_created", variables=self.variables.redacted(template, values)
        )
        try:
            self._transition(workspace, context, RunState.INPUT_READY)
            if dry_run:
                report = self.validator.validate(
                    template,
                    [],
                    [],
                    pagination_complete=template.target.pagination.strategy == "none",
                )
                context.state = RunState.FAILED if not report.ok else RunState.COMPLETED
                context.finished_at = datetime.now(UTC)
                self._persist_context(workspace, context)
                self.output_writer.write_summary(context, report=report)
                return SkillResponse(
                    ok=report.ok,
                    message="Dry run validated configuration without browser actions",
                    run_id=run_id,
                    state=context.state,
                    data={"validation": report.model_dump(mode="json")},
                )
            self._transition(workspace, context, RunState.AUTH_CHECK)
            capabilities = await self._ensure_browser_ready()
            ensure_template_runtime_capabilities(capabilities, template)
            self.policy.require_url_allowed(str(template.system.entry_url), template)
            if template.system.preferred_tab_url_contains and capabilities.tabs:
                adopted = await self.adapter.adopt_tab(template.system.preferred_tab_url_contains)
                if not adopted.ok:
                    opened = await self.adapter.open(str(template.system.entry_url))
                    if not opened.ok:
                        raise SkillError(ErrorCode.PAGE_NOT_FOUND, "Unable to open template entry")
            else:
                opened = await self.adapter.open(str(template.system.entry_url))
                if not opened.ok:
                    raise SkillError(ErrorCode.PAGE_NOT_FOUND, "Unable to open template entry")
            snapshot = await self.adapter.snapshot(interactive=True)
            auth_state = self.auth.classify(template.auth, snapshot)
            if auth_state != AuthState.AUTHENTICATED:
                self._transition(workspace, context, RunState.WAIT_USER_AUTH)
                return SkillResponse(
                    ok=False,
                    message="请在 Chrome 中完成登录，然后使用此 run_id 恢复任务。",
                    run_id=run_id,
                    state=RunState.WAIT_USER_AUTH,
                    data={"auth_state": auth_state.value},
                )
            self._transition(workspace, context, RunState.NAVIGATING, page_url=snapshot.url)
            snapshot = await self._apply_workflow(
                template,
                values,
                snapshot,
                dialogs_supported=capabilities.dialogs,
            )
            self._transition(workspace, context, RunState.EXTRACTING, page_url=snapshot.url)
            context.records, context.pagination_complete, snapshot = await self.extractor.collect(
                self.adapter, template, snapshot
            )
            needs_detail = any(field.source == "detail" for field in template.target.fields) or any(
                item.source == "detail" for item in template.target.attachments
            )
            if template.target.attachments or needs_detail:
                self._transition(workspace, context, RunState.DOWNLOADING, page_url=snapshot.url)
                list_attachments = [
                    item for item in template.target.attachments if item.source == "list"
                ]
                if list_attachments:
                    context.downloaded_files = await self.downloader.collect(
                        self.adapter,
                        template,
                        snapshot,
                        context.records,
                        workspace.path,
                        attachments=list_attachments,
                    )
                if needs_detail:
                    detail_result = await self.detail_collector.collect(
                        self.adapter, template, snapshot, context.records, workspace.path
                    )
                    context.records = detail_result.records
                    context.downloaded_files.extend(detail_result.files)
                    snapshot = detail_result.snapshot
                    self._event(
                        workspace,
                        context,
                        "detail_collection_finished",
                        record_count=len(detail_result.records),
                        file_count=len(detail_result.files),
                        failed_record_count=len(detail_result.failed_record_keys),
                    )
            self._transition(workspace, context, RunState.VALIDATING)
            report = self.validator.validate(
                template,
                context.records,
                context.downloaded_files,
                pagination_complete=context.pagination_complete,
            )
            if not report.ok:
                raise SkillError(
                    ErrorCode.VALIDATION_FAILED,
                    "Business-result validation failed",
                    stage="VALIDATING",
                    repairable=True,
                    details={"validation": report.model_dump(mode="json")},
                )
            self._transition(workspace, context, RunState.WRITING_OUTPUT)
            final_state = RunState.PARTIAL if report.partial else RunState.COMPLETED
            context.state = final_state
            context.finished_at = datetime.now(UTC)
            artifacts = self.output_writer.write(context, report)
            self._persist_context(workspace, context)
            self._event(workspace, context, "run_finished", artifacts=artifacts)
            return SkillResponse(
                ok=True,
                message="任务完成" if final_state == RunState.COMPLETED else "任务产生部分结果",
                run_id=run_id,
                state=final_state,
                data={
                    "artifacts": artifacts,
                    "validation": report.model_dump(mode="json"),
                    "execution_contract": contract_payload(),
                },
            )
        except SkillError as exc:
            context.state = (
                RunState.CANCELLED if exc.code == ErrorCode.RUN_CANCELLED else RunState.FAILED
            )
            context.finished_at = datetime.now(UTC)
            self._persist_context(workspace, context)
            self._event(workspace, context, "run_failed", error=exc.as_dict())
            self._write_failure_summary(workspace, context, exc)
            return SkillResponse(
                ok=False,
                message=exc.message,
                run_id=run_id,
                state=context.state,
                data={"error": exc.as_dict()},
            )

    async def resume(
        self,
        workspace_path: Path,
        supplied_variables: dict[str, Any] | None = None,
    ) -> SkillResponse:
        """Resume an auth-paused run from its durable business checkpoint."""
        workspace = RunWorkspace.existing(workspace_path)
        run_data = workspace.resolve("run.json")
        if not run_data.exists():
            raise SkillError(ErrorCode.TEMPLATE_INVALID, "Run checkpoint not found")
        context = RunContext.model_validate(json.loads(run_data.read_text(encoding="utf-8")))
        if context.state != RunState.WAIT_USER_AUTH:
            raise SkillError(ErrorCode.AUTH_REQUIRED, "Run is not waiting for authentication")
        supplied_variables = supplied_variables or {}
        for key, value in supplied_variables.items():
            if key not in context.template_snapshot.variables:
                raise SkillError(ErrorCode.VARIABLE_INVALID, f"Unknown variable: {key}")
            context.variables[key] = value
        missing_sensitive = [key for key, value in context.variables.items() if value == "***"]
        if missing_sensitive:
            raise SkillError(
                ErrorCode.VARIABLE_MISSING,
                "Sensitive runtime variables must be supplied again: "
                + ", ".join(missing_sensitive),
            )
        context.variables = self.variables.resolve(context.template_snapshot, context.variables)
        try:
            self._transition(workspace, context, RunState.AUTH_CHECK)
            capabilities = await self._ensure_browser_ready()
            ensure_template_runtime_capabilities(capabilities, context.template_snapshot)
            snapshot = await self.adapter.snapshot(interactive=True)
            auth_state = self.auth.classify(context.template_snapshot.auth, snapshot)
            if auth_state != AuthState.AUTHENTICATED:
                self._transition(workspace, context, RunState.WAIT_USER_AUTH)
                return SkillResponse(
                    ok=False,
                    message="仍未检测到有效登录，请在 Chrome 中完成认证。",
                    run_id=context.run_id,
                    state=context.state,
                    data={"auth_state": auth_state.value},
                )
            template = context.template_snapshot
            self._transition(workspace, context, RunState.NAVIGATING, page_url=snapshot.url)
            snapshot = await self._apply_workflow(
                template,
                context.variables,
                snapshot,
                dialogs_supported=capabilities.dialogs,
            )
            self._transition(workspace, context, RunState.EXTRACTING, page_url=snapshot.url)
            context.records, context.pagination_complete, snapshot = await self.extractor.collect(
                self.adapter, template, snapshot
            )
            needs_detail = any(field.source == "detail" for field in template.target.fields) or any(
                item.source == "detail" for item in template.target.attachments
            )
            if template.target.attachments or needs_detail:
                self._transition(workspace, context, RunState.DOWNLOADING, page_url=snapshot.url)
                list_attachments = [
                    item for item in template.target.attachments if item.source == "list"
                ]
                if list_attachments:
                    context.downloaded_files = await self.downloader.collect(
                        self.adapter,
                        template,
                        snapshot,
                        context.records,
                        workspace.path,
                        attachments=list_attachments,
                    )
                if needs_detail:
                    detail_result = await self.detail_collector.collect(
                        self.adapter, template, snapshot, context.records, workspace.path
                    )
                    context.records = detail_result.records
                    context.downloaded_files.extend(detail_result.files)
                    snapshot = detail_result.snapshot
                    self._event(
                        workspace,
                        context,
                        "detail_collection_finished",
                        record_count=len(detail_result.records),
                        file_count=len(detail_result.files),
                        failed_record_count=len(detail_result.failed_record_keys),
                    )
            self._transition(workspace, context, RunState.VALIDATING)
            report = self.validator.validate(
                template,
                context.records,
                context.downloaded_files,
                pagination_complete=context.pagination_complete,
            )
            if not report.ok:
                raise SkillError(ErrorCode.VALIDATION_FAILED, "Business-result validation failed")
            self._transition(workspace, context, RunState.WRITING_OUTPUT)
            context.state = RunState.PARTIAL if report.partial else RunState.COMPLETED
            context.finished_at = datetime.now(UTC)
            artifacts = self.output_writer.write(context, report)
            self._persist_context(workspace, context)
            self._event(workspace, context, "run_finished", artifacts=artifacts)
            return SkillResponse(
                ok=True,
                message="认证后已恢复并完成任务",
                run_id=context.run_id,
                state=context.state,
                data={"artifacts": artifacts, "validation": report.model_dump(mode="json")},
            )
        except SkillError as exc:
            context.state = (
                RunState.CANCELLED if exc.code == ErrorCode.RUN_CANCELLED else RunState.FAILED
            )
            context.finished_at = datetime.now(UTC)
            self._persist_context(workspace, context)
            self._event(workspace, context, "run_failed", error=exc.as_dict())
            self._write_failure_summary(workspace, context, exc)
            return SkillResponse(
                ok=False,
                message=exc.message,
                run_id=context.run_id,
                state=context.state,
                data={"error": exc.as_dict()},
            )

    async def _apply_workflow(
        self,
        template: BrowserTemplate,
        values: dict[str, Any],
        snapshot: BrowserSnapshot,
        *,
        dialogs_supported: bool = False,
    ) -> BrowserSnapshot:
        current = snapshot
        for hint in template.workflow.hints:
            if hint.action == "ensure_page":
                if hint.target.casefold() not in current.text.casefold():
                    located = await self.locator.locate(
                        self.adapter,
                        current,
                        [hint.target],
                        learned_hints=template.learned.page_hints,
                        dom_hints=[hint.dom_hint] if hint.dom_hint else None,
                    )
                    assert located is not None
                    clicked = await self.adapter.click(located.target)
                    if not clicked.ok:
                        raise SkillError(
                            ErrorCode.NAVIGATION_FAILED,
                            "Unable to navigate to the declared workflow page",
                            stage="NAVIGATING",
                            repairable=True,
                        )
                    await self._reject_unexpected_dialog(dialogs_supported)
                    current = await self.adapter.snapshot(interactive=True, diff=True)
                    if current.url:
                        self.policy.require_url_allowed(current.url, template)
            elif hint.action == "set_filter":
                located = await self.locator.locate(
                    self.adapter,
                    current,
                    [hint.target],
                    dom_hints=[hint.dom_hint] if hint.dom_hint else None,
                )
                assert located is not None
                value = self._interpolate(hint.value or "", values)
                filled = await self.adapter.fill(located.target, value)
                if not filled.ok:
                    raise SkillError(
                        ErrorCode.ELEMENT_NOT_FOUND,
                        "Unable to fill the declared workflow filter",
                        stage="NAVIGATING",
                        repairable=True,
                    )
            elif hint.action == "query":
                located = await self.locator.locate(
                    self.adapter,
                    current,
                    [hint.target],
                    dom_hints=[hint.dom_hint] if hint.dom_hint else None,
                )
                assert located is not None
                clicked = await self.adapter.click(located.target)
                if not clicked.ok:
                    raise SkillError(
                        ErrorCode.ELEMENT_NOT_FOUND,
                        "Unable to execute the declared workflow query",
                        stage="NAVIGATING",
                        repairable=True,
                    )
                await self._reject_unexpected_dialog(dialogs_supported)
                current = await self.adapter.snapshot(interactive=True, diff=True)
                if current.url:
                    self.policy.require_url_allowed(current.url, template)
        return current

    async def _ensure_browser_ready(self) -> BrowserCapabilities:
        status = await self.adapter.status()
        if not status.ok:
            raise SkillError(
                ErrorCode.EXTENSION_OFFLINE,
                "Chrome 扩展未连接，请确认 Chrome 已打开且扩展已启用",
                retryable=True,
            )
        capabilities = await self.adapter.capabilities()
        if not capabilities.snapshot:
            raise SkillError(
                ErrorCode.CHROME_USE_UNAVAILABLE,
                "浏览器快照能力暂不可用，请稍后重试",
                retryable=True,
            )
        return capabilities

    async def _reject_unexpected_dialog(self, supported: bool) -> None:
        if not supported:
            return
        result = await self.adapter.get_dialog_status()
        if not result.ok:
            raise SkillError(
                ErrorCode.CHROME_USE_UNAVAILABLE,
                "Unable to inspect browser dialog state",
                stage="dialog",
                retryable=True,
            )
        data = result.data
        is_open = False
        if isinstance(data, dict):
            is_open = bool(data.get("open") or data.get("present")) or str(
                data.get("status", "")
            ).casefold() in {"open", "present", "visible"}
        elif isinstance(data, str):
            is_open = data.strip().casefold() in {"open", "present", "visible", "true"}
        if is_open:
            await self.adapter.dismiss_dialog()
            raise SkillError(
                ErrorCode.ACTION_NOT_ALLOWED,
                "An unexpected browser dialog was dismissed; template execution stopped",
                stage="dialog",
                repairable=True,
            )

    @staticmethod
    def _interpolate(value: str, variables: dict[str, Any]) -> str:
        for key, item in variables.items():
            value = value.replace("${" + key + "}", str(item))
        return value

    def _transition(
        self,
        workspace: RunWorkspace,
        context: RunContext,
        state: RunState,
        *,
        page_url: str | None = None,
    ) -> None:
        if self.run_store.cancellation_requested(context.run_id):
            context.state = RunState.CANCELLED
            context.finished_at = datetime.now(UTC)
            self._persist_context(workspace, context)
            raise SkillError(
                ErrorCode.RUN_CANCELLED,
                "Run was cancelled by the user",
                stage=context.state.value,
            )
        if not can_transition(context.state, state):
            raise SkillError(
                ErrorCode.VALIDATION_FAILED,
                f"Illegal run transition: {context.state} -> {state}",
            )
        context.state = state
        checkpoint = Checkpoint(state=state, page_url=page_url, record_offset=len(context.records))
        context.checkpoints.append(checkpoint)
        workspace.append_jsonl("checkpoints.jsonl", checkpoint.model_dump(mode="json"))
        self._persist_context(workspace, context)
        self._event(workspace, context, "state_changed")

    @staticmethod
    def _event(workspace: RunWorkspace, context: RunContext, event: str, **data: Any) -> None:
        workspace.append_jsonl(
            "execution.jsonl",
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "run_id": context.run_id,
                "template_id": context.template_id,
                "template_version": context.template_version,
                "state": context.state.value,
                "event": event,
                **data,
            },
        )

    def _persist_context(self, workspace: RunWorkspace, context: RunContext) -> None:
        payload = context.model_dump(mode="json")
        payload["variables"] = self.variables.redacted(context.template_snapshot, context.variables)
        workspace.atomic_json("run.json", payload)

    def _write_failure_summary(
        self,
        workspace: RunWorkspace,
        context: RunContext,
        error: SkillError,
    ) -> None:
        try:
            self.output_writer.write_summary(context, error=error.as_dict())
        except SkillError as summary_error:
            self._event(
                workspace,
                context,
                "summary_write_failed",
                error=summary_error.as_dict(),
            )
