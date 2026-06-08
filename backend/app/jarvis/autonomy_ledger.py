"""Perico autonomy ledger.

Shared per-mission bookkeeping for safe recovery attempts. ContextVar-based
so primitives can append without changing their signatures.

Three responsibilities:

1. Accounting: record every safe recovery attempt (step, variant, ok,
   reason) so the closure report and blocked state can say exactly what
   Perico tried before giving up.
2. Stop-reason categorisation: when a block happens, the detecting
   component stamps the ledger with one of the closed-set stop reasons.
   This is the R1 contract surface.
3. Budget ceiling: JARVIS_PERICO_AUTONOMY_BUDGET (default 6) prevents a
   future buggy primitive from looping indefinitely.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterator

logger = logging.getLogger(__name__)

__all__ = [
    "AutonomyAttempt",
    "PericoAutonomyLedger",
    "AUTONOMY_STOP_REASONS",
    "STOP_BUDGET_EXHAUSTED",
    "STOP_RUNTIME_PRECHECK_FAILED",
    "STOP_PYTEST_RETRY_FAILED",
    "STOP_PATCH_WITHOUT_VALIDATION",
    "STOP_OPERATOR_INPUT_REQUIRED",
    "STOP_UNKNOWN",
    "current_autonomy_ledger",
    "perico_mission_autonomy_scope",
    "record_autonomy_attempt",
    "register_stop_reason",
    "register_budget_exhausted",
    "resolve_autonomy_budget",
    "ledger_to_snapshot",
]


STOP_BUDGET_EXHAUSTED = "budget_exhausted"
STOP_RUNTIME_PRECHECK_FAILED = "runtime_precheck_failed"
STOP_PYTEST_RETRY_FAILED = "pytest_retry_failed"
STOP_PATCH_WITHOUT_VALIDATION = "patch_without_validation"
STOP_OPERATOR_INPUT_REQUIRED = "operator_input_required"
STOP_UNKNOWN = "unknown_stop_reason"

AUTONOMY_STOP_REASONS: frozenset[str] = frozenset(
    {
        STOP_BUDGET_EXHAUSTED,
        STOP_RUNTIME_PRECHECK_FAILED,
        STOP_PYTEST_RETRY_FAILED,
        STOP_PATCH_WITHOUT_VALIDATION,
        STOP_OPERATOR_INPUT_REQUIRED,
        STOP_UNKNOWN,
    }
)


_DEFAULT_BUDGET = 6
_MIN_BUDGET = 1
_MAX_BUDGET = 50


def resolve_autonomy_budget() -> int:
    """Read JARVIS_PERICO_AUTONOMY_BUDGET; default 6, clamped to [1, 50]."""
    raw = (os.getenv("JARVIS_PERICO_AUTONOMY_BUDGET") or "").strip()
    if not raw:
        return _DEFAULT_BUDGET
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "jarvis.perico.autonomy.invalid_budget value=%r; using default=%d",
            raw,
            _DEFAULT_BUDGET,
        )
        return _DEFAULT_BUDGET
    return max(_MIN_BUDGET, min(value, _MAX_BUDGET))


@dataclass(frozen=True)
class AutonomyAttempt:
    """One safe autonomy attempt recorded on the ledger."""

    step: str
    variant: str
    ok: bool
    reason: str
    detail: str = ""
    ts: float = field(default_factory=time.time)

    @staticmethod
    def bounded_detail(text: str) -> str:
        s = (text or "").strip()
        return s[:280]

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "variant": self.variant,
            "ok": bool(self.ok),
            "reason": self.reason,
            "detail": self.detail,
            "ts": float(self.ts),
        }


@dataclass
class PericoAutonomyLedger:
    """Per-mission ledger. Not thread-safe; isolated by ContextVar."""

    attempts: list[AutonomyAttempt] = field(default_factory=list)
    stop_reason: str = ""
    stop_detail: str = ""
    budget: int = field(default_factory=resolve_autonomy_budget)

    def record(
        self,
        *,
        step: str,
        variant: str,
        ok: bool,
        reason: str,
        detail: str = "",
    ) -> AutonomyAttempt:
        """Append an attempt. Budget-exhausted attempts get a prefixed reason."""
        effective_reason = (reason or "").strip().lower() or "unspecified"
        if self.budget_exhausted() and not effective_reason.startswith(
            STOP_BUDGET_EXHAUSTED
        ):
            effective_reason = f"{STOP_BUDGET_EXHAUSTED}:{effective_reason}"
        attempt = AutonomyAttempt(
            step=(step or "").strip().lower() or "unspecified",
            variant=(variant or "").strip() or "-",
            ok=bool(ok),
            reason=effective_reason,
            detail=AutonomyAttempt.bounded_detail(detail),
        )
        self.attempts.append(attempt)
        return attempt

    def budget_exhausted(self) -> bool:
        return len(self.attempts) >= self.budget

    def mark_stopped(self, reason: str, detail: str = "") -> None:
        """Stamp terminal stop reason. First call wins; unknown tokens map to STOP_UNKNOWN."""
        if self.stop_reason:
            return
        token = (reason or "").strip().lower()
        if token not in AUTONOMY_STOP_REASONS:
            logger.warning(
                "jarvis.perico.autonomy.unknown_stop_reason reason=%r", reason
            )
            token = STOP_UNKNOWN
        self.stop_reason = token
        self.stop_detail = AutonomyAttempt.bounded_detail(detail)

    def to_snapshot_fields(self) -> dict[str, Any]:
        """Flat, primitive-only serialisation for build_perico_deliverables_snapshot."""
        return {
            "autonomy_attempts": [a.to_dict() for a in self.attempts],
            "autonomy_attempts_count": len(self.attempts),
            "autonomy_budget": int(self.budget),
            "autonomy_stop_reason": self.stop_reason,
            "autonomy_stop_detail": self.stop_detail,
        }


_current_ledger: ContextVar[PericoAutonomyLedger | None] = ContextVar(
    "perico_autonomy_ledger", default=None
)


def current_autonomy_ledger() -> PericoAutonomyLedger | None:
    """Return the active ledger, or None outside a mission scope."""
    return _current_ledger.get()


@contextmanager
def perico_mission_autonomy_scope(
    *,
    ledger: PericoAutonomyLedger | None = None,
    budget: int | None = None,
) -> Iterator[PericoAutonomyLedger]:
    """Open a per-mission autonomy scope. Yields the ledger."""
    active = ledger or PericoAutonomyLedger(
        budget=int(budget) if budget is not None else resolve_autonomy_budget()
    )
    token = _current_ledger.set(active)
    try:
        yield active
    finally:
        _current_ledger.reset(token)


def record_autonomy_attempt(
    *,
    step: str,
    variant: str,
    ok: bool,
    reason: str,
    detail: str = "",
) -> AutonomyAttempt | None:
    """Record on the current ledger if any; no-op outside a scope."""
    ledger = _current_ledger.get()
    if ledger is None:
        return None
    return ledger.record(
        step=step, variant=variant, ok=ok, reason=reason, detail=detail
    )


def register_stop_reason(reason: str, detail: str = "") -> None:
    """Stamp terminal stop reason on current ledger. No-op outside a scope."""
    ledger = _current_ledger.get()
    if ledger is None:
        return
    ledger.mark_stopped(reason, detail=detail)


def register_budget_exhausted(detail: str = "") -> None:
    """Convenience wrapper for the budget-ceiling stop reason."""
    register_stop_reason(STOP_BUDGET_EXHAUSTED, detail=detail)


def ledger_to_snapshot(
    ledger: PericoAutonomyLedger | None = None,
) -> dict[str, Any]:
    """Flatten a ledger into the snapshot fields. Safe to splat unconditionally."""
    active = ledger if ledger is not None else _current_ledger.get()
    if active is None:
        return {
            "autonomy_attempts": [],
            "autonomy_attempts_count": 0,
            "autonomy_budget": resolve_autonomy_budget(),
            "autonomy_stop_reason": "",
            "autonomy_stop_detail": "",
        }
    return active.to_snapshot_fields()
