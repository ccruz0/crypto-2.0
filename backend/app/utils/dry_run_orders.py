"""Helpers for dry-run / synthetic order ids (not real exchange fills)."""

from __future__ import annotations


def is_dry_run_order_id(order_id: str | None) -> bool:
    """True for synthetic dry-run ids (`dry_*`, `dry_market_*`, `dry_client_*`)."""
    if not order_id:
        return False
    oid = str(order_id).strip().lower()
    return oid.startswith("dry_")
