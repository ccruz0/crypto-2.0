"""Tests for order-failure / TRADE_BLOCKED Control-feed telegram throttling."""

from app.services.telegram_event_dedup import clear_memory_claims_for_tests


def setup_function():
    clear_memory_claims_for_tests()


def teardown_function():
    clear_memory_claims_for_tests()


def test_order_failure_claim_allows_once_then_suppresses():
    from app.services.order_failure_telegram_policy import claim_order_failure_telegram

    assert (
        claim_order_failure_telegram(
            None, "ALGO_USD", "INSUFFICIENT_FUNDS", side="BUY", ttl_minutes=60
        )
        is True
    )
    assert (
        claim_order_failure_telegram(
            None, "ALGO_USD", "INSUFFICIENT_FUNDS", side="BUY", ttl_minutes=60
        )
        is False
    )
    # Different symbol / side / reason remain independent
    assert (
        claim_order_failure_telegram(
            None, "ETH_USD", "INSUFFICIENT_FUNDS", side="BUY", ttl_minutes=60
        )
        is True
    )
    assert (
        claim_order_failure_telegram(
            None, "ALGO_USD", "INSUFFICIENT_FUNDS", side="SELL", ttl_minutes=60
        )
        is True
    )
    assert (
        claim_order_failure_telegram(
            None, "ALGO_USD", "AUTHENTICATION_ERROR", side="BUY", ttl_minutes=60
        )
        is True
    )


def test_trade_block_ui_claim_dedupes_counter_variants():
    from app.services.order_failure_telegram_policy import claim_trade_block_monitoring_row

    reason_a = "blocked: MAX_OPEN_ORDERS_TOTAL limit reached (40/40)"
    reason_b = "blocked: MAX_OPEN_ORDERS_TOTAL limit reached (41/40)"

    assert (
        claim_trade_block_monitoring_row(
            None, "ALGO_USD", "BUY", reason_a, chronic=True, ttl_minutes=60
        )
        is True
    )
    assert (
        claim_trade_block_monitoring_row(
            None, "ALGO_USD", "BUY", reason_b, chronic=True, ttl_minutes=60
        )
        is False
    )
    assert (
        claim_trade_block_monitoring_row(
            None, "ETH_USDT", "BUY", reason_a, chronic=True, ttl_minutes=60
        )
        is True
    )


def test_emit_trade_blocked_persists_only_first_row(monkeypatch):
    from app.services import signal_monitor as sm

    calls = []

    def _fake_add(**kwargs):
        calls.append(kwargs)
        return 1

    monkeypatch.setattr(sm, "record_signal_event", lambda **kwargs: None)
    monkeypatch.setattr(
        "app.api.routes_monitoring.add_telegram_message", _fake_add, raising=False
    )
    # Patch where emit imports it
    import app.api.routes_monitoring as mon

    monkeypatch.setattr(mon, "add_telegram_message", _fake_add)

    reason = "blocked: límite diario por símbolo (3/2 órdenes hoy)"
    sm._emit_lifecycle_event(
        db=None,
        symbol="ETH_USDT",
        strategy_key="auto:conservative",
        side="BUY",
        price=1920.0,
        event_type="TRADE_BLOCKED",
        event_reason=reason,
        decision_reason=None,
    )
    sm._emit_lifecycle_event(
        db=None,
        symbol="ETH_USDT",
        strategy_key="auto:conservative",
        side="BUY",
        price=1921.0,
        event_type="TRADE_BLOCKED",
        event_reason=reason,
        decision_reason=None,
    )
    assert len(calls) == 1
    assert calls[0]["throttle_status"] == "TRADE_BLOCKED"


def test_emit_order_failed_respects_persist_flag(monkeypatch):
    from app.services import signal_monitor as sm

    calls = []

    def _fake_add(**kwargs):
        calls.append(kwargs)
        return 1

    monkeypatch.setattr(sm, "record_signal_event", lambda **kwargs: None)
    import app.api.routes_monitoring as mon

    monkeypatch.setattr(mon, "add_telegram_message", _fake_add)

    sm._emit_lifecycle_event(
        db=None,
        symbol="ALGO_USD",
        strategy_key="auto:conservative",
        side="BUY",
        price=0.08,
        event_type="ORDER_FAILED",
        event_reason="order_placement_failed",
        error_message="306 INSUFFICIENT_AVAILABLE_BALANCE",
        persist_monitoring_message=False,
    )
    assert calls == []

    sm._emit_lifecycle_event(
        db=None,
        symbol="ALGO_USD",
        strategy_key="auto:conservative",
        side="BUY",
        price=0.08,
        event_type="ORDER_FAILED",
        event_reason="order_placement_failed",
        error_message="306 INSUFFICIENT_AVAILABLE_BALANCE",
        persist_monitoring_message=True,
    )
    assert len(calls) == 1
    assert calls[0]["throttle_status"] == "ORDER_FAILED"
