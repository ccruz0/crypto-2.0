"""Tests for order-history symbol selection and priority sync."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.services.exchange_sync import (
    DEFAULT_ORDER_HISTORY_SYMBOLS,
    REQUIRED_ORDER_HISTORY_SYMBOLS,
    ExchangeSyncService,
)


def test_get_order_history_sync_symbols_includes_required_and_recent():
    service = ExchangeSyncService()
    db = MagicMock()

    watchlist_query = MagicMock()
    watchlist_query.filter.return_value.distinct.return_value.all.return_value = [
        ("DOT_USD",),
        ("SOL_USD",),
    ]

    recent_query = MagicMock()
    recent_query.filter.return_value.distinct.return_value.all.return_value = [
        ("BTC_USD",),
    ]

    open_query = MagicMock()
    open_query.filter.return_value.distinct.return_value.all.return_value = [
        ("ETH_USDT",),
    ]

    def query_side_effect(model):
        name = getattr(model, "__name__", str(model))
        if name == "WatchlistItem":
            return watchlist_query
        if model is ExchangeOrder:
            if not hasattr(query_side_effect, "exchange_calls"):
                query_side_effect.exchange_calls = 0
            query_side_effect.exchange_calls += 1
            if query_side_effect.exchange_calls == 1:
                return recent_query
            return open_query
        return MagicMock()

    db.query.side_effect = query_side_effect

    priority, all_symbols = service._get_order_history_sync_symbols(db)

    for required in REQUIRED_ORDER_HISTORY_SYMBOLS:
        assert required in all_symbols
    assert "BTC_USD" in priority
    assert "ETH_USDT" in priority
    assert priority.index("BTC_USD") < priority.index("DOT_USD") if "DOT_USD" in priority else True


def test_get_order_history_sync_symbols_uses_defaults_when_watchlist_empty():
    service = ExchangeSyncService()
    db = MagicMock()

    watchlist_query = MagicMock()
    watchlist_query.filter.return_value.distinct.return_value.all.return_value = []

    empty_orders_query = MagicMock()
    empty_orders_query.filter.return_value.distinct.return_value.all.return_value = []

    def query_side_effect(model):
        name = getattr(model, "__name__", str(model))
        if name == "WatchlistItem":
            return watchlist_query
        return empty_orders_query

    db.query.side_effect = query_side_effect

    priority, all_symbols = service._get_order_history_sync_symbols(db)

    assert all_symbols[:3] == list(REQUIRED_ORDER_HISTORY_SYMBOLS)
    for default in DEFAULT_ORDER_HISTORY_SYMBOLS:
        assert default in all_symbols
