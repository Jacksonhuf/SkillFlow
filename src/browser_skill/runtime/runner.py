from __future__ import annotations

import asyncio
import contextlib
import json
import random
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from browser_skill.acquire.network import NetworkExtractor, NetworkRecordSource, parse_exchanges
from browser_skill.acquire.vision import NullVisionProvider, VisionFallback, VisionProvider
from browser_skill.browser.base import BrowserAdapter
from browser_skill.errors import ErrorCode, SkillError
from browser_skill.execution_contract import contract_payload
from browser_skill.interaction.variables import VariableResolver
from browser_skill.models import (
    AcquisitionSource,
    AuthState,
    BatchItemState,
    BatchItemStatus,
    BatchProgress,
    BrowserCapabilities,
    BrowserSnapshot,
    BrowserTemplate,
    Checkpoint,
    DownloadedFile,
    DownloadStatus,
    NetworkExchange,
    RunContext,
    RunMode,
    RunState,
    SkillResponse,
    ValidationReport,
)
from browser_skill.outputs.writer import OutputWriter, RunWorkspace
from browser_skill.pipeline.analyze import AnalysisProvider
from browser_skill.pipeline.orchestrator import analyze_failed_run, finalize_pipeline
from browser_skill.pipeline.process import apply_processing
from browser_skill.runtime.auth import AuthClassifier
from browser_skill.runtime.batch import (
    ItemOutcome,
    apply_incremental_skip,
    build_progress,
    classify_item,
    extract_item_records,
    previously_completed_values,
)
from browser_skill.runtime.capability_requirements import ensure_template_runtime_capabilities
from browser_skill.runtime.detail import DetailCollector
from browser_skill.runtime.downloader import AttachmentDownloader
from browser_skill.runtime.extractor import RecordExtractor
from browser_skill.runtime.locator import LocatorService
from browser_skill.runtime.policy import ActionPolicy
from browser_skill.runtime.run_store import RunStore
from browser_skill.runtime.state_machine import can_transition
from browser_skill.runtime.url_batch import plan_batch_items
from browser_skill.runtime.validator import ResultValidator

EventHook = Callable[[dict[str, Any]], Awaitable[None]]
ProgressListener = Callable[[dict[str, Any]], None]


class _SessionExpired(Exception):
    """Raised inside the batch loop when a detail page shows the login screen."""


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
        vision_provider: VisionProvider | None = None,
        analysis_provider: AnalysisProvider | None = None,
    ) -> None:
        self.adapter = adapter
        self.analysis_provider = analysis_provider
        self.runs_root = runs_root
        self.variables = variable_resolver or VariableResolver()
        self.auth = auth_classifier or AuthClassifier()
        self.validator = validator or ResultValidator()
        # One vision fallback shared by every locator so attempts are reported once per run
        self.vision = VisionFallback(vision_provider or NullVisionProvider())
        self.locator = locator or LocatorService(vision=self.vision)
        self.downloader = downloader or AttachmentDownloader(locator=self.locator)
        self.extractor = extractor or RecordExtractor(locator=self.locator)
        self.detail_collector = detail_collector or DetailCollector(self.downloader)
        self.output_writer = output_writer or OutputWriter()
        self.policy = policy or ActionPolicy()
        self.run_store = RunStore(runs_root)
        # Optional sync observer for execution events (console job progress); never raises
        self.progress_listener: ProgressListener | None = None

    async def run(
        self,
        template: BrowserTemplate,
        supplied_variables: dict[str, Any],
        *,
        dry_run: bool = False,
    ) -> SkillResponse:
        values = self.variables.resolve(template, supplied_variables)
        # Plan detail_batch URLs before touching the browser so bad values fail fast
        batch = self._plan_batch(template, values)
        run_id = f"run_{datetime.now(UTC):%Y%m%dT%H%M%SZ}_{secrets.token_hex(4)}"
        workspace = RunWorkspace(self.runs_root, run_id)
        context = RunContext(
            run_id=run_id,
            template_id=template.template_id,
            template_version=template.version,
            template_snapshot=template,
            variables=values,
            workspace=workspace.path,
            batch=batch,
        )
        self._event(
            workspace,
            context,
            "run_created",
            variables=self.variables.redacted(template, values),
            **({"items": len(batch.items)} if batch else {}),
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
            return await self._execute_after_auth(
                workspace, context, template, snapshot, capabilities
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
            return await self._execute_after_auth(
                workspace,
                context,
                context.template_snapshot,
                snapshot,
                capabilities,
                resumed=True,
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

    async def _execute_after_auth(
        self,
        workspace: RunWorkspace,
        context: RunContext,
        template: BrowserTemplate,
        snapshot: BrowserSnapshot,
        capabilities: BrowserCapabilities,
        *,
        resumed: bool = False,
    ) -> SkillResponse:
        """Shared NAVIGATING → output pipeline for fresh and resumed runs."""
        self._transition(workspace, context, RunState.NAVIGATING, page_url=snapshot.url)
        if template.run.mode == RunMode.DETAIL_BATCH:
            self._transition(workspace, context, RunState.EXTRACTING, page_url=snapshot.url)
            paused = await self._run_batch(workspace, context, template, capabilities)
            if paused is not None:
                return paused
        else:
            snapshot = await self._apply_workflow(
                template,
                context.variables,
                snapshot,
                dialogs_supported=capabilities.dialogs,
            )
            self._transition(workspace, context, RunState.EXTRACTING, page_url=snapshot.url)
            await self._collect_list_mode(workspace, context, template, snapshot, capabilities)
        context.records = apply_processing(template, context.records)
        self._report_vision(workspace, context)
        self._transition(workspace, context, RunState.VALIDATING)
        stats = context.batch.stats() if context.batch is not None else None
        all_skipped = bool(stats and stats["total"] and stats["skipped"] == stats["total"])
        if all_skipped:
            # Nothing was (or had to be) collected: earlier runs already hold every value.
            report = ValidationReport(ok=True, record_count=0, download_count=0)
        else:
            report = self.validator.validate(
                template,
                context.records,
                context.downloaded_files,
                pagination_complete=context.pagination_complete,
            )
        if not report.ok:
            analysis = await analyze_failed_run(
                context, report, analysis_provider=self.analysis_provider
            )
            details: dict[str, Any] = {
                "validation": report.model_dump(mode="json"),
                "analysis": analysis,
            }
            if context.batch is not None:
                details["items"] = context.batch.stats()
            raise SkillError(
                ErrorCode.VALIDATION_FAILED,
                "Business-result validation failed",
                stage="VALIDATING",
                repairable=True,
                details=details,
            )
        self._transition(workspace, context, RunState.WRITING_OUTPUT)
        batch_failures = bool(context.batch and context.batch.stats()["failed"])
        final_state = RunState.PARTIAL if report.partial or batch_failures else RunState.COMPLETED
        context.state = final_state
        context.finished_at = datetime.now(UTC)
        artifacts = self.output_writer.write(context, report)
        pipeline_data = await finalize_pipeline(
            context, report, artifacts, analysis_provider=self.analysis_provider
        )
        self.output_writer.write_summary(context, report=report, artifacts=artifacts)
        self._persist_context(workspace, context)
        self._event(workspace, context, "run_finished", artifacts=artifacts)
        if all_skipped:
            message = f"全部 {stats['total'] if stats else 0} 条此前已采集，本次无需重跑"
        elif resumed:
            message = "认证后已恢复并完成任务"
        elif final_state == RunState.COMPLETED:
            message = "任务完成"
        else:
            message = "任务产生部分结果"
        if stats and stats["skipped"] and not all_skipped:
            message += f"（跳过 {stats['skipped']} 条此前已采集）"
        data: dict[str, Any] = {
            "artifacts": artifacts,
            "validation": report.model_dump(mode="json"),
            "execution_contract": contract_payload(),
            "pipeline": pipeline_data.get("pipeline"),
        }
        if context.batch is not None:
            data["items"] = context.batch.stats()
        return SkillResponse(
            ok=True,
            message=message,
            run_id=context.run_id,
            state=final_state,
            data=data,
        )

    async def _collect_list_mode(
        self,
        workspace: RunWorkspace,
        context: RunContext,
        template: BrowserTemplate,
        snapshot: BrowserSnapshot,
        capabilities: BrowserCapabilities,
    ) -> None:
        context.records, context.pagination_complete, snapshot = await self._collect_records(
            workspace, context, template, snapshot, capabilities
        )
        needs_detail = any(field.source == "detail" for field in template.target.fields) or any(
            item.source == "detail" for item in template.target.attachments
        )
        if not template.target.attachments and not needs_detail:
            return
        self._transition(workspace, context, RunState.DOWNLOADING, page_url=snapshot.url)
        list_attachments = [item for item in template.target.attachments if item.source == "list"]
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
            self._event(
                workspace,
                context,
                "detail_collection_finished",
                record_count=len(detail_result.records),
                file_count=len(detail_result.files),
                failed_record_count=len(detail_result.failed_record_keys),
            )

    def _plan_batch(
        self, template: BrowserTemplate, values: dict[str, Any]
    ) -> BatchProgress | None:
        if template.run.mode != RunMode.DETAIL_BATCH:
            return None
        driver_values = self.variables.driver_values(template, values)
        items = plan_batch_items(template, values, driver_values, policy=self.policy)
        batch = build_progress(template, items)
        if template.run.skip_if_exists:
            completed = previously_completed_values(self.runs_root, template.template_id)
            apply_incremental_skip(batch, completed)
        return batch

    async def _run_batch(
        self,
        workspace: RunWorkspace,
        context: RunContext,
        template: BrowserTemplate,
        capabilities: BrowserCapabilities,
    ) -> SkillResponse | None:
        """Visit one detail page per driver value; returns a pause response if login expired.

        Items already ``ok``/``partial`` (from a run that paused for auth) are skipped, so the
        records and files they contributed are kept from ``run.json`` rather than re-fetched.
        """
        batch = context.batch
        if batch is None:
            batch = self._plan_batch(template, context.variables)
            assert batch is not None
            context.batch = batch
        self._persist_batch(workspace, context)
        skipped = [item for item in batch.items if item.status == BatchItemStatus.SKIPPED]
        if skipped:
            self._event(
                workspace,
                context,
                "items_skipped",
                count=len(skipped),
                values=[item.value for item in skipped[:50]],
            )
        pending = [item for item in batch.items if not item.done]
        for position, item in enumerate(pending):
            self._check_cancelled(workspace, context)
            self._event(
                workspace, context, "item_started", index=item.index, value=item.value, url=item.url
            )
            try:
                outcome = await self._process_batch_item(
                    workspace,
                    template,
                    context.variables,
                    batch.driver_variable,
                    item,
                    capabilities,
                )
            except _SessionExpired:
                self._transition(workspace, context, RunState.WAIT_USER_AUTH, page_url=item.url)
                self._event(
                    workspace, context, "item_deferred", index=item.index, reason="auth_required"
                )
                return SkillResponse(
                    ok=False,
                    message="批量执行中登录已失效，请在 Chrome 中重新登录后使用此 run_id 恢复。",
                    run_id=context.run_id,
                    state=RunState.WAIT_USER_AUTH,
                    data={"auth_state": AuthState.UNAUTHENTICATED.value, "items": batch.stats()},
                )
            except SkillError as exc:
                if exc.code == ErrorCode.RUN_CANCELLED:
                    raise
                outcome = ItemOutcome(
                    status=BatchItemStatus.FAILED, reason=exc.code.value, error=exc.as_dict()
                )
            item.status = outcome.status
            item.reason = outcome.reason
            item.error = outcome.error
            item.record_count = len(outcome.records)
            item.file_count = sum(file.status == DownloadStatus.OK for file in outcome.files)
            item.finished_at = datetime.now(UTC)
            context.records.extend(outcome.records)
            context.downloaded_files.extend(outcome.files)
            self._persist_batch(workspace, context)
            self._event(
                workspace,
                context,
                "item_failed" if item.status == BatchItemStatus.FAILED else "item_finished",
                index=item.index,
                value=item.value,
                status=item.status.value,
                reason=item.reason,
                record_count=item.record_count,
                file_count=item.file_count,
            )
            if item.status == BatchItemStatus.FAILED and template.run.on_item_error == "stop":
                raise SkillError(
                    ErrorCode.FIELD_MAPPING_FAILED
                    if outcome.error is None
                    else ErrorCode(outcome.error["code"]),
                    f"批量项 {item.value} 失败，模板配置为失败即停止",
                    stage="EXTRACTING",
                    details={"items": batch.stats(), "item": item.model_dump(mode="json")},
                )
            if position + 1 < len(pending) and template.run.per_item_delay_ms:
                await asyncio.sleep(self._item_delay_seconds(template.run.per_item_delay_ms))
        stats = batch.stats()
        self._event(workspace, context, "batch_finished", **stats)
        if stats["failed"] == stats["total"] and stats["total"]:
            raise SkillError(
                ErrorCode.VALIDATION_FAILED,
                "所有批量项均失败，未产生任何记录",
                stage="EXTRACTING",
                repairable=True,
                details={"items": stats},
            )
        return None

    async def _process_batch_item(
        self,
        workspace: RunWorkspace,
        template: BrowserTemplate,
        values: dict[str, Any],
        driver: str,
        item: BatchItemState,
        capabilities: BrowserCapabilities,
    ) -> ItemOutcome:
        opened = await self.adapter.open(item.url)
        if not opened.ok:
            raise SkillError(ErrorCode.PAGE_NOT_FOUND, "无法打开详情页", stage="item")
        snapshot = await self.adapter.snapshot(interactive=True)
        if snapshot.url:
            self.policy.require_url_allowed(snapshot.url, template)
        if self.auth.classify(template.auth, snapshot) == AuthState.UNAUTHENTICATED:
            raise _SessionExpired
        snapshot = await self._apply_workflow(
            template, values, snapshot, dialogs_supported=capabilities.dialogs
        )
        exchanges: list[NetworkExchange] = []
        if capabilities.network and NetworkExtractor.network_field_mappings(template):
            listing = await self.adapter.network_requests()
            if listing.ok:
                exchanges = parse_exchanges(listing.data)
        records = extract_item_records(template, driver, item.value, snapshot, exchanges)
        files: list[DownloadedFile] = []
        if template.target.attachments and records:
            # Attachments belong to the page, not to individual table rows: download once per
            # item, named after the first record (which carries the driver value).
            owners = records[:1] if template.run.capture_tables else records
            files = await self.downloader.collect(
                self.adapter, template, snapshot, owners, workspace.path
            )
        return classify_item(template, records, files)

    @staticmethod
    def _item_delay_seconds(delay_ms: int) -> float:
        # ±30% jitter so batches do not hit the site with a fixed rhythm
        return delay_ms / 1000 * random.uniform(0.7, 1.3)

    def _persist_batch(self, workspace: RunWorkspace, context: RunContext) -> None:
        if context.batch is not None:
            payload = context.batch.model_dump(mode="json")
            payload["stats"] = context.batch.stats()
            workspace.atomic_json("batch.json", payload)
        self._persist_context(workspace, context)

    def _check_cancelled(self, workspace: RunWorkspace, context: RunContext) -> None:
        if not self.run_store.cancellation_requested(context.run_id):
            return
        context.state = RunState.CANCELLED
        context.finished_at = datetime.now(UTC)
        self._persist_context(workspace, context)
        raise SkillError(
            ErrorCode.RUN_CANCELLED, "Run was cancelled by the user", stage=context.state.value
        )

    def _report_vision(self, workspace: RunWorkspace, context: RunContext) -> None:
        if not self.vision.attempts:
            return
        attempts = list(self.vision.attempts)
        self.vision.attempts.clear()
        self._event(
            workspace,
            context,
            "vision_fallback",
            source=AcquisitionSource.VISION.value,
            provider=self.vision.provider.name,
            located=sum(item["outcome"] == "located" for item in attempts),
            attempts=attempts,
        )

    async def _collect_records(
        self,
        workspace: RunWorkspace,
        context: RunContext,
        template: BrowserTemplate,
        snapshot: BrowserSnapshot,
        capabilities: BrowserCapabilities,
    ) -> tuple[list[dict[str, Any]], bool, BrowserSnapshot]:
        """Acquisition ladder: learned network endpoint per page first, then DOM/table parsing.

        Pagination (clicks, scrolls, page budgets, cycle detection) is always driven by the
        extractor; the network source only changes where each page's records come from.
        """
        network_mappings = NetworkExtractor.network_field_mappings(template)
        if not network_mappings or not capabilities.network:
            return await self.extractor.collect(self.adapter, template, snapshot)
        source = NetworkRecordSource(self.adapter, template)
        records, complete, current = await self.extractor.collect(
            self.adapter, template, snapshot, record_source=source
        )
        if source.network_pages:
            self._event(
                workspace,
                context,
                "network_extraction",
                source=AcquisitionSource.NETWORK.value,
                record_count=len(records),
                network_pages=source.network_pages,
                dom_pages=source.dom_pages,
            )
        else:
            self._event(
                workspace,
                context,
                "network_extraction_fallback",
                reason="network_unavailable" if source.listing_failures else "no_matching_exchange",
                dom_pages=source.dom_pages,
            )
        return records, complete, current

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

    async def ensure_browser_ready(self) -> BrowserCapabilities:
        return await self._ensure_browser_ready()

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
        self._check_cancelled(workspace, context)
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

    def _event(self, workspace: RunWorkspace, context: RunContext, event: str, **data: Any) -> None:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "run_id": context.run_id,
            "template_id": context.template_id,
            "template_version": context.template_version,
            "state": context.state.value,
            "event": event,
            **data,
        }
        workspace.append_jsonl("execution.jsonl", payload)
        if self.progress_listener is not None:
            with contextlib.suppress(Exception):
                self.progress_listener(payload)

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
