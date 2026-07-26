"""Ops-only synthetic order ids (not real exchange fills)."""

OPS_STUB_CLOSED_PREFIX = "STUB-CLOSED-"


def is_ops_stub_closed_order_id(order_id: str | None) -> bool:
    """True for bandaid FILLED rows used to stop ensure recreation."""
    return bool(order_id and str(order_id).upper().startswith(OPS_STUB_CLOSED_PREFIX))
