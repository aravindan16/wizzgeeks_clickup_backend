"""Task workflow state machine.

States and the only legal transitions between them. The service validates every
status change against this map, so illegal jumps (e.g. Backlog -> Completed) are
rejected — enforcing the workflow and preventing skipped states.
"""

# Canonical ordered states.
BACKLOG = "backlog"
PLANNED = "planned"
IN_PROGRESS = "in_progress"
BLOCKED = "blocked"
REVIEW = "review"
TESTING = "testing"
COMPLETED = "completed"
CLOSED = "closed"

WORKFLOW_STATES: list[str] = [
    BACKLOG, PLANNED, IN_PROGRESS, BLOCKED, REVIEW, TESTING, COMPLETED, CLOSED,
]

# Terminal/closed statuses for metrics.
DONE_STATUSES = {COMPLETED, CLOSED}

# Allowed transitions: state -> set of reachable next states.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    BACKLOG: {PLANNED},
    PLANNED: {IN_PROGRESS, BACKLOG},
    IN_PROGRESS: {BLOCKED, REVIEW, BACKLOG},
    BLOCKED: {IN_PROGRESS},
    REVIEW: {IN_PROGRESS, TESTING},
    TESTING: {IN_PROGRESS, COMPLETED},
    COMPLETED: {CLOSED, IN_PROGRESS},
    CLOSED: {BACKLOG},  # reopen
}

# Statuses that require an explanatory note when entered.
REQUIRES_NOTE: set[str] = {BLOCKED}


def is_valid_transition(from_status: str, to_status: str) -> bool:
    if from_status == to_status:
        return False
    return to_status in ALLOWED_TRANSITIONS.get(from_status, set())


def allowed_next(from_status: str) -> list[str]:
    return sorted(ALLOWED_TRANSITIONS.get(from_status, set()))
