"""Pydantic validation for planner output (strict schema, rejects unknown fields)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

__all__ = ["PlanValidated", "validate_plan_dict"]


class PlanValidated(BaseModel):
    """Validated planner output: exactly action, args, reasoning — no extra keys."""

    model_config = ConfigDict(extra="forbid")

    action: str = Field(..., min_length=1, max_length=256)
    args: dict[str, Any] = Field(default_factory=dict)
    reasoning: str = Field(default="", max_length=8000)

    @field_validator("action")
    @classmethod
    def _strip_action(cls, v: str) -> str:
        s = (v or "").strip()
        if not s:
            raise ValueError("action cannot be empty")
        return s

    @field_validator("args")
    @classmethod
    def _args_must_be_dict(cls, v: Any) -> dict[str, Any]:
        if v is None:
            return {}
        if not isinstance(v, dict):
            raise ValueError("args must be a JSON object")
        return v


def validate_plan_dict(raw: dict[str, Any]) -> tuple[PlanValidated | None, str | None]:
    """
    Validate a parsed dict from the model. Returns (model, None) or (None, error_message).
    """
    try:
        return PlanValidated.model_validate(raw), None
    except ValidationError as e:
        return None, str(e.errors())[:500]
