from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from browser_skill.browser.base import BrowserAdapter
from browser_skill.errors import ErrorCode, SkillError
from browser_skill.models import RunContext, RunState, SkillResponse
from browser_skill.outputs.writer import OutputWriter, RunWorkspace
from browser_skill.runtime.run_store import TERMINAL_STATES, RunStore
from browser_skill.runtime.runner import Runner


@dataclass(slots=True)
class RecoveryResult:
    interrupted: RunContext
    child: SkillResponse


class RunRecoveryService:
    """Safely replay an explicitly confirmed interrupted read-only Run as a linked child Run.

    Browser state cannot be restored safely from old element refs. Recovery therefore starts from
    the immutable template entry point instead of pretending to continue mid-page.
    """

    def __init__(self, adapter: BrowserAdapter, runs_root: Path) -> None:
        self.runs_root = runs_root
        self.store = RunStore(runs_root)
        self.runner = Runner(adapter, runs_root)
        self.writer = OutputWriter()

    async def recover(self, run_id: str, *, confirmed: bool) -> RecoveryResult:
        context = self.store.load(run_id)
        if not confirmed:
            raise SkillError(
                ErrorCode.RUN_RECOVERY_NOT_ALLOWED,
                "Restart recovery requires explicit confirmation that the original worker stopped",
                stage="recovery",
            )
        if context.state in TERMINAL_STATES:
            raise SkillError(
                ErrorCode.RUN_RECOVERY_NOT_ALLOWED,
                "Terminal Runs cannot be restarted",
                stage="recovery",
            )
        if context.state == RunState.WAIT_USER_AUTH:
            raise SkillError(
                ErrorCode.RUN_RECOVERY_NOT_ALLOWED,
                "Authentication-paused Runs must use resume",
                stage="recovery",
            )
        if self.store.cancellation_requested(run_id):
            raise SkillError(
                ErrorCode.RUN_CANCELLED,
                "Cancelled Runs cannot be restarted",
                stage="recovery",
            )
        if any(value == "***" for value in context.variables.values()):
            raise SkillError(
                ErrorCode.VARIABLE_MISSING,
                "Sensitive runtime variables must be supplied again before recovery",
                stage="recovery",
            )

        workspace = RunWorkspace.existing(self.store.workspace(run_id))
        context.state = RunState.FAILED
        context.finished_at = datetime.now(UTC)
        self._persist(workspace, context, "recovery_started")
        child = await self.runner.run(context.template_snapshot, context.variables)
        context.recovery_run_id = child.run_id
        self._persist(workspace, context, "recovery_child_created")
        interrupted = SkillError(
            ErrorCode.RUN_INTERRUPTED,
            "Original worker was declared interrupted and replayed as a linked child Run",
            stage="recovery",
            details={"recovery_run_id": child.run_id, "recovery_state": child.state},
        )
        self.writer.write_summary(context, error=interrupted.as_dict())
        return RecoveryResult(interrupted=context, child=child)

    @staticmethod
    def _persist(workspace: RunWorkspace, context: RunContext, event: str) -> None:
        workspace.atomic_json("run.json", context.model_dump(mode="json"))
        workspace.append_jsonl(
            "execution.jsonl",
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "run_id": context.run_id,
                "template_id": context.template_id,
                "template_version": context.template_version,
                "state": context.state.value,
                "event": event,
                "recovery_run_id": context.recovery_run_id,
            },
        )
