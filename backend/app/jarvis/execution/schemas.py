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
    decision: Literal["approved", "rejected"]
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
