"""String enums for Jarvis Control Center persistence (no runtime execution logic)."""

from __future__ import annotations

CONTROL_MODES = frozenset({"advisor", "builder", "operator"})
CONTROL_DOMAINS = frozenset({"trading", "marketing", "software", "ops", "general"})
CONTROL_ENVIRONMENTS = frozenset({"prod", "lab", "local"})

SESSION_STATUSES = frozenset({"active", "closed", "failed"})
TASK_STATUSES = frozenset({
    "queued",
    "planning",
    "running",
    "awaiting_approval",
    "completed",
    "failed",
    "cancelled",
})
RISK_LEVELS = frozenset({"low", "medium", "high"})

APPROVAL_STATUSES = frozenset({"pending", "approved", "rejected", "expired"})
EXECUTION_STATUSES = frozenset({
    "not_executed",
    "ready",
    "executing",
    "executed",
    "failed",
})

ACTOR_TYPES = frozenset({"human", "jarvis", "system", "scheduler"})

DEFAULT_MODE = "advisor"
DEFAULT_DOMAIN = "general"
DEFAULT_ENVIRONMENT = "prod"
DEFAULT_TASK_STATUS = "queued"
DEFAULT_SESSION_STATUS = "active"
