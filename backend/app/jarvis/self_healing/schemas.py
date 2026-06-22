"""Pydantic API schemas for the Jarvis Self-Healing Advisor (Phase 7)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SelfHealingAssessment(BaseModel):
    confidence: float = 0.0
    severity: str = "medium"
    blast_radius: str = "unknown"
    fixability: str = "not_fixable"
    has_meaningful_root_cause: bool = False


class SelfHealingFixRecommendation(BaseModel):
    proposed_fix: str = ""
    affected_files: list[str] = Field(default_factory=list)
    estimated_risk: str = "medium"
    estimated_effort: str = "medium"
    fix_template_id: str | None = None
    test_paths: list[str] = Field(default_factory=list)
    validation_rules: list[str] = Field(default_factory=list)
    has_template: bool = False


class SelfHealingAcwPackage(BaseModel):
    acw_ready: bool = False
    threshold: float = 70.0
    reasons: list[str] = Field(default_factory=list)
    proposed_objective: str = ""
    implementation_plan: list[str] = Field(default_factory=list)
    expected_files: list[str] = Field(default_factory=list)
    expected_tests: list[str] = Field(default_factory=list)


class SelfHealingSafety(BaseModel):
    allowed: bool = True
    blocked_domains: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class SelfHealingRecommendationResponse(BaseModel):
    investigation_id: str
    generated_at: str = ""
    enabled: bool = False
    status: str = ""
    root_cause: str | None = None
    confidence: float = 0.0
    assessment: SelfHealingAssessment = Field(default_factory=SelfHealingAssessment)
    recommendation: SelfHealingFixRecommendation = Field(default_factory=SelfHealingFixRecommendation)
    acw: SelfHealingAcwPackage = Field(default_factory=SelfHealingAcwPackage)
    safety: SelfHealingSafety = Field(default_factory=SelfHealingSafety)
    proposed_fix: str = ""
    affected_files: list[str] = Field(default_factory=list)
    estimated_risk: str = "medium"
    acw_ready: bool = False
    available_actions: list[str] = Field(default_factory=list)


class SelfHealingAcwTaskResponse(BaseModel):
    investigation_id: str | None = None
    acw_task: dict[str, Any] = Field(default_factory=dict)
    recommendation: SelfHealingRecommendationResponse | None = None
    created_by: str = ""
    created_at: str = ""


class SelfHealingDecisionRequest(BaseModel):
    decision: str = Field(..., description="ignore | investigate_further")
    actor_id: str = "operator"


class SelfHealingDecisionResponse(BaseModel):
    investigation_id: str
    decision: str
    recorded_at: str = ""
    actor_id: str = ""
    suggested_objective: str | None = None
    missing_evidence: list[str] = Field(default_factory=list)


class SelfHealingAcwTaskRequest(BaseModel):
    actor_id: str = "self_healing_advisor"
    priority: str = "normal"


class SelfHealingSafetyStatusResponse(BaseModel):
    self_healing_enabled: bool = False
    acw_threshold: float = 70.0
    auto_execution: bool = False
    auto_merge: bool = False
    auto_deploy: bool = False
    human_approval_required: bool = True
