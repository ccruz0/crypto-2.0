"""In-memory approval record store (swappable for Redis/Postgres later)."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Literal

_EXEC_RESULT_MAX_JSON = 8000
_EXEC_ERROR_MAX_LEN = 4000

# Match conversation memory spirit: bounded retention.
_MAX_APPROVAL_RECORDS = 100

# Human approval workflow (field: ``approval_status``; legacy ``status`` mirrors this).
APPROVAL_PENDING = "pending"
APPROVAL_APPROVED = "approved"
APPROVAL_REJECTED = "rejected"
APPROVAL_AUTO_APPROVED = "auto_approved"

# Deferred tool execution readiness (orthogonal to approval_status).
EXEC_NOT_EXECUTED = "not_executed"
EXEC_READY = "ready"
EXEC_EXECUTED = "executed"
EXEC_FAILED = "execution_failed"


def utc_now_iso() -> str:
    """Stable UTC timestamp for audit logs (ISO 8601)."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


StorageMutationError = Literal["not_found", "already_decided"]

FinalizeExecutionError = Literal[
    "not_found",
    "not_approved_ready",
    "already_executed",
    "already_failed",
]


def _approval_status_of(record: dict[str, Any]) -> str:
    """Canonical approval state (supports legacy ``status`` only)."""
    v = record.get("approval_status")
    if v is not None and str(v).strip():
        return str(v).strip()
    v2 = record.get("status")
    if v2 is not None and str(v2).strip():
        return str(v2).strip()
    return ""


def _execution_status_of(record: dict[str, Any]) -> str:
    v = record.get("execution_status")
    if v is not None and str(v).strip():
        return str(v).strip()
    return EXEC_NOT_EXECUTED


def normalize_approval_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with canonical approval + execution fields."""
    out = dict(record)
    ap = _approval_status_of(out)
    if ap:
        out["approval_status"] = ap
        out["status"] = ap
    ex = _execution_status_of(out)
    out["execution_status"] = ex
    out.setdefault("approved_by", None)
    out.setdefault("rejected_by", None)
    out.setdefault("executed_by", None)
    out.setdefault("risk_level", None)
    out.setdefault("allowed_envs", None)
    return out


def bound_execution_result_payload(value: Any) -> Any:
    """Small JSON-safe payload for ``execution_result`` (bounded size)."""
    try:
        s = json.dumps(value, default=str)
    except (TypeError, ValueError):
        return {"repr": str(value)[: _EXEC_RESULT_MAX_JSON]}
    if len(s) <= _EXEC_RESULT_MAX_JSON:
        return json.loads(s)
    return {"_truncated": True, "preview": s[:_EXEC_RESULT_MAX_JSON]}


def bound_execution_error(message: str) -> str:
    return (message or "")[:_EXEC_ERROR_MAX_LEN]


def build_pending_approval_record(
    *,
    jarvis_run_id: str,
    tool: str,
    args: dict[str, Any],
    policy: str,
    category: str,
    message: str,
    created_at: str | None = None,
    risk_level: str | None = None,
    allowed_envs: list[str] | None = None,
    extra_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Canonical pending approval record shared by executor and internal staging flows."""
    row: dict[str, Any] = {
        "jarvis_run_id": (jarvis_run_id or "").strip(),
        "tool": (tool or "").strip(),
        "args": dict(args or {}),
        "policy": (policy or "").strip(),
        "category": (category or "").strip(),
        "message": message,
        "approval_status": APPROVAL_PENDING,
        "execution_status": EXEC_NOT_EXECUTED,
        "status": APPROVAL_PENDING,
        "created_at": created_at or utc_now_iso(),
        "updated_at": None,
        "decision": None,
        "decision_reason": None,
        "executed_at": None,
        "execution_result": None,
        "execution_error": None,
        "approved_by": None,
        "rejected_by": None,
        "executed_by": None,
        "risk_level": risk_level,
        "allowed_envs": allowed_envs,
    }
    if extra_fields:
        row.update(dict(extra_fields))
    return normalize_approval_record(row)


class JarvisApprovalStorage(ABC):
    """Persist approval metadata, execution readiness, and transitions (no tool execution)."""

    @abstractmethod
    def record_pending(self, record: dict[str, Any]) -> None:
        """Store a new row (typically approval pending, execution not_executed)."""
        ...

    @abstractmethod
    def list_pending(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """Newest-first rows where approval is still pending."""
        ...

    @abstractmethod
    def list_recent(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """Newest-first rows (all approval states)."""
        ...

    @abstractmethod
    def list_ready_for_execution(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """Newest-first rows approved and ready to run (execution layer; no run here)."""
        ...

    @abstractmethod
    def get_by_run_id(self, jarvis_run_id: str) -> dict[str, Any] | None:
        """Latest stored row for this run id, or None."""
        ...

    @abstractmethod
    def approve_by_run_id(
        self,
        jarvis_run_id: str,
        *,
        reason: str | None = None,
        approved_by: str | None = None,
    ) -> tuple[dict[str, Any] | None, StorageMutationError | None]:
        """Pending -> approved + execution ready; return (record, None) or (None, error)."""

    @abstractmethod
    def reject_by_run_id(
        self,
        jarvis_run_id: str,
        *,
        reason: str | None = None,
        rejected_by: str | None = None,
    ) -> tuple[dict[str, Any] | None, StorageMutationError | None]:
        """Pending -> rejected + execution not_executed."""

    @abstractmethod
    def finalize_ready_execution(
        self,
        jarvis_run_id: str,
        *,
        success: bool,
        execution_result: Any = None,
        execution_error: str | None = None,
        executed_by: str | None = None,
    ) -> tuple[dict[str, Any] | None, FinalizeExecutionError | None]:
        """
        Transition ``ready`` -> ``executed`` or ``execution_failed``.
        Returns (updated_record, None) or (None, error_code).
        """
        ...

    @abstractmethod
    def finalize_auto_execution_success(
        self,
        jarvis_run_id: str,
        *,
        execution_result: Any,
    ) -> tuple[dict[str, Any] | None, str | None]:
        """
        Pending + not_executed -> auto_approved + executed (Jarvis auto layer only).
        Returns (updated_record, None) or (None, error_reason).
        """
        ...

    def clear(self) -> None:
        """Tests only."""
        pass


class InMemoryJarvisApprovalStorage(JarvisApprovalStorage):
    """FIFO-capped list; lookups scan newest-first by list index."""

    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []

    def _trim(self) -> None:
        while len(self._records) > _MAX_APPROVAL_RECORDS:
            self._records.pop(0)

    def _index_latest(self, jarvis_run_id: str) -> int | None:
        key = (jarvis_run_id or "").strip()
        if not key:
            return None
        for i in range(len(self._records) - 1, -1, -1):
            if (self._records[i].get("jarvis_run_id") or "").strip() == key:
                return i
        return None

    def record_pending(self, record: dict[str, Any]) -> None:
        row = normalize_approval_record(dict(record))
        self._records.append(row)
        self._trim()

    def list_pending(self, *, limit: int = 20) -> list[dict[str, Any]]:
        lim = max(1, min(limit, 200))
        out: list[dict[str, Any]] = []
        for r in reversed(self._records):
            if _approval_status_of(r) == APPROVAL_PENDING:
                out.append(normalize_approval_record(dict(r)))
                if len(out) >= lim:
                    break
        return out

    def list_recent(self, *, limit: int = 20) -> list[dict[str, Any]]:
        lim = max(1, min(limit, 200))
        tail = self._records[-lim:]
        return [normalize_approval_record(dict(r)) for r in reversed(tail)]

    def list_ready_for_execution(self, *, limit: int = 20) -> list[dict[str, Any]]:
        lim = max(1, min(limit, 200))
        out: list[dict[str, Any]] = []
        for r in reversed(self._records):
            if _approval_status_of(r) == APPROVAL_APPROVED and _execution_status_of(r) == EXEC_READY:
                out.append(normalize_approval_record(dict(r)))
                if len(out) >= lim:
                    break
        return out

    def get_by_run_id(self, jarvis_run_id: str) -> dict[str, Any] | None:
        idx = self._index_latest(jarvis_run_id)
        if idx is None:
            return None
        return normalize_approval_record(dict(self._records[idx]))

    def approve_by_run_id(
        self,
        jarvis_run_id: str,
        *,
        reason: str | None = None,
        approved_by: str | None = None,
    ) -> tuple[dict[str, Any] | None, StorageMutationError | None]:
        return self._transition(
            jarvis_run_id,
            approval_to=APPROVAL_APPROVED,
            execution_to=EXEC_READY,
            reason=reason,
            approved_by=approved_by,
        )

    def reject_by_run_id(
        self,
        jarvis_run_id: str,
        *,
        reason: str | None = None,
        rejected_by: str | None = None,
    ) -> tuple[dict[str, Any] | None, StorageMutationError | None]:
        return self._transition(
            jarvis_run_id,
            approval_to=APPROVAL_REJECTED,
            execution_to=EXEC_NOT_EXECUTED,
            reason=reason,
            rejected_by=rejected_by,
        )

    def _transition(
        self,
        jarvis_run_id: str,
        *,
        approval_to: str,
        execution_to: str,
        reason: str | None,
        approved_by: str | None = None,
        rejected_by: str | None = None,
    ) -> tuple[dict[str, Any] | None, StorageMutationError | None]:
        key = (jarvis_run_id or "").strip()
        if not key:
            return None, "not_found"
        idx = self._index_latest(key)
        if idx is None:
            return None, "not_found"
        cur = self._records[idx]
        if _approval_status_of(cur) != APPROVAL_PENDING:
            return None, "already_decided"
        now = utc_now_iso()
        reason_clean = (reason or "").strip() or None
        updated = dict(cur)
        updated["approval_status"] = approval_to
        updated["status"] = approval_to
        updated["execution_status"] = execution_to
        updated["updated_at"] = now
        updated["decision"] = approval_to
        updated["decision_reason"] = reason_clean
        if approved_by is not None:
            updated["approved_by"] = approved_by
        if rejected_by is not None:
            updated["rejected_by"] = rejected_by
        self._records[idx] = updated
        return normalize_approval_record(dict(updated)), None

    def finalize_ready_execution(
        self,
        jarvis_run_id: str,
        *,
        success: bool,
        execution_result: Any = None,
        execution_error: str | None = None,
        executed_by: str | None = None,
    ) -> tuple[dict[str, Any] | None, FinalizeExecutionError | None]:
        key = (jarvis_run_id or "").strip()
        if not key:
            return None, "not_found"
        idx = self._index_latest(key)
        if idx is None:
            return None, "not_found"
        cur = self._records[idx]
        if _approval_status_of(cur) != APPROVAL_APPROVED:
            return None, "not_approved_ready"
        ex = _execution_status_of(cur)
        if ex == EXEC_EXECUTED:
            return None, "already_executed"
        if ex == EXEC_FAILED:
            return None, "already_failed"
        if ex != EXEC_READY:
            return None, "not_approved_ready"
        now = utc_now_iso()
        updated = dict(cur)
        updated["executed_at"] = now
        if success:
            updated["execution_status"] = EXEC_EXECUTED
            updated["execution_result"] = bound_execution_result_payload(execution_result)
            updated["execution_error"] = None
        else:
            updated["execution_status"] = EXEC_FAILED
            updated["execution_result"] = None
            updated["execution_error"] = bound_execution_error(execution_error or "execution_failed")
        if executed_by is not None:
            updated["executed_by"] = executed_by
        self._records[idx] = updated
        return normalize_approval_record(dict(updated)), None

    def finalize_auto_execution_success(
        self,
        jarvis_run_id: str,
        *,
        execution_result: Any,
    ) -> tuple[dict[str, Any] | None, str | None]:
        key = (jarvis_run_id or "").strip()
        if not key:
            return None, "not_found"
        idx = self._index_latest(key)
        if idx is None:
            return None, "not_found"
        cur = self._records[idx]
        if _approval_status_of(cur) != APPROVAL_PENDING:
            return None, "not_eligible"
        if _execution_status_of(cur) != EXEC_NOT_EXECUTED:
            return None, "not_eligible"
        now = utc_now_iso()
        updated = dict(cur)
        updated["approval_status"] = APPROVAL_AUTO_APPROVED
        updated["status"] = APPROVAL_AUTO_APPROVED
        updated["execution_status"] = EXEC_EXECUTED
        updated["execution_result"] = bound_execution_result_payload(execution_result)
        updated["execution_error"] = None
        updated["updated_at"] = now
        updated["executed_at"] = now
        updated["decision"] = APPROVAL_AUTO_APPROVED
        updated["decision_reason"] = "jarvis_auto_execution"
        updated["executed_by"] = "jarvis_auto_execution"
        self._records[idx] = updated
        return normalize_approval_record(dict(updated)), None

    def clear(self) -> None:
        self._records.clear()


_default_approval_storage: JarvisApprovalStorage = InMemoryJarvisApprovalStorage()


def get_default_approval_storage() -> JarvisApprovalStorage:
    return _default_approval_storage


def reset_default_approval_storage_for_tests() -> None:
    if isinstance(_default_approval_storage, InMemoryJarvisApprovalStorage):
        _default_approval_storage.clear()
