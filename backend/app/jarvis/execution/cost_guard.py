"""Cost and retry guard for Jarvis task execution."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class CostGuardLimits:
    max_estimated_cost_usd: float = field(
        default_factory=lambda: float(os.environ.get("JARVIS_TASK_MAX_ESTIMATED_COST_USD", "5.0"))
    )
    max_actual_cost_usd: float = field(
        default_factory=lambda: float(os.environ.get("JARVIS_TASK_MAX_ACTUAL_COST_USD", "10.0"))
    )
    max_steps: int = field(default_factory=lambda: int(os.environ.get("JARVIS_TASK_MAX_STEPS", "20")))
    max_retries: int = field(default_factory=lambda: int(os.environ.get("JARVIS_TASK_MAX_RETRIES", "3")))
    max_duration_seconds: float = field(
        default_factory=lambda: float(os.environ.get("JARVIS_TASK_MAX_DURATION_SECONDS", "300"))
    )


class CostGuardViolation(Exception):
    """Raised when execution exceeds configured limits."""


@dataclass
class CostGuardState:
    step_count: int = 0
    retry_count: int = 0
    actual_cost_usd: float = 0.0
    seen_step_signatures: set[str] = field(default_factory=set)
    loop_detected: bool = False


class CostGuard:
    def __init__(self, limits: CostGuardLimits | None = None) -> None:
        self.limits = limits or CostGuardLimits()
        self.state = CostGuardState()

    def check_estimated_cost(self, estimated: float) -> None:
        if estimated > self.limits.max_estimated_cost_usd:
            raise CostGuardViolation(
                f"estimated cost ${estimated:.4f} exceeds limit ${self.limits.max_estimated_cost_usd:.4f}"
            )

    def begin_step(self, signature: str, *, step_cost_usd: float = 0.0) -> None:
        if self.state.step_count >= self.limits.max_steps:
            raise CostGuardViolation(f"step limit exceeded ({self.limits.max_steps})")
        if signature in self.state.seen_step_signatures:
            self.state.loop_detected = True
            raise CostGuardViolation(f"loop detected at step signature: {signature}")
        self.state.seen_step_signatures.add(signature)
        self.state.step_count += 1
        self.record_cost(step_cost_usd)

    def record_retry(self) -> None:
        self.state.retry_count += 1
        if self.state.retry_count > self.limits.max_retries:
            raise CostGuardViolation(f"retry limit exceeded ({self.limits.max_retries})")

    def record_cost(self, amount: float) -> None:
        self.state.actual_cost_usd += max(0.0, float(amount or 0.0))
        if self.state.actual_cost_usd > self.limits.max_actual_cost_usd:
            raise CostGuardViolation(
                f"actual cost ${self.state.actual_cost_usd:.4f} exceeds limit ${self.limits.max_actual_cost_usd:.4f}"
            )

    def check_duration(self, elapsed_seconds: float) -> None:
        if elapsed_seconds > self.limits.max_duration_seconds:
            raise CostGuardViolation(
                f"duration {elapsed_seconds:.1f}s exceeds limit {self.limits.max_duration_seconds:.1f}s"
            )
