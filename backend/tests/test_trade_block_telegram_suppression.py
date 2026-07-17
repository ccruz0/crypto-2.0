"""Tests for suppressing expected trade-block Telegram noise when trading is off."""


def test_suppress_live_toggle_off():
    from app.utils.trading_guardrails import should_notify_trade_block_to_telegram

    assert should_notify_trade_block_to_telegram("blocked: Live toggle is OFF") is False


def test_suppress_trade_yes_off():
    from app.utils.trading_guardrails import should_notify_trade_block_to_telegram

    assert should_notify_trade_block_to_telegram("blocked: Trade Yes is OFF for ETH_USD") is False


def test_notify_unexpected_block():
    from app.utils.trading_guardrails import should_notify_trade_block_to_telegram

    assert (
        should_notify_trade_block_to_telegram(
            "blocked: MAX_OPEN_ORDERS_TOTAL limit reached (10/10)"
        )
        is True
    )


def test_trade_block_cooldown_dedupes_repeated_alerts(monkeypatch):
    from app.services.telegram_event_dedup import clear_memory_claims_for_tests
    from app.utils import trading_guardrails as guardrails

    guardrails._trade_block_alert_times.clear()
    clear_memory_claims_for_tests()
    monkeypatch.setattr(guardrails, "_TRADE_BLOCK_ALERT_COOLDOWN_SECONDS", 1800)

    reason_a = "blocked: MAX_OPEN_ORDERS_TOTAL limit reached (22/10)"
    reason_b = "blocked: MAX_OPEN_ORDERS_TOTAL limit reached (23/10)"

    assert guardrails.should_send_trade_block_telegram_alert("DOT_USD", "BUY", reason_a) is True
    guardrails.mark_trade_block_telegram_sent("DOT_USD", "BUY", reason_a)

    # Same incident: counter churn, other symbols, and opposite side must not re-page.
    assert guardrails.should_send_trade_block_telegram_alert("DOT_USD", "BUY", reason_b) is False
    assert guardrails.should_send_trade_block_telegram_alert("ETH_USD", "BUY", reason_a) is False
    assert guardrails.should_send_trade_block_telegram_alert("DOT_USD", "SELL", reason_a) is False


def test_trade_block_cooldown_allows_after_window(monkeypatch):
    from app.services.telegram_event_dedup import clear_memory_claims_for_tests
    from app.utils import trading_guardrails as guardrails

    guardrails._trade_block_alert_times.clear()
    clear_memory_claims_for_tests()
    monkeypatch.setattr(guardrails, "_TRADE_BLOCK_ALERT_COOLDOWN_SECONDS", 60)

    reason = "blocked: MAX_OPEN_ORDERS_TOTAL limit reached (22/10)"
    now = 1_000_000.0
    monkeypatch.setattr(guardrails.time, "time", lambda: now)

    assert guardrails.should_send_trade_block_telegram_alert("DOT_USD", "BUY", reason) is True
    guardrails.mark_trade_block_telegram_sent("DOT_USD", "BUY", reason)

    monkeypatch.setattr(guardrails.time, "time", lambda: now + 30)
    assert guardrails.should_send_trade_block_telegram_alert("DOT_USD", "BUY", reason) is False

    # Expire both the in-process claim and the memory cooldown window.
    clear_memory_claims_for_tests()
    guardrails._trade_block_alert_times.clear()
    monkeypatch.setattr(guardrails.time, "time", lambda: now + 61)
    assert guardrails.should_send_trade_block_telegram_alert("DOT_USD", "BUY", reason) is True


def test_non_global_blocks_still_dedupe_per_symbol(monkeypatch):
    from app.utils import trading_guardrails as guardrails

    guardrails._trade_block_alert_times.clear()
    monkeypatch.setattr(guardrails, "_TRADE_BLOCK_ALERT_COOLDOWN_SECONDS", 1800)

    reason = "blocked: MAX_ORDERS_PER_SYMBOL_PER_DAY limit reached (2/2)"

    assert guardrails.should_send_trade_block_telegram_alert("DOT_USD", "BUY", reason) is True
    guardrails.mark_trade_block_telegram_sent("DOT_USD", "BUY", reason)

    assert guardrails.should_send_trade_block_telegram_alert("DOT_USD", "BUY", reason) is False
    # Different symbol remains independent for non-global reasons.
    assert guardrails.should_send_trade_block_telegram_alert("ETH_USD", "BUY", reason) is True
