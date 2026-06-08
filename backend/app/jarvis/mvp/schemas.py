"""Request/response schemas for Jarvis LangGraph MVP."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

RiskLevel = Literal["low", "medium", "high"]
TaskStatus = Literal["completed", "requires_approval", "failed"]


class JarvisTaskRequest(BaseModel):
    task: str = Field(..., min_length=1, description="Natural-language task for Jarvis")
    dry_run: bool = Field(default=True, description="When true, only read-only tools may run")


class JarvisTaskResponse(BaseModel):
    task_id: str
    status: TaskStatus
    risk_level: RiskLevel
    plan: list[dict[str, Any]] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    review: dict[str, Any] = Field(default_factory=dict)
    estimated_cost_usd: float = 0.0
    final_answer: str = ""


class JarvisTaskRunSummary(BaseModel):
    task_id: str
    task: str
    status: str
    risk_level: RiskLevel
    estimated_cost_usd: float = 0.0
    created_at: str | None = None
    completed_at: str | None = None


class JarvisTaskListResponse(BaseModel):
    tasks: list[JarvisTaskRunSummary] = Field(default_factory=list)


class JarvisTaskRunDetail(BaseModel):
    task_id: str
    task: str
    status: str
    risk_level: RiskLevel
    dry_run: bool
    plan: list[dict[str, Any]] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    review: dict[str, Any] = Field(default_factory=dict)
    estimated_cost_usd: float = 0.0
    final_answer: str = ""
    error: str | None = None
    created_at: str | None = None
    completed_at: str | None = None
