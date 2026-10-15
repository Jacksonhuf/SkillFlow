from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from browser_skill.acquire.network import NetworkDiscovery, parse_exchanges
from browser_skill.browser.base import BrowserAdapter
from browser_skill.errors import ErrorCode, SkillError
from browser_skill.execution_contract import contract_payload
from browser_skill.interaction.contracts import (
    auth_required_interaction,
    error_interaction,
    mapping_review_interaction,
    metrics_interaction,
    platform_probe_interaction,
    run_result_interaction,
    run_status_interaction,
    sample_review_interaction,
    template_menu_interaction,
    template_review_interaction,
    url_probe_interaction,
    variable_form_interaction,
)
from browser_skill.interaction.template_menu import TemplateMenu
from browser_skill.interaction.value_files import apply_values_file
from browser_skill.interaction.variables import VariableResolver
from browser_skill.models import (
    AuthState,
    BrowserCapabilities,
    BrowserTemplate,
    DeliverySpec,
    MappingDiscoveryReport,
    RunState,
    SkillRequest,
    SkillResponse,
    TemplateStatus,
)
from browser_skill.outputs.paths import contained_path
from browser_skill.outputs.writer import RunWorkspace
from browser_skill.pipeline.deliver import delivery_channel_summaries, delivery_spec_from_webhook
from browser_skill.pipeline.webhook_auth import webhook_secret_from_options
from browser_skill.platform.acceptance import validate_acceptance_bundle
from browser_skill.platform.probe import probe_adapter
from browser_skill.runtime.auto_repair import AutoRepairService
from browser_skill.runtime.batch import batch_retry_values
from browser_skill.runtime.lifecycle import TemplateLifecycleService
from browser_skill.runtime.list_navigation import reconcile_list_nav_steps_with_snapshot
from browser_skill.runtime.pick_reconcile import reconcile_picks_with_snapshot
from browser_skill.runtime.probe_compiler import ProbeDraftCompiler
from browser_skill.runtime.recovery import RunRecoveryService
from browser_skill.runtime.repair import RepairService
from browser_skill.runtime.run_store import RunStore
from browser_skill.runtime.runner import Runner
from browser_skill.runtime.sample_alignment import SampleAligner
from browser_skill.runtime.sample_analyzer import SampleAnalyzer
from browser_skill.runtime.teach import TeachCompiler
from browser_skill.runtime.teach_explorer import TeachExplorer
from browser_skill.runtime.url_probe import UrlProber
from browser_skill.telemetry.metrics import RunMetricsAggregator
from browser_skill.templates.store import TemplateStore


class BrowserSkillApp:
    def __init__(
        self,
        templates_root: Path,
        runs_root: Path,
        adapter: BrowserAdapter,
        samples_root: Path | None = None,
    ) -> None:
        self.store = TemplateStore(templates_root)
        self.adapter = adapter
        self.runs_root = runs_root.resolve()
        self.samples_root = (samples_root or runs_root / "uploads").resolve()
        self.samples_root.mkdir(parents=True, exist_ok=True)
        self.runner = Runner(adapter, runs_root)
        self.lifecycle = TemplateLifecycleService(self.store, runs_root)
        self.run_store = RunStore(runs_root)

    async def handle(self, request: SkillRequest) -> SkillResponse:
        try:
            return await self._handle(request)
        except SkillError as exc:
            interaction = error_interaction(
                exc.message,
                code=exc.code.value,
                details=exc.details,
            )
            return SkillResponse(
                ok=False,
                message=exc.message,
                data={
                    "error": exc.as_dict(),
                    "interaction": interaction.model_dump(mode="json"),
                },
            )

    async def _learn_network_sources(
        self,
        template: BrowserTemplate,
        report: MappingDiscoveryReport,
        capabilities: BrowserCapabilities,
    ) -> dict[str, Any]:
        """Upgrade list-field mappings to a learned JSON endpoint when the browser exposes one."""
        if not capabilities.network:
            return {"enabled": False, "reason": "network capture unsupported"}
        result = await self.adapter.network_requests()
        if not result.ok:
            return {"enabled": True, "learned": False, "reason": "network listing failed"}
        exchanges = parse_exchanges(result.data)
        discovery = NetworkDiscovery().discover(template, exchanges)
        if not discovery.mappings:
            return {
                "enabled": True,
                "learned": False,
                "exchanges_considered": discovery.exchanges_considered,
            }
        report.learned.field_mappings.update(discovery.mappings)
        for key in discovery.mappings:
            if key in report.missing_required_fields:
                report.missing_required_fields.remove(key)
            if key not in report.matched_fields:
                report.matched_fields.append(key)
        return {
            "enabled": True,
            "learned": True,
            "endpoint": discovery.endpoint,
            "array_path": discovery.array_path,
            "fields": discovery.matched_fields,
            "exchanges_considered": discovery.exchanges_considered,
        }

    async def _handle(self, request: SkillRequest) -> SkillResponse:
        if request.action == "start":
            templates = self.store.list()
            interaction = template_menu_interaction(templates)
            return SkillResponse(
                ok=True,
                message="可用模板",
                data={
                    "execution_contract": contract_payload(),
                    "interaction": interaction.model_dump(mode="json"),
                    "templates": [
                        {"display_index": index, **asdict(item)}
                        for index, item in enumerate(templates, 1)
                    ],
                },
            )
        if request.action == "resume":
            if not request.run_id:
                return SkillResponse(ok=False, message="恢复任务需要 run_id")
            workspace = (self.runs_root / request.run_id).resolve()
            if self.runs_root not in workspace.parents:
                return SkillResponse(ok=False, message="run_id 无效")
            response = await self.runner.resume(workspace, request.variables)
            if response.run_id and response.state == RunState.WAIT_USER_AUTH:
                interaction = auth_required_interaction(
                    response.run_id,
                    str(response.data.get("auth_state", "unknown")),
                )
            elif response.run_id and response.state:
                interaction = run_result_interaction(
                    run_id=response.run_id,
                    state=response.state,
                    message=response.message,
                    data=response.data,
                )
            else:
                return response
            response.data["interaction"] = interaction.model_dump(mode="json")
            return response
        if request.action == "retry_batch":
            return await self._retry_batch(request)
        if request.action in {"status", "cancel"}:
            if not request.run_id:
                return SkillResponse(ok=False, message="操作需要 run_id")
            context = (
                self.run_store.cancel(request.run_id)
                if request.action == "cancel"
                else self.run_store.load(request.run_id)
            )
            interaction = run_status_interaction(context)
            return SkillResponse(
                ok=True,
                message="已提交取消请求" if request.action == "cancel" else "任务状态已读取",
                run_id=context.run_id,
                state=context.state,
                data={"interaction": interaction.model_dump(mode="json")},
            )
        if request.action == "probe":
            probe_report = await probe_adapter(self.adapter, mode=request.probe_mode)
            interaction = platform_probe_interaction(probe_report)
            return SkillResponse(
                ok=probe_report.ready,
                message="平台能力探针已完成" if probe_report.ready else "平台能力探针未通过",
                data={
                    "probe": probe_report.model_dump(mode="json"),
                    "interaction": interaction.model_dump(mode="json"),
                },
            )
        if request.action == "probe_expand_clicks":
            mode = request.expand_click_recording
            if mode not in {"start", "stop"}:
                return SkillResponse(ok=False, message="需要 expand_click_recording: start 或 stop")
            await self.runner.ensure_browser_ready()
            if mode == "start":
                if request.url:
                    opened = await self.adapter.open(request.url.strip())
                    if not opened.ok:
                        return SkillResponse(
                            ok=False,
                            message="无法打开示例页面，请检查地址或先在 Chrome 登录",
                        )
                start = getattr(self.adapter, "start_expand_click_recording", None)
                if not callable(start):
                    return SkillResponse(
                        ok=False,
                        message="当前浏览器引擎不支持录制点击，请使用 Playwright 引擎",
                    )
                result = await start()
                expand_data: dict[str, Any] = (
                    dict(result.data) if isinstance(result.data, dict) else {}
                )
                try:
                    snapshot = await self.adapter.snapshot(interactive=True)
                    expand_data["cross_origin_iframes"] = int(
                        (snapshot.meta or {}).get("cross_origin_iframes") or 0
                    )
                except Exception:
                    expand_data.setdefault("cross_origin_iframes", 0)
                return SkillResponse(
                    ok=result.ok,
                    message="已开始录制：请在 Chrome 点击要展开的按钮，再点「结束录制」",
                    data=expand_data,
                )
            stop = getattr(self.adapter, "stop_expand_click_recording", None)
            if not callable(stop):
                return SkillResponse(ok=False, message="当前浏览器引擎不支持录制点击")
            result = await stop()
            clicks = []
            if isinstance(result.data, dict):
                raw = result.data.get("clicks")
                if isinstance(raw, list):
                    clicks = [str(item) for item in raw if str(item).strip()]
            return SkillResponse(
                ok=result.ok,
                message=f"录制结束，共 {len(clicks)} 个步骤",
                data={"clicks": clicks},
            )
        if request.action == "probe_list_navigation":
            mode = request.list_nav_recording
            if mode not in {"start", "stop"}:
                return SkillResponse(ok=False, message="需要 list_nav_recording: start 或 stop")
            await self.runner.ensure_browser_ready()
            if mode == "start":
                if request.url:
                    opened = await self.adapter.open(request.url.strip())
                    if not opened.ok:
                        return SkillResponse(
                            ok=False,
                            message="无法打开列表页，请检查地址或先在 Chrome 登录",
                        )
                start = getattr(self.adapter, "start_list_nav_recording", None)
                if not callable(start):
                    return SkillResponse(
                        ok=False,
                        message="当前浏览器引擎不支持列表导航录制，请使用 Playwright 引擎",
                    )
                result = await start()
                start_data: dict[str, Any] = (
                    dict(result.data) if isinstance(result.data, dict) else {}
                )
                try:
                    snapshot = await self.adapter.snapshot(interactive=True)
                    start_data["cross_origin_iframes"] = int(
                        (snapshot.meta or {}).get("cross_origin_iframes") or 0
                    )
                except Exception:
                    start_data.setdefault("cross_origin_iframes", 0)
                return SkillResponse(
                    ok=result.ok,
                    message="请依次点击：① 搜索输入框 ② 搜索/查询按钮（可选 ③ 结果行「详情」链接）",
                    data=start_data,
                )
            stop = getattr(self.adapter, "stop_list_nav_recording", None)
            if not callable(stop):
                return SkillResponse(ok=False, message="当前浏览器引擎不支持列表导航录制")
            result = await stop()
            steps: list[dict[str, Any]] = []
            if isinstance(result.data, dict) and isinstance(result.data.get("steps"), list):
                steps = [item for item in result.data["steps"] if isinstance(item, dict)]
            realigned = 0
            snapshot_refreshed = False
            try:
                snapshot = await self.adapter.snapshot(interactive=True)
                snapshot_refreshed = True
                steps, realigned = reconcile_list_nav_steps_with_snapshot(steps, snapshot)
            except Exception:
                pass
            semantics = _list_nav_semantics_from_steps(steps)
            message = f"录制结束：{len(steps)} 步"
            if snapshot_refreshed and realigned:
                message += f"（已刷新快照并对齐 {realigned} 个 ref）"
            elif snapshot_refreshed:
                message += "（已刷新快照）"
            return SkillResponse(
                ok=result.ok,
                message=message,
                data={
                    "steps": steps,
                    **semantics,
                    "snapshot_refreshed": snapshot_refreshed,
                    "refs_realigned": realigned,
                },
            )
        if request.action == "probe_field_pick":
            mode = request.field_pick_recording
            if mode not in {"start", "stop"}:
                return SkillResponse(ok=False, message="需要 field_pick_recording: start 或 stop")
            await self.runner.ensure_browser_ready()
            if mode == "start":
                if request.url:
                    opened = await self.adapter.open(request.url.strip())
                    if not opened.ok:
                        return SkillResponse(
                            ok=False,
                            message="无法打开示例页面，请检查地址或先在 Chrome 登录",
                        )
                start = getattr(self.adapter, "start_field_pick_recording", None)
                if not callable(start):
                    return SkillResponse(
                        ok=False,
                        message="当前浏览器引擎不支持点选字段，请使用 Playwright 引擎",
                    )
                result = await start()
                payload: dict[str, Any] = dict(result.data) if isinstance(result.data, dict) else {}
                try:
                    snapshot = await self.adapter.snapshot(interactive=True)
                    payload["cross_origin_iframes"] = int(
                        (snapshot.meta or {}).get("cross_origin_iframes") or 0
                    )
                except Exception:
                    payload.setdefault("cross_origin_iframes", 0)
                return SkillResponse(
                    ok=result.ok,
                    message="点选模式已开启：在 Chrome 里点击要采集的字段值，再点「结束点选」",
                    data=payload,
                )
            stop = getattr(self.adapter, "stop_field_pick_recording", None)
            if not callable(stop):
                return SkillResponse(ok=False, message="当前浏览器引擎不支持点选字段")
            result = await stop()
            raw_picks: list[dict[str, Any]] = []
            if isinstance(result.data, dict) and isinstance(result.data.get("picks"), list):
                raw_picks = [item for item in result.data["picks"] if isinstance(item, dict)]
            realigned = 0
            snapshot_refreshed = False
            try:
                snapshot = await self.adapter.snapshot(interactive=True)
                snapshot_refreshed = True
                raw_picks, realigned = reconcile_picks_with_snapshot(raw_picks, snapshot)
            except Exception:
                pass
            fields = _field_candidates_from_picks(raw_picks)
            message = f"点选结束，识别 {len(fields)} 个字段"
            if snapshot_refreshed and realigned:
                message += f"（已刷新快照并对齐 {realigned} 个 ref）"
            elif snapshot_refreshed:
                message += "（已刷新快照）"
            return SkillResponse(
                ok=result.ok,
                message=message,
                data={
                    "picks": raw_picks,
                    "fields": fields,
                    "snapshot_refreshed": snapshot_refreshed,
                    "refs_realigned": realigned,
                },
            )
        if request.action == "probe_url":
            if not request.url:
                return SkillResponse(ok=False, message="探测需要 url")
            capabilities = await self.runner.ensure_browser_ready()
            probe = await UrlProber(auth=self.runner.auth).probe(
                self.adapter, request.url, capabilities=capabilities
            )
            interaction = url_probe_interaction(probe)
            authenticated = probe.auth_state != AuthState.UNAUTHENTICATED
            return SkillResponse(
                ok=authenticated,
                message=(
                    f"探测完成：{len(probe.fields)} 个字段候选、{len(probe.attachments)} 个附件候选"
                    if authenticated
                    else "页面需要登录，请在 Chrome 中登录后重新探测"
                ),
                data={
                    "probe": probe.model_dump(mode="json"),
                    "interaction": interaction.model_dump(mode="json"),
                },
            )
        if request.action == "create_from_probe":
            if request.probe_draft is None:
                return SkillResponse(ok=False, message="创建模板需要 probe_draft")
            probe_draft = request.probe_draft
            draft = ProbeDraftCompiler().compile(
                probe_draft, version=self.store.next_version(probe_draft.template_id)
            )
            path = self.store.save(draft)
            interaction = template_review_interaction(draft, mode="teach")
            return SkillResponse(
                ok=True,
                message="模板草稿已创建，请用示例值试跑",
                data={
                    "template_id": draft.template_id,
                    "version": draft.version,
                    "relative_path": path.relative_to(self.store.root).as_posix(),
                    "driver_variable": draft.run.driver_variable,
                    "url_template": draft.system.url_template,
                    "interaction": interaction.model_dump(mode="json"),
                },
            )
        if request.action == "validate_acceptance":
            if request.acceptance_bundle_path is None:
                return SkillResponse(ok=False, message="验收证据包需要 acceptance_bundle_path")
            bundle_path = request.acceptance_bundle_path.resolve()
            if not bundle_path.is_file():
                return SkillResponse(ok=False, message="验收证据包路径无效")
            result = validate_acceptance_bundle(
                bundle_path,
                require_sign_off=request.confirmed,
            )
            return SkillResponse(
                ok=result.ok,
                message="验收证据包校验通过" if result.ok else "验收证据包校验失败",
                data=result.model_dump(mode="json"),
            )
        if request.action == "metrics":
            metrics_report = RunMetricsAggregator(self.runs_root).aggregate(
                template_id=request.template_id
            )
            interaction = metrics_interaction(metrics_report)
            return SkillResponse(
                ok=True,
                message="运行指标已汇总",
                data={
                    "metrics": metrics_report.model_dump(mode="json"),
                    "interaction": interaction.model_dump(mode="json"),
                },
            )
        if request.action == "recover":
            if not request.run_id:
                return SkillResponse(ok=False, message="恢复中断任务需要 run_id")
            recovered = await RunRecoveryService(self.adapter, self.runs_root).recover(
                request.run_id,
                confirmed=request.confirmed,
            )
            child = recovered.child
            if child.run_id and child.state == RunState.WAIT_USER_AUTH:
                interaction = auth_required_interaction(
                    child.run_id,
                    str(child.data.get("auth_state", "unknown")),
                )
            elif child.run_id and child.state:
                interaction = run_result_interaction(
                    run_id=child.run_id,
                    state=child.state,
                    message=child.message,
                    data=child.data,
                )
            else:
                return child
            child.data.update(
                {
                    "interrupted_run_id": recovered.interrupted.run_id,
                    "interaction": interaction.model_dump(mode="json"),
                }
            )
            return child
        if request.action == "analyze_sample":
            if request.sample_path is None:
                return SkillResponse(ok=False, message="分析样例需要 sample_path")
            path = contained_path(self.samples_root, *request.sample_path.parts)
            inference = SampleAnalyzer().analyze(path)
            interaction = sample_review_interaction(inference)
            return SkillResponse(
                ok=True,
                message="样例分析完成，请确认推导结果",
                data={
                    "inference": inference.model_dump(mode="json"),
                    "interaction": interaction.model_dump(mode="json"),
                },
            )
        if request.action == "create":
            if request.draft is None:
                return SkillResponse(ok=False, message="创建模板需要 draft 定义")
            draft_input = request.draft
            draft = TeachCompiler().compile_draft(
                template_id=draft_input.template_id,
                name=draft_input.name,
                entry_url=str(draft_input.entry_url),
                description=draft_input.description,
                fields=draft_input.fields,
                attachments=draft_input.attachments,
                variables=draft_input.variables,
                record_key=draft_input.record_key,
                page_hints=draft_input.page_hints,
                version=self.store.next_version(draft_input.template_id),
            )
            path = self.store.save(draft)
            interaction = template_review_interaction(draft, mode="teach")
            return SkillResponse(
                ok=True,
                message="模板草稿已创建",
                data={
                    "template_id": draft.template_id,
                    "version": draft.version,
                    "relative_path": path.relative_to(self.store.root).as_posix(),
                    "interaction": interaction.model_dump(mode="json"),
                },
            )
        if request.action == "discover":
            if not request.template_id or request.version is None:
                return SkillResponse(ok=False, message="Mapping 发现需要 template_id 和 version")
            template = self.store.load(
                request.template_id,
                request.version,
                require_published=False,
            )
            status = await self.adapter.status()
            capabilities = await self.adapter.capabilities()
            if not status.ok or not capabilities.snapshot:
                raise SkillError(
                    ErrorCode.CHROME_USE_UNAVAILABLE,
                    "浏览器快照能力暂不可用，请稍后重试",
                    stage="discovery",
                    retryable=True,
                )
            self.runner.policy.require_url_allowed(str(template.system.entry_url), template)
            opened = await self.adapter.open(str(template.system.entry_url))
            if not opened.ok:
                raise SkillError(ErrorCode.PAGE_NOT_FOUND, "无法打开模板入口页面")
            snapshot = await self.adapter.snapshot(interactive=True)
            auth_state = self.runner.auth.classify(template.auth, snapshot)
            if auth_state != AuthState.AUTHENTICATED:
                raise SkillError(
                    ErrorCode.AUTH_REQUIRED,
                    "请先在 Chrome 中完成登录，再继续 Mapping 发现",
                    stage="discovery",
                    details={"auth_state": auth_state.value},
                )
            exploration = await TeachExplorer().explore(self.adapter, template, snapshot)
            report = exploration.report
            network_summary = await self._learn_network_sources(template, report, capabilities)
            candidate_version: int | None = None
            if report.publishable_candidate:
                candidate_version = self.store.next_version(template.template_id)
                candidate = template.model_copy(
                    update={
                        "version": candidate_version,
                        "status": TemplateStatus.TESTING,
                        "learned": report.learned,
                    },
                    deep=True,
                )
                self.store.save(candidate)
            interaction = mapping_review_interaction(
                report,
                candidate_version=candidate_version,
            )
            return SkillResponse(
                ok=report.publishable_candidate,
                message=(
                    "Mapping 候选版本已创建"
                    if candidate_version is not None
                    else "必填目标尚未全部找到"
                ),
                data={
                    "report": report.model_dump(mode="json"),
                    "candidate_version": candidate_version,
                    "exploration": {
                        "visited_urls": exploration.visited_urls,
                        "attempted_hints": exploration.attempted_hints,
                        "steps": exploration.steps,
                        "budget_exhausted": exploration.budget_exhausted,
                    },
                    "network": network_summary,
                    "interaction": interaction.model_dump(mode="json"),
                },
            )
        if request.action == "update_delivery":
            if not request.template_id or request.version is None:
                return SkillResponse(
                    ok=False,
                    message="update_delivery 需要 template_id 与 version",
                )
            template = self.store.load(
                request.template_id,
                request.version,
                require_published=False,
            )
            if template.status == TemplateStatus.PUBLISHED and not request.fork_as_new_version:
                return SkillResponse(
                    ok=False,
                    message=(
                        "已发布版本不可就地修改；请加 fork_as_new_version 或 CLI --fork 创建草稿"
                    ),
                )
            try:
                delivery, report_enabled = self._delivery_update_spec(template, request)
            except ValueError as exc:
                return SkillResponse(ok=False, message=str(exc))
            report_spec = template.report.model_copy(update={"enabled": report_enabled})
            forked_from: int | None = None
            if template.status == TemplateStatus.PUBLISHED:
                forked_from = template.version
                new_version = self.store.next_version(request.template_id)
                updated = template.model_copy(
                    update={
                        "version": new_version,
                        "status": TemplateStatus.DRAFT,
                        "delivery": delivery,
                        "report": report_spec,
                    },
                    deep=True,
                )
                self.store.save(updated)
                message = (
                    f"已基于 v{forked_from} 创建草稿 v{new_version}，分发配置已写入"
                )
            else:
                updated = self.store.patch_delivery(
                    request.template_id,
                    request.version,
                    delivery=delivery,
                    report=report_spec,
                )
                message = "分发配置已保存"
            cli = _update_delivery_cli(request, delivery)
            data: dict[str, Any] = {
                "template_id": updated.template_id,
                "version": updated.version,
                "delivery_channels": delivery_channel_summaries(updated.delivery),
                "pipeline": {
                    "report": updated.report.enabled,
                    "delivery": updated.delivery.enabled,
                },
                "cli": cli,
                "invoke_cli": cli.replace("browser-skill", "py scripts/invoke.py", 1),
            }
            if forked_from is not None:
                data["forked_from_version"] = forked_from
            return SkillResponse(ok=True, message=message, data=data)
        if request.action == "publish":
            if not request.template_id or request.version is None or not request.run_id:
                return SkillResponse(
                    ok=False,
                    message="发布需要 template_id、version 和通过测试的 run_id",
                )
            published = self.lifecycle.publish(
                request.template_id,
                request.version,
                test_run_id=request.run_id,
                confirmed=request.confirmed,
            )
            interaction = template_review_interaction(published, mode="published")
            interaction.title = "模板已发布"
            interaction.actions = ["run_template"]
            return SkillResponse(
                ok=True,
                message="模板已发布",
                data={
                    "template_id": published.template_id,
                    "version": published.version,
                    "interaction": interaction.model_dump(mode="json"),
                },
            )
        if request.action == "repair":
            if request.run_id:
                repaired = await AutoRepairService(
                    self.adapter,
                    self.store,
                    self.runs_root,
                ).repair(request.run_id)
                interaction = run_status_interaction(repaired)
                return SkillResponse(
                    ok=True,
                    message="Repair 测试通过，新版本已发布并恢复原任务",
                    run_id=repaired.run_id,
                    state=repaired.state,
                    data={
                        "recovery_run_id": repaired.recovery_run_id,
                        "repaired_template_version": repaired.repaired_template_version,
                        "interaction": interaction.model_dump(mode="json"),
                    },
                )
            if not request.template_id or request.learned is None:
                return SkillResponse(ok=False, message="Repair 需要 template_id 和 learned 数据")
            original = self.store.load(request.template_id)
            candidate = RepairService().candidate(
                original,
                request.learned,
                version=self.store.next_version(request.template_id),
            )
            if not RepairService().contract_unchanged(original, candidate):
                return SkillResponse(ok=False, message="Repair 不得修改业务契约")
            path = self.store.save(candidate)
            interaction = template_review_interaction(candidate, mode="repair")
            return SkillResponse(
                ok=True,
                message="Repair 候选版本已创建",
                data={
                    "template_id": candidate.template_id,
                    "version": candidate.version,
                    "relative_path": path.relative_to(self.store.root).as_posix(),
                    "interaction": interaction.model_dump(mode="json"),
                },
            )
        selector: str | int | None = request.template_id or request.selector
        if selector is None:
            return SkillResponse(ok=False, message="请选择模板")
        template_id = TemplateMenu(
            self.store.list(include_unpublished=request.action == "test")
        ).resolve(selector)
        if template_id is None:
            return SkillResponse(ok=False, message="请使用 Teach 模式创建模板")
        template = self.store.load(
            template_id,
            require_published=request.action != "test",
        )
        if request.action in {"run", "test"}:
            if request.values_file is not None:
                apply_values_file(
                    template,
                    request.variables,
                    request.values_file,
                    column=request.values_column,
                    name=request.values_variable,
                )
            missing = VariableResolver().missing(template, request.variables)
            if missing:
                interaction = variable_form_interaction(template, missing)
                return SkillResponse(
                    ok=False,
                    message="缺少必填变量",
                    data={"interaction": interaction.model_dump(mode="json")},
                )
            response = await self.runner.run(template, request.variables)
            if request.action == "test" and request.sample_path is not None and response.run_id:
                self._attach_sample_alignment(response, template, request.sample_path)
            if response.run_id and response.state == RunState.WAIT_USER_AUTH:
                interaction = auth_required_interaction(
                    response.run_id,
                    str(response.data.get("auth_state", "unknown")),
                )
            elif response.run_id and response.state:
                interaction = run_result_interaction(
                    run_id=response.run_id,
                    state=response.state,
                    message=response.message,
                    data=response.data,
                )
            else:
                return response
            response.data["interaction"] = interaction.model_dump(mode="json")
            return response
        return SkillResponse(ok=False, message=f"动作尚需交互流程：{request.action}")

    async def _retry_batch(self, request: SkillRequest) -> SkillResponse:
        if not request.run_id:
            return SkillResponse(ok=False, message="retry_batch 需要 run_id（先前批量运行）")
        prior = self.run_store.load(request.run_id)
        batch_path = self.run_store.workspace(request.run_id) / "batch.json"
        if not batch_path.is_file():
            return SkillResponse(ok=False, message="该运行没有 batch.json，无法按原因重跑")
        try:
            batch_payload = json.loads(batch_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return SkillResponse(ok=False, message="batch.json 无法读取")
        if not isinstance(batch_payload, dict):
            return SkillResponse(ok=False, message="batch.json 格式无效")
        bucket = request.failure_bucket or "failed"
        values = batch_retry_values(batch_payload, bucket=request.failure_bucket)
        if not values:
            return SkillResponse(ok=False, message=f"分类「{bucket}」下没有可重跑的编号")
        template = self.store.load(prior.template_id, require_published=True)
        driver = str(batch_payload.get("driver_variable") or template.run.driver_variable or "")
        if not driver:
            return SkillResponse(ok=False, message="无法确定驱动变量")
        variables = dict(prior.variables)
        variables.update(request.variables)
        variables[driver] = values
        response = await self.runner.run(template, variables)
        response.data["retry_batch"] = {
            "prior_run_id": request.run_id,
            "failure_bucket": bucket,
            "driver": driver,
            "values": values,
        }
        if response.run_id and response.state:
            interaction = run_result_interaction(
                run_id=response.run_id,
                state=response.state,
                message=response.message,
                data=response.data,
            )
            response.data["interaction"] = interaction.model_dump(mode="json")
        return response

    def _attach_sample_alignment(
        self, response: SkillResponse, template: BrowserTemplate, sample_path: Path
    ) -> None:
        """Teach test with a sample: compare what the user wants with what the run produced."""
        assert response.run_id is not None
        path = contained_path(self.samples_root, *sample_path.parts)
        run_dir = self.runs_root / response.run_id
        records: list[dict[str, Any]] = []
        run_file = run_dir / "run.json"
        if run_file.is_file():
            payload = json.loads(run_file.read_text(encoding="utf-8"))
            records = [r for r in payload.get("records", []) if isinstance(r, dict)]
        report = SampleAligner().align(template, path, records)
        data = report.model_dump(mode="json")
        data["aligned"] = report.aligned
        if run_dir.is_dir():
            RunWorkspace.existing(run_dir).atomic_json("sample_alignment.json", data)
        response.data["sample_alignment"] = data
        if not report.aligned and response.ok:
            response.message = f"{response.message}；样例比对发现 {len(report.issues)} 个差异"

    @staticmethod
    def _delivery_update_spec(
        template: BrowserTemplate, request: SkillRequest
    ) -> tuple[DeliverySpec, bool]:
        if request.disable_delivery:
            return delivery_spec_from_webhook(None, None, disable=True), False
        existing_url = ""
        existing_secret: str | None = None
        for channel in template.delivery.channels:
            if channel.type == "webhook" and channel.enabled:
                existing_url = channel.target
                existing_secret = webhook_secret_from_options(channel.options)
                break
        url = (request.webhook_url or "").strip() or existing_url
        if not url:
            raise ValueError("请填写 webhook_url，或先通过 Teach 配置分发")
        secret_input = request.webhook_secret
        secret = existing_secret if secret_input is None else secret_input.strip() or None
        delivery = delivery_spec_from_webhook(url, secret)
        return delivery, delivery.enabled


def _update_delivery_cli(request: SkillRequest, delivery: DeliverySpec) -> str:
    base = (
        f"browser-skill update-delivery {request.template_id} --version {request.version}"
    )
    if request.fork_as_new_version:
        base = f"{base} --fork"
    if request.disable_delivery:
        return f"{base} --disable"
    target = delivery.channels[0].target if delivery.channels else (request.webhook_url or "")
    return f"{base} --webhook-url {target}"


def _list_nav_step_ref(step: dict[str, Any]) -> str | None:
    ref = str(step.get("ref") or "").strip()
    if ref.startswith("@e"):
        return ref
    return None


def _list_nav_semantics_from_steps(steps: list[dict[str, Any]]) -> dict[str, Any]:
    inputs: list[str] = []
    actions: list[str] = []
    rows: list[str] = []
    input_ref: str | None = None
    action_ref: str | None = None
    row_ref: str | None = None
    input_frame: int | None = None
    action_frame: int | None = None
    row_frame: int | None = None
    for step in steps:
        label = str(step.get("label") or "").strip()
        if not label:
            continue
        kind = str(step.get("kind") or "action")
        ref = _list_nav_step_ref(step)
        frame_raw = step.get("frame_index")
        frame = frame_raw if isinstance(frame_raw, int) and frame_raw >= 0 else None
        if kind == "input":
            inputs.append(label)
            if input_ref is None and ref:
                input_ref = ref
                input_frame = frame
        elif kind == "row":
            rows.append(label)
            if row_ref is None and ref:
                row_ref = ref
                row_frame = frame
        else:
            actions.append(label)
            if action_ref is None and ref:
                action_ref = ref
                action_frame = frame
    return {
        "list_nav_input_semantic": inputs,
        "list_nav_action_semantic": actions,
        "list_nav_row_semantic": rows,
        "list_nav_input_ref": input_ref,
        "list_nav_action_ref": action_ref,
        "list_nav_row_ref": row_ref,
        "list_nav_input_label": inputs[0] if inputs else None,
        "list_nav_action_label": actions[0] if actions else None,
        "list_nav_row_label": rows[0] if rows else None,
        "list_nav_input_frame_index": input_frame,
        "list_nav_action_frame_index": action_frame,
        "list_nav_row_frame_index": row_frame,
    }


def _field_candidates_from_picks(picks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_keys: set[str] = set()
    fields: list[dict[str, Any]] = []
    for pick in picks:
        ref = str(pick.get("ref") or "").strip()
        if not ref.startswith("@e"):
            continue
        text = str(pick.get("text") or "").strip()
        label = str(pick.get("label") or "").strip()
        name = label or text[:40] or "字段"
        base = re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")
        if not base or not base[0].isalpha():
            base = f"ref_{ref.lstrip('@')}" if ref.startswith("@e") else "field"
        base = base[:50]
        key = base
        suffix = 2
        while key in seen_keys:
            key = f"{base}_{suffix}"
            suffix += 1
        seen_keys.add(key)
        frame_index = pick.get("frame_index")
        frame = frame_index if isinstance(frame_index, int) and frame_index >= 0 else None
        fields.append(
            {
                "key": key,
                "name": name[:100],
                "sample": text,
                "source": "dom",
                "strategy": "label_value",
                "type": "string",
                "confidence": 0.92,
                "recommended": True,
                "dom_ref": ref,
                "frame_index": frame,
            }
        )
    return fields


def parse_variables(items: list[str]) -> dict[str, Any]:
    """Parse repeated ``name=value`` options; a name given more than once becomes a list."""
    values: dict[str, Any] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"变量必须使用 name=value 格式：{item}")
        key, value = item.split("=", 1)
        if not key:
            raise ValueError("变量名称不能为空")
        if key in values:
            previous = values[key]
            values[key] = [*previous, value] if isinstance(previous, list) else [previous, value]
        else:
            values[key] = value
    return values
