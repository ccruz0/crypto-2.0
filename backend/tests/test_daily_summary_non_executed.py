"""Tests for daily-summary rollup of non-executed orders."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.daily_summary import DailySummaryService
from app.utils.decision_reason import ReasonCode, classify_exchange_error


def _row(
    *,
    reason_code,
    throttle_reason=None,
    reason_message=None,
    symbol="DOT_USD",
    decision_type="SKIPPED",
    timestamp=None,
    order_skipped=False,
    throttle_status="TRADE_BLOCKED",
):
    return SimpleNamespace(
        reason_code=reason_code,
        throttle_reason=throttle_reason,
        reason_message=reason_message,
        symbol=symbol,
        decision_type=decision_type,
        timestamp=timestamp or datetime.now(timezone.utc),
        order_skipped=order_skipped,
        throttle_status=throttle_status,
    )


def test_bucket_key_collapses_max_open_orders_counters():
    row_a = _row(
        reason_code="GUARDRAIL_BLOCKED",
        throttle_reason="blocked: MAX_OPEN_ORDERS_TOTAL limit reached (27/10)",
    )
    row_b = _row(
        reason_code="GUARDRAIL_BLOCKED",
        throttle_reason="blocked: MAX_OPEN_ORDERS_TOTAL limit reached (28/10)",
    )
    key_a, label_a = DailySummaryService._non_executed_bucket_key(row_a)
    key_b, label_b = DailySummaryService._non_executed_bucket_key(row_b)
    assert key_a == key_b == "MAX_OPEN_ORDERS_TOTAL"
    assert "Tope global" in label_a
    assert label_a == label_b


def test_bucket_key_amount_usd():
    row = _row(
        reason_code="INVALID_TRADE_AMOUNT",
        throttle_reason=None,
        reason_message="Amount USD not configured for ETH_USD",
    )
    key, label = DailySummaryService._non_executed_bucket_key(row)
    assert key == "INVALID_TRADE_AMOUNT"
    assert "Amount USD" in label


def test_bucket_key_telegram_api_not_guardrail():
    row = _row(
        reason_code="GUARDRAIL_BLOCKED",
        throttle_reason=(
            "Telegram API error: unknown - 400 Client Error: Bad Request for url: "
            "https://api.telegram.org/bot123456:AAHsecret/sendMessage"
        ),
    )
    key, label = DailySummaryService._non_executed_bucket_key(row)
    assert key == "TELEGRAM_API_ERROR"
    assert "Guardrail" not in label
    assert "Telegram" in label
    assert "AAHsecret" not in label
    assert "bot123456" not in label


def test_bucket_key_portfolio_value_limit():
    row = _row(
        reason_code="GUARDRAIL_BLOCKED",
        throttle_reason="blocked: PORTFOLIO_VALUE_LIMIT",
    )
    key, label = DailySummaryService._non_executed_bucket_key(row)
    assert key == "PORTFOLIO_VALUE_LIMIT"
    assert "portfolio" in label.lower()


def test_format_non_executed_orders_summary_empty():
    svc = DailySummaryService()
    text = svc.format_non_executed_orders_summary(
        {"hours": 24, "total_events": 0, "total_episodes": 0, "unique_symbols": 0, "buckets": []}
    )
    assert "Órdenes no ejecutadas" in text
    assert "Ningún bloqueo" in text or "Ningún intento" in text


def test_format_non_executed_orders_summary_episodes():
    svc = DailySummaryService()
    text = svc.format_non_executed_orders_summary(
        {
            "hours": 24,
            "total_events": 2,
            "total_episodes": 2,
            "unique_symbols": 2,
            "buckets": [
                {
                    "key": "MAX_OPEN_TRADES_REACHED",
                    "label": "Máx. trades abiertos",
                    "count": 1,
                    "episodes": 1,
                    "mode": "episodes",
                    "symbols": defaultdict(int, {"DOT_USD": 1}),
                    "decision_types": defaultdict(int, {"SKIPPED": 50}),
                    "symbol_details": [
                        {
                            "symbol": "DOT_USD",
                            "cycles": 50,
                            "duration_seconds": 12 * 3600,
                            "duration_label": "~12h",
                        }
                    ],
                },
                {
                    "key": "INVALID_TRADE_AMOUNT",
                    "label": "Amount USD no configurado",
                    "count": 2,
                    "episodes": 2,
                    "mode": "events",
                    "symbols": defaultdict(int, {"ETH_USD": 2}),
                    "decision_types": defaultdict(int, {"SKIPPED": 2}),
                    "symbol_details": [],
                },
            ],
        }
    )
    assert "2 episodio" in text
    assert "Máx. trades abiertos — 1 ep." in text
    assert "DOT_USD ~12h" in text
    assert "Amount USD no configurado — 2×" in text


def test_rollup_excludes_cooldown_and_collapses_sticky_max_open():
    """Cooldown / throttle noise must not inflate; sticky max-open → 1 episode + duration."""
    svc = DailySummaryService()
    now = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
    rows = []
    # 20 cooldown re-logs — must be excluded
    for i in range(20):
        rows.append(
            _row(
                reason_code="COOLDOWN_ACTIVE",
                throttle_reason="THROTTLED_TIME_GATE (elapsed 10.0s < 60.0s)",
                symbol="BTC_USD",
                timestamp=now + timedelta(minutes=i),
            )
        )
    # 15 sticky max-open cycles for DOT — 1 episode
    for i in range(15):
        rows.append(
            _row(
                reason_code="MAX_OPEN_TRADES_REACHED",
                throttle_reason="max open trades reached",
                symbol="DOT_USD",
                timestamp=now + timedelta(minutes=i * 2),
            )
        )
    # 5 throttled duplicate alerts — excluded
    for i in range(5):
        rows.append(
            _row(
                reason_code="THROTTLED_DUPLICATE_ALERT",
                throttle_reason="THROTTLED_PRICE_GATE",
                symbol="ETH_USDT",
                timestamp=now + timedelta(minutes=i),
            )
        )
    # 1 real exchange failure — kept as event
    rows.append(
        _row(
            reason_code="EXCHANGE_REJECTED",
            throttle_reason="order rejected by exchange",
            symbol="SOL_USD",
            decision_type="FAILED",
            throttle_status="ORDER_FAILED",
            timestamp=now + timedelta(hours=1),
        )
    )

    mock_query = MagicMock()
    mock_query.filter.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.all.return_value = rows

    mock_db = MagicMock()
    mock_db.query.return_value = mock_query

    rollup = svc.get_non_executed_orders_summary(db=mock_db, hours=24)

    assert rollup["total_episodes"] == 2  # DOT max-open episode + SOL failure
    keys = {b["key"] for b in rollup["buckets"]}
    assert "COOLDOWN_ACTIVE" not in keys
    assert "THROTTLED_DUPLICATE_ALERT" not in keys
    assert "MAX_OPEN_TRADES_REACHED" in keys
    assert "EXCHANGE_REJECTED" in keys

    max_open = next(b for b in rollup["buckets"] if b["key"] == "MAX_OPEN_TRADES_REACHED")
    assert max_open["episodes"] == 1
    assert max_open["symbol_details"][0]["symbol"] == "DOT_USD"
    assert max_open["symbol_details"][0]["cycles"] == 15
    assert max_open["symbol_details"][0]["duration_label"] is not None

    text = svc.format_non_executed_orders_summary(rollup)
    assert "Cooldown" not in text
    assert "Throttled" not in text
    assert "Máx. trades abiertos" in text
    assert "DOT_USD" in text


def test_classify_telegram_api_error_not_guardrail():
    msg = (
        "Telegram API error: unknown - 400 Client Error: Bad Request for url: "
        "https://api.telegram.org/bot999401:AAHtoken/sendMessage"
    )
    assert classify_exchange_error(msg) == ReasonCode.TELEGRAM_API_ERROR.value
    # Must not false-positive on "401" digits inside a bot id / URL as AUTH.
    assert classify_exchange_error(msg) != ReasonCode.AUTHENTICATION_ERROR.value
    assert classify_exchange_error(msg) != ReasonCode.GUARDRAIL_BLOCKED.value


def test_redact_telegram_secrets_helper():
    from app.services.telegram_notifier import _redact_telegram_secrets, _truncate_telegram_text

    raw = "400 for url: https://api.telegram.org/bot123:AAHsecret/sendMessage more"
    cleaned = _redact_telegram_secrets(raw)
    assert "AAHsecret" not in cleaned
    assert "bot***" in cleaned or "bot***/" in cleaned
    assert len(_truncate_telegram_text("x" * 5000, 100)) <= 100
