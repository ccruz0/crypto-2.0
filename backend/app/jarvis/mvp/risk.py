"""Deterministic risk classification for Jarvis tasks."""

from __future__ import annotations

import re
from typing import Literal

RiskLevel = Literal["low", "medium", "high"]

_HIGH_RISK_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bdelete\b.*\b(resources?|buckets?|databases?|db|volumes?|stacks?)\b",
        r"\bterminate\b.*\b(instances?|ec2|vms?|servers?)\b",
        r"\b(modify|change|update|edit)\b.*\b(trading order|open order|position)\b",
        r"\b(execute|place|submit)\b.*\b(trade|order|buy|sell)\b",
        r"\b(change|rotate|update|modify)\b.*\b(secrets?|credentials?|password|api keys?)\b",
        r"\b(modify|change|update|attach|detach)\b.*\b(iam|policy|role|permission)\b",
        r"\b(modify|change|update|deploy)\b.*\b(production|prod)\b.*\b(infrastructure|infra)\b",
        r"\b(drop|destroy|purge|wipe)\b",
        r"\bkill\b.*\b(instance|process|service)\b",
    )
]

_MEDIUM_RISK_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bpropose\b.*\b(restart|reboot|reload)\b",
        r"\b(restart|reboot|reload)\b.*\b(service|backend|container|instance)\b",
        r"\bpropose\b.*\b(config|configuration|env|runtime)\b",
        r"\b(change|update|modify)\b.*\b(config|configuration|env|runtime)\b",
        r"\bpropose\b.*\b(deploy|deployment|release|rollout)\b",
        r"\b(deploy|deployment|release|rollout)\b",
    )
]

_LOW_RISK_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(check|read|get|show|summarize|summary|status|health|estimate|cost|logs?)\b",
        r"\bdashboard\b",
        r"\bruntime\b.*\bstatus\b",
        r"\baws\b.*\bcost\b",
        r"\b(audit|analyze|review)\b.*\b(aws|infrastructure|ec2|ebs)\b",
        r"\baws\b.*\b(infrastructure|resources?)\b.*\baudit\b",
        r"\brun\b.*\baws\b.*\baudit\b",
        r"\b(run|audit|check|compare|reconcile)\b.*\b(crypto|portfolio|wallet)\b",
        r"\bportfolio\b.*\b(consistency|audit|reconcile)\b",
        r"\bcompare\b.*\b(exchange|dashboard)\b",
    )
]


def classify_task_risk(task: str) -> RiskLevel:
    """Classify task risk using keyword rules. High beats medium beats low."""
    text = (task or "").strip()
    if not text:
        return "low"

    if any(p.search(text) for p in _HIGH_RISK_PATTERNS):
        return "high"
    if any(p.search(text) for p in _MEDIUM_RISK_PATTERNS):
        return "medium"
    if any(p.search(text) for p in _LOW_RISK_PATTERNS):
        return "low"

    # Unknown intent defaults to medium so we stay conservative without blocking read-only work.
    return "medium"
