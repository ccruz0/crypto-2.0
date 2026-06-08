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
    audit_id: str | None = None
    audit_output: dict[str, Any] | None = None
    crypto_audit_id: str | None = None
    crypto_audit_output: dict[str, Any] | None = None


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


class JarvisAuditRunSummary(BaseModel):
    audit_id: str
    task_id: str | None = None
    created_at: str | None = None
    estimated_monthly_savings: float = 0.0
    finding_counts: dict[str, int] = Field(default_factory=dict)
    severity: str = "low"


class JarvisAuditListResponse(BaseModel):
    audits: list[JarvisAuditRunSummary] = Field(default_factory=list)


class JarvisAuditRunDetail(BaseModel):
    audit_id: str
    task_id: str | None = None
    created_at: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    cost_findings: list[dict[str, Any]] = Field(default_factory=list)
    security_findings: list[dict[str, Any]] = Field(default_factory=list)
    resource_findings: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    estimated_monthly_savings: float = 0.0
    finding_counts: dict[str, int] = Field(default_factory=dict)
    severity: str = "low"


class JarvisCryptoAuditRunSummary(BaseModel):
    audit_id: str
    task_id: str | None = None
    created_at: str | None = None
    portfolio_difference_usd: float = 0.0
    portfolio_difference_pct: float = 0.0
    finding_count: int = 0
    severity: str = "low"


class JarvisCryptoAuditListResponse(BaseModel):
    audits: list[JarvisCryptoAuditRunSummary] = Field(default_factory=list)


class JarvisCryptoAuditRunDetail(BaseModel):
    audit_id: str
    task_id: str | None = None
    created_at: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    wallet_findings: list[dict[str, Any]] = Field(default_factory=list)
    position_findings: list[dict[str, Any]] = Field(default_factory=list)
    valuation_findings: list[dict[str, Any]] = Field(default_factory=list)
    price_feed_findings: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    portfolio_difference_usd: float = 0.0
    portfolio_difference_pct: float = 0.0
    finding_count: int = 0
    severity: str = "low"


class JarvisExecutiveDashboardResponse(BaseModel):
    infrastructure: dict[str, Any] = Field(default_factory=dict)
    security: dict[str, Any] = Field(default_factory=dict)
    jarvis_activity: dict[str, Any] = Field(default_factory=dict)
    crypto_health: dict[str, Any] = Field(default_factory=dict)
    trends: dict[str, Any] = Field(default_factory=dict)
    decision_intelligence: dict[str, Any] = Field(default_factory=dict)
    execution: dict[str, Any] = Field(default_factory=dict)
    followups: dict[str, Any] = Field(default_factory=dict)
    strategic_objectives: dict[str, Any] = Field(default_factory=dict)
    read_only: bool = True


PlanStatus = Literal["proposed", "approved", "rejected"]
PlanSeverity = Literal["low", "medium", "high", "critical"]
ActionPlanSourceType = Literal["aws_audit", "crypto_audit", "executive_dashboard"]


class JarvisActionPlanAction(BaseModel):
    title: str
    description: str
    impact: str
    risk: str
    manual_steps: list[str] = Field(default_factory=list)


class JarvisActionPlanSummary(BaseModel):
    plan_id: str
    source_type: str | None = None
    source_id: str | None = None
    severity: PlanSeverity = "low"
    estimated_savings_usd: float = 0.0
    status: PlanStatus = "proposed"
    created_at: str | None = None


class JarvisActionPlanListResponse(BaseModel):
    plans: list[JarvisActionPlanSummary] = Field(default_factory=list)


class JarvisActionPlanDetail(BaseModel):
    plan_id: str
    source_type: str | None = None
    source_id: str | None = None
    severity: PlanSeverity = "low"
    estimated_savings_usd: float = 0.0
    estimated_risk_reduction: str = ""
    actions: list[JarvisActionPlanAction] = Field(default_factory=list)
    status: PlanStatus = "proposed"
    created_at: str | None = None
    action_count: int = 0
    read_only: bool = True
    execution_performed: bool = False


class JarvisActionPlanGenerateRequest(BaseModel):
    source_type: ActionPlanSourceType
    source_id: str = Field(..., min_length=1)


class JarvisExecutivePriorityItem(BaseModel):
    priority: int | None = None
    title: str
    reason: str
    expected_impact: str
    estimated_savings_usd: float = 0.0
    risk_if_ignored: str


class JarvisExecutiveBlockedItem(BaseModel):
    title: str
    reason: str
    blocked_by: str


class JarvisExecutiveReportSummary(BaseModel):
    report_id: str
    generated_at: str | None = None
    overall_health_score: int = 0
    top_priority_count: int = 0
    quick_win_count: int = 0
    top_priority_title: str | None = None


class JarvisExecutiveReportListResponse(BaseModel):
    reports: list[JarvisExecutiveReportSummary] = Field(default_factory=list)


class JarvisExecutionReview(BaseModel):
    active: int = 0
    blocked: int = 0
    overdue: int = 0
    stalled: int = 0
    completed_this_month: int = 0
    top_risk: str | None = None


class JarvisFollowupReview(BaseModel):
    summary: dict[str, Any] = Field(default_factory=dict)
    top_followups: list[dict[str, Any]] = Field(default_factory=list)
    has_high_severity: bool = False


class JarvisStrategicAlignment(BaseModel):
    summary: dict[str, Any] = Field(default_factory=dict)
    objectives: list[dict[str, Any]] = Field(default_factory=list)
    blocked_objectives: list[dict[str, Any]] = Field(default_factory=list)
    on_track_objectives: list[dict[str, Any]] = Field(default_factory=list)
    at_risk_objectives: list[dict[str, Any]] = Field(default_factory=list)


class JarvisExecutiveReportDetail(BaseModel):
    report_id: str
    generated_at: str | None = None
    overall_health_score: int = 0
    top_priorities: list[JarvisExecutivePriorityItem] = Field(default_factory=list)
    quick_wins: list[JarvisExecutivePriorityItem] = Field(default_factory=list)
    strategic_items: list[JarvisExecutivePriorityItem] = Field(default_factory=list)
    blocked_items: list[JarvisExecutiveBlockedItem] = Field(default_factory=list)
    lessons_learned: list[str] = Field(default_factory=list)
    execution_review: JarvisExecutionReview = Field(default_factory=JarvisExecutionReview)
    execution_status: dict[str, Any] = Field(default_factory=dict)
    followup_review: JarvisFollowupReview = Field(default_factory=JarvisFollowupReview)
    strategic_alignment: JarvisStrategicAlignment = Field(default_factory=JarvisStrategicAlignment)
    read_only: bool = True
    execution_performed: bool = False


DecisionType = Literal["approved", "rejected", "deferred"]
OutcomeType = Literal["unknown", "successful", "unsuccessful", "partial"]


class JarvisDecisionCreateRequest(BaseModel):
    source_type: str | None = None
    source_id: str | None = None
    plan_id: str | None = None
    decision: DecisionType
    decision_reason: str = ""
    outcome: OutcomeType = "unknown"
    reviewed_by: str | None = None


class JarvisDecisionSummary(BaseModel):
    decision_id: str
    created_at: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    plan_id: str | None = None
    decision: DecisionType
    decision_reason: str = ""
    outcome: OutcomeType = "unknown"
    reviewed_at: str | None = None
    reviewed_by: str | None = None


class JarvisDecisionListResponse(BaseModel):
    decisions: list[JarvisDecisionSummary] = Field(default_factory=list)


class JarvisDecisionDetail(JarvisDecisionSummary):
    read_only: bool = True
    execution_performed: bool = False


class JarvisDecisionIntelligence(BaseModel):
    decision_success_rate: float = 0.0
    approved_count: int = 0
    rejected_count: int = 0
    deferred_count: int = 0
    successful_outcomes: int = 0
    failed_outcomes: int = 0
    partial_outcomes: int = 0
    unknown_outcomes: int = 0
    total_decisions: int = 0
    most_common_rejected_recommendation: str | None = None
    most_common_rejected_count: int = 0
    most_successful_recommendation_type: str | None = None
    most_successful_count: int = 0
    repeated_findings_count: int = 0
    lessons_learned: list[str] = Field(default_factory=list)
    initiative_outcomes: dict[str, Any] = Field(default_factory=dict)
    read_only: bool = True


InitiativeStatus = Literal["planned", "active", "blocked", "completed", "cancelled"]
InitiativeHealth = Literal["green", "yellow", "red"]
InitiativePriority = Literal["critical", "high", "medium", "low"]


class JarvisInitiativeCreateRequest(BaseModel):
    title: str = Field(..., min_length=1)
    description: str = ""
    status: InitiativeStatus = "planned"
    priority: InitiativePriority = "medium"
    owner: str | None = None
    target_date: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    progress_pct: int = Field(default=0, ge=0, le=100)
    blocked_reason: str | None = None


class JarvisInitiativeUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    status: InitiativeStatus | None = None
    priority: InitiativePriority | None = None
    owner: str | None = None
    target_date: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    progress_pct: int | None = Field(default=None, ge=0, le=100)
    blocked_reason: str | None = None


class JarvisInitiativeSummary(BaseModel):
    initiative_id: str
    created_at: str | None = None
    updated_at: str | None = None
    title: str
    description: str = ""
    status: InitiativeStatus = "planned"
    priority: InitiativePriority = "medium"
    owner: str | None = None
    target_date: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    progress_pct: int = 0
    health: InitiativeHealth = "green"
    blocked_reason: str | None = None
    is_overdue: bool = False
    is_stalled: bool = False
    days_overdue: int = 0


class JarvisInitiativeListResponse(BaseModel):
    initiatives: list[JarvisInitiativeSummary] = Field(default_factory=list)


class JarvisInitiativeDetail(JarvisInitiativeSummary):
    read_only: bool = True
    execution_performed: bool = False


FollowupStatus = Literal["open", "acknowledged", "resolved", "dismissed"]
FollowupSeverity = Literal["low", "medium", "high", "critical"]


class JarvisFollowupSummary(BaseModel):
    followup_id: str
    created_at: str | None = None
    updated_at: str | None = None
    source_type: str
    source_id: str | None = None
    title: str
    description: str = ""
    severity: FollowupSeverity = "medium"
    status: FollowupStatus = "open"
    due_date: str | None = None
    assigned_to: str | None = None
    reminder_count: int = 0
    last_reminded_at: str | None = None
    is_overdue: bool = False


class JarvisFollowupListResponse(BaseModel):
    followups: list[JarvisFollowupSummary] = Field(default_factory=list)


class JarvisFollowupDetail(JarvisFollowupSummary):
    read_only: bool = True
    execution_performed: bool = False


class JarvisFollowupUpdateRequest(BaseModel):
    status: FollowupStatus | None = None
    severity: FollowupSeverity | None = None
    assigned_to: str | None = None
    description: str | None = None


class JarvisFollowupGenerateResponse(BaseModel):
    followups_touched: int = 0
    followup_ids: list[str] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    telegram_sent: bool = False
    read_only: bool = True
    execution_performed: bool = False


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
