from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from browser_skill.errors import ErrorCode, SkillError
from browser_skill.models import RunContext, RunState
from browser_skill.outputs.paths import contained_path, safe_filename
from browser_skill.outputs.writer import RunWorkspace

TERMINAL_STATES = {RunState.COMPLETED, RunState.PARTIAL, RunState.FAILED, RunState.CANCELLED}


class RunStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def load(self, run_id: str) -> RunContext:
        workspace = self.workspace(run_id)
        path = workspace / "run.json"
        if not path.is_file():
            raise SkillError(ErrorCode.TEMPLATE_NOT_FOUND, "Run not found")
        try:
            return RunContext.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError) as exc:
            raise SkillError(ErrorCode.TEMPLATE_INVALID, "Run state is invalid") from exc

    def cancel(self, run_id: str) -> RunContext:
        context = self.load(run_id)
        if context.state in TERMINAL_STATES:
            return context
        # A cancellation marker is checked at every subsequent Runner transition.
        marker = self.workspace(run_id) / "cancel.requested"
        marker.write_text(datetime.now(UTC).isoformat(), encoding="utf-8")
        if context.state == RunState.WAIT_USER_AUTH:
            context.state = RunState.CANCELLED
            context.finished_at = datetime.now(UTC)
            RunWorkspace.existing(self.workspace(run_id)).atomic_json(
                "run.json", context.model_dump(mode="json")
            )
        return context

    def cancellation_requested(self, run_id: str) -> bool:
        return (self.workspace(run_id) / "cancel.requested").is_file()

    def workspace(self, run_id: str) -> Path:
        if safe_filename(run_id, fallback="invalid") != run_id:
            raise SkillError(ErrorCode.UNSAFE_OUTPUT_PATH, "Invalid run identifier")
        return contained_path(self.root, run_id)
