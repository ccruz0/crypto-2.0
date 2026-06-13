"""Pydantic schemas for Jarvis Phase 3 task execution."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

TaskPriority = Literal["low", "normal", "high"]
ApprovalMode = Literal["auto", "manual"]
ApprovalStatus = Literal["not_required", "pending", "approved", "rejected"]


class JarvisExecutionStep(BaseModel):
    id: str
    action: str
    tool: str
    description: str
    safety_level: str = "safe_auto"
    estimated_cost_usd: float = 0.01


class JarvisExecutionPlan(BaseModel):
    steps: list[JarvisExecutionStep] = Field(default_factory=list)
    total_estimated_cost_usd: float = 0.0
    overall_safety: str = "safe_auto"
    objective_summary: str = ""


class JarvisTaskSubmitRequest(BaseModel):
    objective: str = Field(..., min_length=1)
    priority: TaskPriority = "normal"
    approval_mode: ApprovalMode = "auto"
    dry_run: bool = Field(default=True, description="Investigation-only default; read-only tools only")


class JarvisTaskSubmitResponse(BaseModel):
    task_id: str
    status: str
    objective: str
    plan: JarvisExecutionPlan
    approval_required: bool = False
    approval_status: ApprovalStatus = "not_required"
    estimated_cost_usd: float = 0.0
    actual_cost_usd: float = 0.0
    current_step: str | None = None
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    execution_log: list[dict[str, Any]] = Field(default_factory=list)


class JarvisTaskApprovalRequest(BaseModel):
    actor_id: str = "dashboard"
    comment: str = ""


class JarvisTaskApprovalRecord(BaseModel):
    approval_id: str
    task_id: str
    decision: str
    actor_id: str
    comment: str = ""
    created_at: str | None = None


class JarvisExecutionTaskDetail(BaseModel):
    task_id: str
    objective: str
    task: str
    status: str
    priority: str = "normal"
    dry_run: bool = True
    plan: JarvisExecutionPlan | dict[str, Any] = Field(default_factory=dict)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    approval_required: bool = False
    approval_status: ApprovalStatus = "not_required"
    estimated_cost_usd: float = 0.0
    actual_cost_usd: float = 0.0
    final_answer: str = ""
    error: str | None = None
    current_step: str | None = None
    execution_log: list[dict[str, Any]] = Field(default_factory=list)
    approvals: list[JarvisTaskApprovalRecord] = Field(default_factory=list)
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


class JarvisExecutionTaskSummary(BaseModel):
    task_id: str
    objective: str
    status: str
    priority: str = "normal"
    approval_status: ApprovalStatus = "not_required"
    estimated_cost_usd: float = 0.0
    actual_cost_usd: float = 0.0
    created_at: str | None = None
    completed_at: str | None = None


class JarvisExecutionTaskListResponse(BaseModel):
    tasks: list[JarvisExecutionTaskSummary] = Field(default_factory=list)


# --- Phase 4: Change workflow schemas ---


class JarvisChangeTaskSubmitRequest(BaseModel):
    objective: str = Field(..., min_length=1)
    priority: TaskPriority = "normal"
    target_files: list[str] = Field(default_factory=list)
    dry_run: bool = Field(default=True, description="Investigation and patch generation only; no application")
    run_tests: bool = Field(default=True, description="Run relevant tests in dry-run or local mode")


class JarvisPatchRevisionRequest(BaseModel):
    notes: str = ""
    objective: str | None = None


class JarvisApprovalQueueItem(BaseModel):
    task_id: str
    objective: str
    status: str
    patch_summary: str = ""
    files_affected: list[str] = Field(default_factory=list)
    risk_score: int | None = None
    test_results: dict[str, Any] = Field(default_factory=dict)
    review_findings: list[dict[str, Any]] = Field(default_factory=list)
    approval_status: ApprovalStatus = "pending"
    created_at: str | None = None
    workflow_type: str = "phase4_change"


class JarvisApprovalQueueResponse(BaseModel):
    items: list[JarvisApprovalQueueItem] = Field(default_factory=list)


class JarvisChangeTaskDetail(JarvisExecutionTaskDetail):
    workflow_type: str = "phase4_change"
    review: dict[str, Any] = Field(default_factory=dict)
    phase5: dict[str, Any] = Field(default_factory=dict)


class JarvisPhase5StatusResponse(BaseModel):
    task_id: str
    status: str = ""
    workflow_type: str = "phase5_change"
    safety_flags: dict[str, bool] = Field(default_factory=dict)
    gate1_approved: bool = False
    gate2_approved: bool = False
    can_approve_apply: bool = False
    can_approve_pr: bool = False
    tests_passed: bool = False
    sandbox_applied: bool = False
    pr_url: str | None = None
    branch_name: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    test_results: dict[str, Any] = Field(default_factory=dict)
    forbidden_check: dict[str, Any] = Field(default_factory=dict)
