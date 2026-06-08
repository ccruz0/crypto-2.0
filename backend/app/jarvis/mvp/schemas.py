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


ObjectiveStatus = Literal["planned", "active", "completed", "cancelled"]
ObjectiveHealth = Literal["green", "yellow", "red"]
KrStatus = Literal["on_track", "at_risk", "behind", "achieved"]
KrDirection = Literal["max", "min"]
ObjectiveLinkedType = Literal[
    "initiative",
    "aws_audit",
    "crypto_audit",
    "action_plan",
    "decision",
    "executive_report",
]


class JarvisKeyResultSummary(BaseModel):
    kr_id: str
    objective_id: str
    title: str
    metric_name: str | None = None
    target_value: float = 0.0
    current_value: float = 0.0
    unit: str | None = None
    direction: KrDirection = "max"
    status: KrStatus = "on_track"
    progress_pct: float = 0.0
    metric_source: str | None = None
    last_refreshed_at: str | None = None


class JarvisKrRefreshRunSummary(BaseModel):
    refresh_id: str
    created_at: str | None = None
    kr_count: int = 0
    updated_count: int = 0
    failed_count: int = 0
    errors: list[dict[str, Any]] = Field(default_factory=list)


class JarvisKrRefreshResponse(BaseModel):
    refresh_id: str
    kr_count: int = 0
    updated_count: int = 0
    failed_count: int = 0
    errors: list[dict[str, Any]] = Field(default_factory=list)
    alerts_queued: int = 0
    telegram_sent: int = 0
    read_only: bool = True
    execution_performed: bool = False


class JarvisKrRefreshRunsResponse(BaseModel):
    runs: list[JarvisKrRefreshRunSummary] = Field(default_factory=list)
    read_only: bool = True


class JarvisObjectiveLink(BaseModel):
    link_id: str
    objective_id: str
    linked_type: ObjectiveLinkedType
    linked_id: str
    created_at: str | None = None


class JarvisObjectiveCreateRequest(BaseModel):
    title: str = Field(..., min_length=1)
    description: str = ""
    status: ObjectiveStatus = "planned"
    owner: str | None = None
    target_date: str | None = None


class JarvisObjectiveUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    status: ObjectiveStatus | None = None
    owner: str | None = None
    target_date: str | None = None


class JarvisKeyResultCreateRequest(BaseModel):
    title: str = Field(..., min_length=1)
    metric_name: str | None = None
    target_value: float = 0.0
    current_value: float = 0.0
    unit: str | None = None
    direction: KrDirection = "max"


class JarvisKeyResultUpdateRequest(BaseModel):
    title: str | None = None
    current_value: float | None = None
    target_value: float | None = None


class JarvisObjectiveLinkRequest(BaseModel):
    linked_type: ObjectiveLinkedType
    linked_id: str = Field(..., min_length=1)


class JarvisObjectiveSummary(BaseModel):
    objective_id: str
    created_at: str | None = None
    updated_at: str | None = None
    title: str
    description: str = ""
    status: ObjectiveStatus = "planned"
    owner: str | None = None
    target_date: str | None = None
    progress_pct: int = 0
    health: ObjectiveHealth = "green"
    is_overdue: bool = False
    alignment_status: str = "On track"


class JarvisObjectiveListResponse(BaseModel):
    objectives: list[JarvisObjectiveSummary] = Field(default_factory=list)


class JarvisObjectiveDetail(JarvisObjectiveSummary):
    key_results: list[JarvisKeyResultSummary] = Field(default_factory=list)
    links: list[JarvisObjectiveLink] = Field(default_factory=list)
    linked_initiatives: list[dict[str, Any]] = Field(default_factory=list)
    progress_trend: list[dict[str, Any]] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    read_only: bool = True
    execution_performed: bool = False
