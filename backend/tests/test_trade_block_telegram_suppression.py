"""Tests for suppressing expected trade-block / order-failure / small-position Telegram noise."""


def test_suppress_live_toggle_off():
    from app.utils.trading_guardrails import should_notify_trade_block_to_telegram

    assert should_notify_trade_block_to_telegram("blocked: Live toggle is OFF") is False


def test_suppress_trade_yes_off():
    from app.utils.trading_guardrails import should_notify_trade_block_to_telegram

    assert should_notify_trade_block_to_telegram("blocked: Trade Yes is OFF for ETH_USD") is False


def test_notify_unexpected_block_still_eligible_for_monitoring_gate():
    """should_notify is for Monitoring eligibility; live TG uses suppress_live_* separately."""
    from app.utils.trading_guardrails import should_notify_trade_block_to_telegram

    assert (
        should_notify_trade_block_to_telegram(
            "blocked: MAX_OPEN_ORDERS_TOTAL limit reached (10/10)"
        )
        is True
    )


def test_trade_block_cooldown_dedupes_repeated_alerts(monkeypatch):
    from app.utils import trading_guardrails as guardrails

    guardrails._trade_block_alert_times.clear()
    monkeypatch.setattr(guardrails, "_TRADE_BLOCK_ALERT_COOLDOWN_SECONDS", 1800)

    reason_a = "blocked: MAX_OPEN_ORDERS_TOTAL limit reached (22/10)"
    reason_b = "blocked: MAX_OPEN_ORDERS_TOTAL limit reached (23/10)"

    assert guardrails.should_send_trade_block_telegram_alert("DOT_USD", "BUY", reason_a) is True
    guardrails.mark_trade_block_telegram_sent("DOT_USD", "BUY", reason_a)

    assert guardrails.should_send_trade_block_telegram_alert("DOT_USD", "BUY", reason_b) is False
    assert guardrails.should_send_trade_block_telegram_alert("ETH_USD", "BUY", reason_a) is True
    assert guardrails.should_send_trade_block_telegram_alert("DOT_USD", "SELL", reason_a) is True


def test_trade_block_cooldown_allows_after_window(monkeypatch):
    from app.utils import trading_guardrails as guardrails

    guardrails._trade_block_alert_times.clear()
    monkeypatch.setattr(guardrails, "_TRADE_BLOCK_ALERT_COOLDOWN_SECONDS", 60)

    reason = "blocked: MAX_OPEN_ORDERS_TOTAL limit reached (22/10)"
    now = 1_000_000.0
    monkeypatch.setattr(guardrails.time, "time", lambda: now)

    assert guardrails.should_send_trade_block_telegram_alert("DOT_USD", "BUY", reason) is True
    guardrails.mark_trade_block_telegram_sent("DOT_USD", "BUY", reason)

    monkeypatch.setattr(guardrails.time, "time", lambda: now + 30)
    assert guardrails.should_send_trade_block_telegram_alert("DOT_USD", "BUY", reason) is False

    monkeypatch.setattr(guardrails.time, "time", lambda: now + 61)
    assert guardrails.should_send_trade_block_telegram_alert("DOT_USD", "BUY", reason) is True


def test_suppress_live_max_open_orders_total():
    from app.services.trade_block_telegram_policy import suppress_live_trade_block_telegram

    assert (
        suppress_live_trade_block_telegram(
            "blocked: MAX_OPEN_ORDERS_TOTAL limit reached (27/10)"
        )
        is True
    )


def test_suppress_live_system_core_max_open_trades():
    from app.services.trade_block_telegram_policy import (
        suppress_live_trade_block_telegram,
        suppress_order_failure_telegram,
    )

    reason = "system_core_max_open_trades count=3 max=3"
    assert suppress_live_trade_block_telegram(reason) is True
    assert (
        suppress_order_failure_telegram(
            reason, reason_code="SYSTEM_CORE_MAX_OPEN_TRADES"
        )
        is True
    )


def test_suppress_live_per_coin_and_open_orders_limit():
    from app.services.trade_block_telegram_policy import (
        suppress_live_trade_block_telegram,
        suppress_order_failure_telegram,
    )

    assert (
        suppress_live_trade_block_telegram("system_core_one_active_trade_per_coin")
        is True
    )
    assert (
        suppress_order_failure_telegram(
            "Maximum open orders reached for ETH_USD. 3/3.",
            reason_code="MAX_OPEN_TRADES_REACHED",
        )
        is True
    )
    assert suppress_live_trade_block_telegram("OPEN_ORDERS_LIMIT") is True
    assert (
        suppress_live_trade_block_telegram(
            "blocked: MAX_ORDERS_PER_SYMBOL_PER_DAY limit reached (2/2)"
        )
        is True
    )


def test_do_not_suppress_real_failures():
    from app.services.trade_block_telegram_policy import (
        suppress_live_trade_block_telegram,
        suppress_order_failure_telegram,
        suppress_small_position_unprotected_telegram,
    )

    assert (
        suppress_live_trade_block_telegram("blocked: authentication failed")
        is False
    )
    assert (
        suppress_order_failure_telegram(
            "306 INSUFFICIENT_AVAILABLE_BALANCE",
            reason_code="INSUFFICIENT_AVAILABLE_BALANCE",
        )
        is False
    )
    assert (
        suppress_order_failure_telegram(
            "InstanceDown probe failed",
            reason_code="EXCHANGE_ERROR_UNKNOWN",
        )
        is False
    )
    assert (
        suppress_small_position_unprotected_telegram(
            "CRITICAL: SL/TP FAILED — FLATTENING"
        )
        is False
    )
    assert (
        suppress_small_position_unprotected_telegram(
            "INSTRUMENT RULES MISSING\nUNPROTECTED_RULES_MISSING"
        )
        is False
    )


def test_suppress_small_position_unprotected():
    from app.services.trade_block_telegram_policy import (
        suppress_small_position_unprotected_telegram,
    )

    sample = (
        "⚠️ SMALL POSITION UNPROTECTED\n"
        "Symbol: BCH_USD\n"
        "Executed Qty: 0.00008900\n"
        "Position cannot be protected with SL/TP."
    )
    assert suppress_small_position_unprotected_telegram(sample) is True
    assert (
        suppress_small_position_unprotected_telegram(
            "quantity_below_min for BCH_USD"
        )
        is True
    )
