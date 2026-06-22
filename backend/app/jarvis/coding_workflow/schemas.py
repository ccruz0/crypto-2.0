"""Pydantic schemas for Autonomous Coding Workflow (ACW)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.jarvis.execution.schemas import TaskPriority

WORKFLOW_TYPE = "coding_workflow"


class CodingWorkflowSubmitRequest(BaseModel):
    objective: str = Field(..., min_length=1)
    priority: TaskPriority = "normal"
    target_files: list[str] = Field(default_factory=list)


class CodingWorkflowEvidenceSummary(BaseModel):
    repository_modules: int = 0
    code_references: list[str] = Field(default_factory=list)
    production_evidence_count: int = 0
    safety_level: str = ""
    safety_notes: list[str] = Field(default_factory=list)


class CodingWorkflowApprovalPackage(BaseModel):
    objective: str
    task_id: str
    workflow_type: str = WORKFLOW_TYPE
    plan: dict[str, Any] = Field(default_factory=dict)
    evidence_summary: CodingWorkflowEvidenceSummary = Field(default_factory=CodingWorkflowEvidenceSummary)
    patch_diff_summary: str = ""
    full_patch_artifact: str = "patch.diff"
    risk_score: int = 0
    forbidden_path_check: dict[str, Any] = Field(default_factory=dict)
    sandbox_test_results: dict[str, Any] | None = None
    required_approvals: list[str] = Field(default_factory=lambda: ["gate1_apply", "gate2_pr"])
    pr_creation_eligible: bool = False


class CodingWorkflowTaskDetail(BaseModel):
    task_id: str
    objective: str
    status: str
    workflow_type: str = WORKFLOW_TYPE
    plan: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    review: dict[str, Any] = Field(default_factory=dict)
    approval_package: dict[str, Any] = Field(default_factory=dict)
    execution_log: list[dict[str, Any]] = Field(default_factory=list)
    approvals: list[dict[str, Any]] = Field(default_factory=list)
    phase5: dict[str, Any] = Field(default_factory=dict)


class CodingWorkflowArtifactsResponse(BaseModel):
    task_id: str
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
