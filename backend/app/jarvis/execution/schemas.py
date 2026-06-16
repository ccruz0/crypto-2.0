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
    review: dict[str, Any] = Field(default_factory=dict)
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


# --- Phase 4A: Production diagnostic investigations ---


class JarvisInvestigationImageAttachment(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    content_base64: str = Field(..., min_length=1, description="Base64-encoded image bytes")
    caption: str = Field(default="", max_length=500)
    content_type: str | None = Field(default=None, description="Optional MIME type hint")


class JarvisInvestigationRunRequest(BaseModel):
    objective: str = Field(..., min_length=1, description="Production diagnostic objective")
    attachments: list[JarvisInvestigationImageAttachment] = Field(
        default_factory=list,
        description="Optional image attachments as investigation evidence (read-only context)",
    )


class JarvisInvestigationRankedCause(BaseModel):
    cause: str
    score: float
    supporting_evidence: list[str] = Field(default_factory=list)
    explanation: str = ""


class JarvisInvestigationEvidence(BaseModel):
    source: str
    reference: str
    detail: str
    confidence: str = "medium"
    evidence_type: str | None = None
    artifact_id: str | None = None
    content_url: str | None = None
    mime_type: str | None = None


class JarvisInvestigationSummary(BaseModel):
    investigation_id: str
    objective: str
    status: str
    root_cause: str | None = None
    confidence: float = 0.0
    evidence_count: int = 0
    recommended_fix: str | None = None
    category: str = "api"
    created_at: str | None = None


class JarvisInvestigationDetail(BaseModel):
    investigation_id: str
    objective: str
    category: str = "api"
    template_id: str = "generic"
    status: str
    summary: str = ""
    evidence: list[JarvisInvestigationEvidence] = Field(default_factory=list)
    evidence_count: int = 0
    root_cause: str | None = None
    confidence: float = 0.0
    ranked_causes: list[JarvisInvestigationRankedCause] = Field(default_factory=list)
    impact: str = ""
    recommended_fix: str = ""
    verification_steps: list[str] = Field(default_factory=list)
    next_action: str = ""
    proposal_task_id: str | None = None
    proposal_status: str | None = None
    resolution_status: str | None = None
    created_at: str | None = None
    synthesis: dict[str, Any] = Field(default_factory=dict)
    missing_evidence: list[str] = Field(default_factory=list)
    evidence_sources: list[str] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    collector_failures: list[str] = Field(default_factory=list)
    passed: bool = False


class JarvisProposalEligibilityResponse(BaseModel):
    eligible: bool
    reasons: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    fix_template_candidates: list[dict[str, Any]] = Field(default_factory=list)
    existing_proposal_task_id: str | None = None
    primary_template: str | None = None
    score: int = 0
    template_score: int = 0
    template_confidence: float = 0.0
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    no_fix_required_reason: str | None = None


class JarvisFixTemplateSummary(BaseModel):
    fix_template_id: str
    description: str
    target_files: list[str] = Field(default_factory=list)
    supported_investigations: list[str] = Field(default_factory=list)
    risk_level: str


class JarvisFixTemplateListResponse(BaseModel):
    templates: list[JarvisFixTemplateSummary] = Field(default_factory=list)
    count: int = 0


class JarvisFixTemplateDetailResponse(BaseModel):
    fix_template_id: str
    description: str
    match_patterns: list[str] = Field(default_factory=list)
    target_files: list[str] = Field(default_factory=list)
    recommended_fix: str = ""
    risk_level: str = "low"
    test_paths: list[str] = Field(default_factory=list)
    validation_rules: list[str] = Field(default_factory=list)
    supported_investigations: list[str] = Field(default_factory=list)
    strategy: str = "template"
    root_cause_exact: str | None = None
    noop_reason: str = ""
    match: str = ""


class JarvisProposalTaskDetail(JarvisExecutionTaskDetail):
    workflow_type: str = "phase4b_patch_proposal"
    source_investigation_id: str | None = None
    fix_template_id: str | None = None
    sandbox_summary: dict[str, Any] = Field(default_factory=dict)


class JarvisInvestigationListResponse(BaseModel):
    investigations: list[JarvisInvestigationSummary] = Field(default_factory=list)


class JarvisInvestigationPreset(BaseModel):
    id: str
    label: str
    objective: str


class JarvisInvestigationPresetsResponse(BaseModel):
    presets: list[JarvisInvestigationPreset] = Field(default_factory=list)


# --- Phase 4C: Investigation quality analytics (read-only) ---


class JarvisAnalyticsInvestigationMetrics(BaseModel):
    total_investigations: int = 0
    completed: int = 0
    resolved: int = 0
    insufficient_evidence: int = 0
    partial_failure: int = 0
    failed: int = 0
    running: int = 0
    average_duration_ms: float = 0.0
    median_duration_ms: float = 0.0
    success_rate_pct: float = 0.0
    failure_rate_pct: float = 0.0
    insufficient_evidence_rate_pct: float = 0.0
    false_positives: int = 0
    tool_errors_inferred: int = 0


class JarvisAnalyticsQualityScore(BaseModel):
    overall_score: float = 100.0
    last_7_days: float = 100.0
    last_30_days: float = 100.0
    formula: dict[str, Any] = Field(default_factory=dict)


class JarvisAnalyticsPeriodRates(BaseModel):
    completion_rate_pct: float = 0.0
    resolution_rate_pct: float = 0.0
    false_positive_rate_pct: float = 0.0


class JarvisAnalyticsDailyTrend(BaseModel):
    date: str
    total: int = 0
    completed: int = 0
    failed: int = 0
    insufficient_evidence: int = 0
    resolved: int = 0
    false_positives: int = 0
    success_rate_pct: float = 0.0


class JarvisAnalyticsQualityTrend(BaseModel):
    date: str
    quality_score: float = 100.0


class JarvisAnalyticsOverviewResponse(BaseModel):
    investigations: JarvisAnalyticsInvestigationMetrics
    quality_score: JarvisAnalyticsQualityScore
    period_rates: dict[str, JarvisAnalyticsPeriodRates] = Field(default_factory=dict)
    trends: dict[str, Any] = Field(default_factory=dict)
    read_only: bool = True


class JarvisAnalyticsTemplateRow(BaseModel):
    template_id: str
    investigations: int = 0
    completed: int = 0
    failed: int = 0
    insufficient_evidence: int = 0
    completion_rate_pct: float = 0.0
    failure_rate_pct: float = 0.0
    insufficient_evidence_rate_pct: float = 0.0
    average_confidence: float = 0.0


class JarvisAnalyticsTemplatesResponse(BaseModel):
    templates: list[JarvisAnalyticsTemplateRow] = Field(default_factory=list)
    count: int = 0
    read_only: bool = True


class JarvisAnalyticsToolError(BaseModel):
    message: str
    count: int = 0


class JarvisAnalyticsToolRow(BaseModel):
    tool: str
    executions: int = 0
    successes: int = 0
    failures: int = 0
    success_rate_pct: float = 0.0
    failure_rate_pct: float = 0.0
    average_duration_ms: float = 0.0
    common_errors: list[JarvisAnalyticsToolError] = Field(default_factory=list)


class JarvisAnalyticsToolsResponse(BaseModel):
    tools: list[JarvisAnalyticsToolRow] = Field(default_factory=list)
    count: int = 0
    noisiest_tools: list[JarvisAnalyticsToolRow] = Field(default_factory=list)
    read_only: bool = True


class JarvisAnalyticsProposalFunnel(BaseModel):
    proposals_generated: int = 0
    no_fix_required: int = 0
    waiting_for_approval: int = 0
    approved: int = 0
    rejected: int = 0
    failed: int = 0
    proposing: int = 0
    useful_proposals: int = 0
    useful_rate_pct: float = 0.0


class JarvisAnalyticsProposalsResponse(BaseModel):
    proposals: JarvisAnalyticsProposalFunnel
    proposal_tasks: int = 0
    read_only: bool = True


class JarvisAnalyticsRootCauseRow(BaseModel):
    root_cause: str
    occurrences: int = 0
    key: str = ""


class JarvisAnalyticsIncidentRow(BaseModel):
    investigation_id: str | None = None
    objective: str | None = None
    root_cause: str
    status: str | None = None
    confidence: float = 0.0
    created_at: str | None = None


class JarvisAnalyticsRootCausesResponse(BaseModel):
    most_common_root_causes: list[JarvisAnalyticsRootCauseRow] = Field(default_factory=list)
    recurring_incidents: list[JarvisAnalyticsRootCauseRow] = Field(default_factory=list)
    resolved_incidents: list[JarvisAnalyticsIncidentRow] = Field(default_factory=list)
    active_incidents: list[JarvisAnalyticsIncidentRow] = Field(default_factory=list)
    unique_root_causes: int = 0
    read_only: bool = True


# --- Phase 4D: Self-improvement recommendation engine (read-only) ---


class JarvisImprovementRecommendation(BaseModel):
    id: str
    category: str
    priority: str
    priority_score: float = 0.0
    title: str
    recommendation: str
    reason: str
    evidence: list[str] = Field(default_factory=list)
    expected_benefit: str = ""
    impact: str = "medium"
    frequency: int = 0
    confidence: float = 50.0


class JarvisImprovementRecommendationsResponse(BaseModel):
    recommendations: list[JarvisImprovementRecommendation] = Field(default_factory=list)
    backlog: list[JarvisImprovementRecommendation] = Field(default_factory=list)
    by_priority: dict[str, list[JarvisImprovementRecommendation]] = Field(default_factory=dict)
    counts: dict[str, int] = Field(default_factory=dict)
    read_only: bool = True


class JarvisImprovementTemplateGap(BaseModel):
    gap_type: str
    template_id: str | None = None
    category: str | None = None
    investigations: int = 0
    severity: str = "medium"
    insufficient_evidence: int | None = None
    insufficient_evidence_rate_pct: float | None = None
    generic_rate_pct: float | None = None
    failure_rate_pct: float | None = None
    top_keywords: list[str] = Field(default_factory=list)
    templates_used: dict[str, int] = Field(default_factory=dict)


class JarvisImprovementTemplatesResponse(BaseModel):
    gaps: list[JarvisImprovementTemplateGap] = Field(default_factory=list)
    recommendations: list[JarvisImprovementRecommendation] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    template_metrics: list[JarvisAnalyticsTemplateRow] = Field(default_factory=list)
    read_only: bool = True


class JarvisImprovementToolEffectiveness(BaseModel):
    tool: str
    category: str = "diagnostic"
    assessment_display: str = "Diagnostic Tool"
    executions: int = 0
    successes: int = 0
    failures: int = 0
    success_rate_pct: float = 0.0
    useful_outcomes: int = 0
    investigations_using: int = 0
    utility_ratio: float = 0.0
    useful_findings: int = 0
    false_positive_contribution: int = 0
    workflow_usage_rate: float | None = None
    successful_completion_rate: float | None = None
    failure_association_rate: float | None = None
    average_duration_ms: float = 0.0
    assessment: str = "moderate"


class JarvisImprovementToolsResponse(BaseModel):
    tools: list[JarvisImprovementToolEffectiveness] = Field(default_factory=list)
    low_utility_tools: list[JarvisImprovementToolEffectiveness] = Field(default_factory=list)
    high_value_tools: list[JarvisImprovementToolEffectiveness] = Field(default_factory=list)
    recommendations: list[JarvisImprovementRecommendation] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    read_only: bool = True


class JarvisImprovementTrendsResponse(BaseModel):
    quality_scores: dict[str, Any] = Field(default_factory=dict)
    false_positives: dict[str, Any] = Field(default_factory=dict)
    period_rates: dict[str, Any] = Field(default_factory=dict)
    recurring_incidents: list[JarvisAnalyticsRootCauseRow] = Field(default_factory=list)
    open_orders_share_pct: float = 0.0
    quality_score_daily: list[JarvisAnalyticsQualityTrend] = Field(default_factory=list)
    recommendations: list[JarvisImprovementRecommendation] = Field(default_factory=list)
    read_only: bool = True


class JarvisImprovementQualityResponse(BaseModel):
    quality_score: float = 0.0
    recommendation_count: int = 0
    high_priority_count: int = 0
    suppressed_recommendations: int = 0
    duplicate_recommendations: int = 0
    evidence_coverage: float = 0.0
    read_only: bool = True

