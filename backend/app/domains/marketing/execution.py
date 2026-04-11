"""Simulated execution for approved marketing proposals (no external API calls)."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def execute_marketing_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
    """
    Dispatch by ``proposal["action_type"]``. Returns a structured simulated result.

    Supported simulations: ``send_campaign``, ``update_budget``, ``launch_ad``.
    Any other type is handled with a safe no-side-effect simulated response.
    """
    if not isinstance(proposal, dict):
        return {
            "status": "executed",
            "action_type": None,
            "details": {"mode": "simulated", "note": "invalid proposal payload; expected object"},
        }

    action_type = (proposal.get("action_type") or "").strip()
    title = str(proposal.get("title") or "")
    target = proposal.get("target")
    source = str(proposal.get("source") or "")

    logger.info(
        "jarvis.marketing.execute_proposal action_type=%s title=%r source=%s",
        action_type,
        title[:80] if title else "",
        source,
    )

    if action_type == "send_campaign":
        return {
            "status": "executed",
            "action_type": action_type,
            "details": {
                "mode": "simulated",
                "operation": "send_campaign",
                "message": "Campaign send simulated (no external API).",
                "target": target,
            },
        }

    if action_type == "update_budget":
        return {
            "status": "executed",
            "action_type": action_type,
            "details": {
                "mode": "simulated",
                "operation": "update_budget",
                "message": "Budget update simulated (no external API).",
                "target": target,
            },
        }

    if action_type == "launch_ad":
        return {
            "status": "executed",
            "action_type": action_type,
            "details": {
                "mode": "simulated",
                "operation": "launch_ad",
                "message": "Ad launch simulated (no external API).",
                "target": target,
            },
        }

    logger.info(
        "jarvis.marketing.execute_proposal.unknown_action action_type=%s",
        action_type or "(empty)",
    )
    return {
        "status": "executed",
        "action_type": action_type or None,
        "details": {
            "mode": "simulated",
            "operation": "unsupported_action_type",
            "message": (
                "Unknown or non-explicit action_type; simulated no-op. "
                "Future tools may map this to concrete executors."
            ),
            "proposal_title": title or None,
        },
    }


def safe_execute_marketing_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
    """Try/except wrapper; never raises. Returns structured error on failure."""
    try:
        return execute_marketing_proposal(proposal)
    except Exception as e:
        logger.exception("jarvis.marketing.safe_execute_proposal_failed err=%s", e)
        return {"status": "error", "error": str(e)[:500]}
