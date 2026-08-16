"""Process-local failure/fallback counters for the Jarvis Bedrock layer.

Rationale (R6, point 3): ``ask_bedrock`` used to return an empty string on any
failure, so production silently ran on heuristic fallbacks for days with no
signal. This module gives every failure and every heuristic fallback a *counted*
event that can be scraped or shipped to CloudWatch, so degradation is visible
instead of silent.

The counters are deliberately dependency-free (a plain in-process dict) so this
module can be imported anywhere without pulling in boto3 or a metrics client.
A sink can be registered (e.g. to emit a CloudWatch EMF line or a Prometheus
counter) via :func:`register_sink`; if none is registered, counting still works
and remains queryable via :func:`snapshot`.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from collections.abc import Callable

logger = logging.getLogger(__name__)

# Metric names — stable strings so dashboards/alerts can key off them.
BEDROCK_INVOCATION_FAILURES = "bedrock_invocation_failures"
BEDROCK_HEURISTIC_FALLBACKS = "bedrock_heuristic_fallbacks"

_lock = threading.Lock()
_counters: dict[tuple[str, str], int] = defaultdict(int)

# Optional external sink: called as sink(metric, kind, value) on every increment.
_Sink = Callable[[str, str, int], None]
_sink: _Sink | None = None


def register_sink(sink: _Sink | None) -> None:
    """Register (or clear, with ``None``) an external metrics sink.

    The sink is invoked synchronously on each increment. It must never raise;
    any exception it throws is swallowed and logged so metrics can never take
    down a request path.
    """
    global _sink
    _sink = sink


def increment(metric: str, kind: str = "unknown", value: int = 1) -> None:
    """Increment ``metric`` labelled with ``kind`` by ``value``."""
    with _lock:
        _counters[(metric, kind)] += value
        current = _counters[(metric, kind)]
    if _sink is not None:
        try:
            _sink(metric, kind, value)
        except Exception:  # noqa: BLE001 — a metrics sink must never break the caller
            logger.exception("failure_metrics sink raised for %s[%s]", metric, kind)
    logger.debug("metric %s[%s] -> %d", metric, kind, current)


def record_invocation_failure(kind: str) -> None:
    """Count a hard Bedrock invocation failure of class ``kind``."""
    increment(BEDROCK_INVOCATION_FAILURES, kind)


def record_heuristic_fallback(kind: str) -> None:
    """Count a degradation to a heuristic fallback triggered by class ``kind``."""
    increment(BEDROCK_HEURISTIC_FALLBACKS, kind)


def snapshot() -> dict[str, int]:
    """Return a copy of all counters as ``{"metric[kind]": value}``."""
    with _lock:
        return {f"{metric}[{kind}]": v for (metric, kind), v in _counters.items()}


def reset() -> None:
    """Clear all counters. Intended for tests."""
    with _lock:
        _counters.clear()
