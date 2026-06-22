"""Jarvis Self-Healing Advisor (Phase 7).

Read-only recommendation layer that turns a completed investigation into a safe
fix recommendation and, when confidence is high enough, prepares an ACW task.

Jarvis never modifies production, deploys, merges, places trades, or executes
fixes automatically. This module only *proposes* changes; human approval and the
existing two-gate ACW/Phase 5 workflow remain mandatory.
"""

from app.jarvis.self_healing.assessment import RootCauseAssessment, assess_root_cause
from app.jarvis.self_healing.recommendation import FixRecommendation, recommend_fix
from app.jarvis.self_healing.service import (
    SelfHealingError,
    attach_self_healing,
    build_recommendation,
    create_acw_task_from_recommendation,
    generate_recommendation_for_investigation,
)

__all__ = [
    "FixRecommendation",
    "RootCauseAssessment",
    "SelfHealingError",
    "assess_root_cause",
    "attach_self_healing",
    "build_recommendation",
    "create_acw_task_from_recommendation",
    "generate_recommendation_for_investigation",
    "recommend_fix",
]
