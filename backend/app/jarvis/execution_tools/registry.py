"""Typed tool interfaces for Jarvis read-only execution."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

ToolFn = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    handler: ToolFn
    timeout_seconds: float = 30.0
    read_only: bool = True
    estimated_cost_usd: float = 0.01


@dataclass
class ToolExecutionResult:
    tool: str
    ok: bool
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_ms: int = 0


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        return sorted(self._tools.keys())

    def execute(self, name: str, **kwargs: Any) -> ToolExecutionResult:
        spec = self.get(name)
        if spec is None:
            return ToolExecutionResult(tool=name, ok=False, error=f"unknown tool: {name}")
        if not spec.read_only:
            return ToolExecutionResult(tool=name, ok=False, error="write tools disabled in Phase 3")

        started = time.perf_counter()
        try:
            output = spec.handler(**kwargs)
            duration_ms = int((time.perf_counter() - started) * 1000)
            if duration_ms > int(spec.timeout_seconds * 1000):
                logger.warning("tool %s exceeded timeout budget (%ss)", name, spec.timeout_seconds)
            return ToolExecutionResult(tool=name, ok=True, output=output, duration_ms=duration_ms)
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            logger.warning("tool %s failed: %s", name, exc)
            return ToolExecutionResult(tool=name, ok=False, error=str(exc), duration_ms=duration_ms)


def build_default_registry() -> ToolRegistry:
    from app.jarvis.execution_tools.inspect_container import inspect_container
    from app.jarvis.execution_tools.inspect_costs import inspect_costs
    from app.jarvis.execution_tools.inspect_health import inspect_health
    from app.jarvis.execution_tools.inspect_repository import inspect_repository
    from app.jarvis.execution_tools.inspect_runtime import inspect_runtime
    from app.jarvis.execution_tools.read_logs import read_logs

    registry = ToolRegistry()
    for fn, desc in (
        (read_logs, "Read recent application log summary (read-only)"),
        (inspect_container, "Inspect running container status (read-only)"),
        (inspect_repository, "Inspect repository layout and git status (read-only)"),
        (inspect_runtime, "Inspect runtime environment flags (read-only)"),
        (inspect_health, "Inspect dashboard/API health endpoints (read-only)"),
        (inspect_costs, "Inspect cost snapshot stub (read-only)"),
    ):
        registry.register(
            ToolSpec(
                name=fn.__name__,
                description=desc,
                handler=fn,
            )
        )
    return registry
