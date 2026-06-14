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


class JarvisInvestigationRunRequest(BaseModel):
    objective: str = Field(..., min_length=1, description="Production diagnostic objective")


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

