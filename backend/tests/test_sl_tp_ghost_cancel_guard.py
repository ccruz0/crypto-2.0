"""Guards against false CANCELLED of live SL/TP (ghost cleanup / recreate loops)."""

from types import SimpleNamespace

from app.services.sl_tp_protection import (
    GHOST_CANCEL_GRACE_SECONDS,
    is_protection_order,
    should_mark_unresolved_order_cancelled,
)


def test_is_protection_order_by_role_and_type():
    assert is_protection_order(order_role="TAKE_PROFIT", order_type="LIMIT") is True
    assert is_protection_order(order_role="STOP_LOSS", order_type="MARKET") is True
    assert is_protection_order(order_role=None, order_type="TAKE_PROFIT_LIMIT") is True
    assert is_protection_order(order_role=None, order_type="STOP_LIMIT") is True
    assert is_protection_order(order_role=None, order_type="MARKET") is False


def test_ghost_cancel_skips_protection_even_when_stale():
    tp = SimpleNamespace(order_role="TAKE_PROFIT", order_type="TAKE_PROFIT_LIMIT")
    may_cancel, reason = should_mark_unresolved_order_cancelled(
        tp, age_seconds=GHOST_CANCEL_GRACE_SECONDS + 600
    )
    assert may_cancel is False
    assert reason == "protection_requires_exchange_confirmation"


def test_ghost_cancel_skips_stop_limit_without_role():
    sl = SimpleNamespace(order_role=None, order_type="STOP_LIMIT")
    may_cancel, reason = should_mark_unresolved_order_cancelled(sl, age_seconds=10_000)
    assert may_cancel is False
    assert reason == "protection_requires_exchange_confirmation"


def test_ghost_cancel_allows_stale_non_protection():
    entry = SimpleNamespace(order_role=None, order_type="LIMIT")
    may_cancel, reason = should_mark_unresolved_order_cancelled(
        entry, age_seconds=GHOST_CANCEL_GRACE_SECONDS + 1
    )
    assert may_cancel is True
    assert reason == "stale_non_protection_ghost"


def test_ghost_cancel_respects_grace_for_non_protection():
    entry = SimpleNamespace(order_role=None, order_type="MARKET")
    may_cancel, reason = should_mark_unresolved_order_cancelled(
        entry, age_seconds=GHOST_CANCEL_GRACE_SECONDS - 1
    )
    assert may_cancel is False
    assert reason == "within_grace"


def test_ghost_cancel_unknown_age_never_cancels():
    entry = SimpleNamespace(order_role=None, order_type="LIMIT")
    may_cancel, reason = should_mark_unresolved_order_cancelled(entry, age_seconds=None)
    assert may_cancel is False
    assert reason == "within_grace"
