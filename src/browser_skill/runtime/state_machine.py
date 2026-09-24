from __future__ import annotations

from browser_skill.models import RunState

ALLOWED_TRANSITIONS: dict[RunState, set[RunState]] = {
    RunState.INIT: {RunState.INPUT_READY, RunState.FAILED, RunState.CANCELLED},
    RunState.INPUT_READY: {RunState.AUTH_CHECK, RunState.FAILED, RunState.CANCELLED},
    RunState.AUTH_CHECK: {RunState.WAIT_USER_AUTH, RunState.NAVIGATING, RunState.FAILED},
    RunState.WAIT_USER_AUTH: {RunState.AUTH_CHECK, RunState.CANCELLED, RunState.FAILED},
    RunState.NAVIGATING: {RunState.EXTRACTING, RunState.REPAIRING, RunState.FAILED},
    RunState.EXTRACTING: {
        RunState.DOWNLOADING,
        RunState.VALIDATING,
        RunState.REPAIRING,
        # detail_batch: the session may expire between items; pause and resume where we left off
        RunState.WAIT_USER_AUTH,
        RunState.FAILED,
    },
    RunState.DOWNLOADING: {RunState.VALIDATING, RunState.REPAIRING, RunState.FAILED},
    RunState.VALIDATING: {
        RunState.WRITING_OUTPUT,
        RunState.REPAIRING,
        RunState.FAILED,
    },
    RunState.WRITING_OUTPUT: {RunState.COMPLETED, RunState.PARTIAL, RunState.FAILED},
    RunState.REPAIRING: {RunState.TESTING, RunState.FAILED},
    RunState.TESTING: {RunState.NAVIGATING, RunState.FAILED},
    RunState.COMPLETED: set(),
    RunState.PARTIAL: set(),
    RunState.FAILED: set(),
    RunState.CANCELLED: set(),
}


def can_transition(current: RunState, target: RunState) -> bool:
    return target in ALLOWED_TRANSITIONS[current]
