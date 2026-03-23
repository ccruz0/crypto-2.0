"""
Hard stops for unapproved PROD mutations when ATP_GOVERNANCE_ENFORCE=true on AWS.

See governance_service.prod_mutation_blocked_message.
"""

from __future__ import annotations

from fastapi import HTTPException

from app.services.governance_service import prod_mutation_blocked_message


def raise_if_backend_restart_blocked() -> None:
    msg = prod_mutation_blocked_message("POST /api/monitoring/backend/restart")
    if msg:
        raise HTTPException(status_code=403, detail=msg)
