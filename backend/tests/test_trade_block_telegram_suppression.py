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
