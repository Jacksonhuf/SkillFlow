from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from browser_skill.browser.base import BrowserAdapter
from browser_skill.errors import ErrorCode, SkillError
from browser_skill.models import AuthState, RunContext, RunState
from browser_skill.outputs.writer import RunWorkspace
from browser_skill.runtime.auth import AuthClassifier
from browser_skill.runtime.discovery import MappingDiscoveryService
from browser_skill.runtime.lifecycle import TemplateLifecycleService
from browser_skill.runtime.policy import ActionPolicy
from browser_skill.runtime.repair import RepairService
from browser_skill.runtime.run_store import RunStore
from browser_skill.runtime.runner import Runner
from browser_skill.templates.store import TemplateStore


class AutoRepairService:
    """Perform one contract-preserving rediscovery, full Test Run, publish, and recovery link."""

    def __init__(
        self,
        adapter: BrowserAdapter,
        store: TemplateStore,
        runs_root: Path,
    ) -> None:
        self.adapter = adapter
        self.store = store
        self.runs_root = runs_root
        self.run_store = RunStore(runs_root)
        self.lifecycle = TemplateLifecycleService(store, runs_root)

    async def repair(self, failed_run_id: str) -> RunContext:
        original = self.run_store.load(failed_run_id)
        if original.state != RunState.FAILED:
            raise SkillError(ErrorCode.REPAIR_FAILED, "Only failed Runs can enter automatic Repair")
        if original.repair_attempts >= 1:
            raise SkillError(ErrorCode.REPAIR_FAILED, "Automatic Repair is limited to one attempt")
        if any(value == "***" for value in original.variables.values()):
            raise SkillError(
                ErrorCode.VARIABLE_MISSING,
                "Sensitive variables must be supplied before Repair can rerun the task",
            )
        template = original.template_snapshot
        original.state = RunState.REPAIRING
        original.repair_attempts = 1
        self._persist(original)
        try:
            status = await self.adapter.status()
            capabilities = await self.adapter.capabilities()
            if not status.ok or not capabilities.snapshot:
                raise SkillError(
                    ErrorCode.CHROME_USE_UNAVAILABLE, "Browser is unavailable for Repair"
                )
            ActionPolicy().require_url_allowed(str(template.system.entry_url), template)
            opened = await self.adapter.open(str(template.system.entry_url))
            if not opened.ok:
                raise SkillError(
                    ErrorCode.PAGE_NOT_FOUND, "Repair could not open the template entry"
                )
            snapshot = await self.adapter.snapshot(interactive=True)
            if AuthClassifier().classify(template.auth, snapshot) != AuthState.AUTHENTICATED:
                raise SkillError(
                    ErrorCode.AUTH_REQUIRED, "Authentication is required before Repair"
                )
            report = MappingDiscoveryService().discover(template, snapshot)
            if not report.publishable_candidate:
                raise SkillError(
                    ErrorCode.REPAIR_FAILED,
                    "Repair could not rediscover all required targets",
                    details=report.model_dump(mode="json"),
                )
            candidate = RepairService().candidate(
                template,
                report.learned,
                version=self.store.next_version(template.template_id),
            )
            if not RepairService().contract_unchanged(template, candidate):
                raise SkillError(
                    ErrorCode.REPAIR_REQUIRES_TEACH, "Repair changed the business contract"
                )
            self.store.save(candidate)
            original.state = RunState.TESTING
            original.repaired_template_version = candidate.version
            self._persist(original)
            test_response = await Runner(self.adapter, self.runs_root).run(
                candidate, original.variables
            )
            if (
                not test_response.ok
                or test_response.state != RunState.COMPLETED
                or not test_response.run_id
            ):
                raise SkillError(
                    ErrorCode.REPAIR_FAILED,
                    "Repaired template did not pass its full Test Run",
                    details={"test_run_id": test_response.run_id, "state": test_response.state},
                )
            self.lifecycle.publish(
                candidate.template_id,
                candidate.version,
                test_run_id=test_response.run_id,
                confirmed=True,
            )
        except SkillError:
            original.state = RunState.FAILED
            original.finished_at = datetime.now(UTC)
            self._persist(original)
            raise
        original.state = RunState.COMPLETED
        original.recovery_run_id = test_response.run_id
        original.finished_at = datetime.now(UTC)
        self._persist(original)
        return original

    def _persist(self, context: RunContext) -> None:
        workspace = RunWorkspace.existing(self.run_store.workspace(context.run_id))
        workspace.atomic_json("run.json", context.model_dump(mode="json"))
        workspace.append_jsonl(
            "execution.jsonl",
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "run_id": context.run_id,
                "state": context.state.value,
                "event": "repair_state_changed",
                "repair_attempts": context.repair_attempts,
                "recovery_run_id": context.recovery_run_id,
                "repaired_template_version": context.repaired_template_version,
            },
        )
