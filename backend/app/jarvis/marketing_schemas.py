"""Pydantic argument models for Jarvis marketing (read-only) tools."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MarketingAnalysisWindowArgs(BaseModel):
    """Shared window for analytics summaries (strict, no extra keys)."""

    model_config = ConfigDict(extra="forbid")

    days_back: int = Field(default=28, ge=1, le=365, description="Lookback window in days.")


class TopPagesByConversionArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days_back: int = Field(default=28, ge=1, le=365)
    limit: int = Field(default=10, ge=1, le=50, description="Max pages per strongest/weakest list.")


class AnalyzeMarketingOpportunitiesArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days_back: int = Field(default=28, ge=1, le=365)
    top_n: int = Field(default=5, ge=1, le=10, description="Max items per opportunities/wastes/gaps/recommendations.")


class ProposeMarketingActionsArgs(AnalyzeMarketingOpportunitiesArgs):
    """Same window as opportunity analysis; maps findings to proposed actions."""

    pass


class StageMarketingActionForApprovalArgs(AnalyzeMarketingOpportunitiesArgs):
    """Select one or more proposed marketing actions to store as pending approvals."""

    action_index: int | None = None
    action_indices: list[int] | None = None
    reason: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def _validate_selection_mode(self) -> "StageMarketingActionForApprovalArgs":
        has_single = self.action_index is not None
        has_multi = self.action_indices is not None
        if has_single == has_multi:
            raise ValueError("Provide exactly one of action_index or action_indices.")
        return self


class ExecuteMarketingProposalArgs(BaseModel):
    """Args for executing an approved staged marketing proposal (simulated)."""

    model_config = ConfigDict(extra="forbid")

    proposal: dict[str, Any]
    proposal_index: int = 0
    business: str = ""
    days_back: int = Field(default=28, ge=1, le=365)
    top_n: int = Field(default=5, ge=1, le=10)
    staging_reason: str | None = None
    staging_batch_id: str | None = None
