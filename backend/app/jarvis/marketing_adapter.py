"""Jarvis adapter: re-exports marketing domain execution for core callers."""

from app.domains.marketing.execution import execute_marketing_proposal, safe_execute_marketing_proposal

__all__ = ["execute_marketing_proposal", "safe_execute_marketing_proposal"]
