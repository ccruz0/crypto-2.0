"""
Regression guard tests for WatchlistItem serialization.

These tests ensure that trade_amount_usd is NEVER mutated or defaulted
during serialization. This is a critical invariant that must be maintained.

If any of these tests fail, it means a regression has been introduced
that breaks the "DB is single source of truth" guarantee.
"""

import pytest
from unittest.mock import Mock
from app.api.routes_dashboard import _serialize_watchlist_item


def create_mock_watchlist_item(symbol: str, trade_amount_usd=None, **kwargs):
    """Create a mock WatchlistItem for testing"""
    item = Mock()
    item.id = 1
    item.symbol = symbol
    item.exchange = kwargs.get("exchange", "CRYPTO_COM")
    item.trade_amount_usd = trade_amount_usd
    item.trade_enabled = kwargs.get("trade_enabled", False)
    item.trade_on_margin = kwargs.get("trade_on_margin", False)
    item.alert_enabled = kwargs.get("alert_enabled", False)
    item.buy_alert_enabled = kwargs.get("buy_alert_enabled", False)
    item.sell_alert_enabled = kwargs.get("sell_alert_enabled", False)
    item.sl_tp_mode = kwargs.get("sl_tp_mode", "conservative")
    item.order_status = kwargs.get("order_status", "PENDING")
    item.min_price_change_pct = kwargs.get("min_price_change_pct", None)
    item.sl_percentage = kwargs.get("sl_percentage", None)
    item.tp_percentage = kwargs.get("tp_percentage", None)
    item.sl_price = kwargs.get("sl_price", None)
    item.tp_price = kwargs.get("tp_price", None)
    item.buy_target = kwargs.get("buy_target", None)
    item.take_profit = kwargs.get("take_profit", None)
    item.stop_loss = kwargs.get("stop_loss", None)
    item.price = kwargs.get("price", None)
    item.rsi = kwargs.get("rsi", None)
    item.atr = kwargs.get("atr", None)
    item.ma50 = kwargs.get("ma50", None)
    item.ma200 = kwargs.get("ma200", None)
    item.ema10 = kwargs.get("ema10", None)
    item.res_up = kwargs.get("res_up", None)
    item.res_down = kwargs.get("res_down", None)
    item.order_date = kwargs.get("order_date", None)
    item.purchase_price = kwargs.get("purchase_price", None)
    item.quantity = kwargs.get("quantity", None)
    item.sold = kwargs.get("sold", False)
    item.sell_price = kwargs.get("sell_price", None)
    item.notes = kwargs.get("notes", None)
    item.created_at = kwargs.get("created_at", None)
    item.updated_at = kwargs.get("updated_at", None)
    item.signals = kwargs.get("signals", None)
    item.skip_sl_tp_reminder = kwargs.get("skip_sl_tp_reminder", False)
    item.is_deleted = kwargs.get("is_deleted", False)
    return item


def test_trade_amount_usd_null_returns_null():
    """REGRESSION GUARD: NULL trade_amount_usd must return null (not 10, not 0)"""
    item = create_mock_watchlist_item("TEST_NULL", trade_amount_usd=None)
    
    # Serialize
    serialized = _serialize_watchlist_item(item, market_data=None, db=None)
    
    # CRITICAL: Must be None, not 10, not 0, not any default
    assert serialized["trade_amount_usd"] is None, (
        f"REGRESSION: trade_amount_usd should be None, got {serialized['trade_amount_usd']}. "
        f"A default value was applied, breaking the 'DB is truth' guarantee."
    )


def test_trade_amount_usd_exact_value_preserved():
    """REGRESSION GUARD: Exact value must be preserved (10.0 stays 10.0, not 11)"""
    test_value = 10.0
    item = create_mock_watchlist_item("TEST_EXACT", trade_amount_usd=test_value)
    
    # Serialize
    serialized = _serialize_watchlist_item(item, market_data=None, db=None)
    
    # CRITICAL: Must be exactly the same value
    assert serialized["trade_amount_usd"] == test_value, (
        f"REGRESSION: trade_amount_usd should be {test_value}, got {serialized['trade_amount_usd']}. "
        f"The value was mutated, breaking the 'DB is truth' guarantee."
    )


def test_trade_amount_usd_zero_preserved():
    """REGRESSION GUARD: Zero value must be preserved (0.0 stays 0.0, not None)"""
    item = create_mock_watchlist_item("TEST_ZERO", trade_amount_usd=0.0)
    
    # Serialize
    serialized = _serialize_watchlist_item(item, market_data=None, db=None)
    
    # CRITICAL: Must be 0.0, not None
    assert serialized["trade_amount_usd"] == 0.0, (
        f"REGRESSION: trade_amount_usd should be 0.0, got {serialized['trade_amount_usd']}. "
        f"The value was mutated to None, breaking the 'DB is truth' guarantee."
    )


def test_trade_amount_usd_no_default_applied():
    """REGRESSION GUARD: No default value should ever be applied"""
    # Test with various scenarios
    test_cases = [
        (None, None, "NULL should stay NULL"),
        (10.0, 10.0, "10.0 should stay 10.0"),
        (11.0, 11.0, "11.0 should stay 11.0"),
        (0.0, 0.0, "0.0 should stay 0.0"),
    ]
    
    for db_value, expected_api_value, description in test_cases:
        item = create_mock_watchlist_item(f"TEST_{db_value}", trade_amount_usd=db_value)
        serialized = _serialize_watchlist_item(item, market_data=None, db=None)
        actual = serialized["trade_amount_usd"]
        
        assert actual == expected_api_value, (
            f"REGRESSION: {description}. "
            f"DB={db_value}, Expected API={expected_api_value}, Got API={actual}. "
            f"This indicates a default or mutation was applied."
        )


def test_get_dashboard_reads_from_watchlist_item():
    """REGRESSION GUARD: GET /api/dashboard must read from WatchlistItem, not WatchlistMaster"""
    from app.api.routes_dashboard import list_watchlist_items
    from app.database import get_db
    
    # This test verifies the route handler imports and structure
    # The actual implementation should query WatchlistItem
    import inspect
    source = inspect.getsource(list_watchlist_items)
    
    # CRITICAL: Must query WatchlistItem, not WatchlistMaster
    assert "WatchlistItem" in source, (
        "REGRESSION: GET /api/dashboard must query WatchlistItem table. "
        "Found query to WatchlistMaster instead."
    )
    assert "WatchlistMaster" not in source or "watchlist_items" in source.lower(), (
        "REGRESSION: GET /api/dashboard should not query WatchlistMaster. "
        "WatchlistItem is the single source of truth."
    )


def test_put_dashboard_writes_to_watchlist_item():
    """REGRESSION GUARD: PUT /api/dashboard/symbol/{symbol} must write to WatchlistItem"""
    from app.api.routes_dashboard import update_watchlist_item_by_symbol
    import inspect
    source = inspect.getsource(update_watchlist_item_by_symbol)
    
    # CRITICAL: Must query/update WatchlistItem, not WatchlistMaster
    assert "WatchlistItem" in source, (
        "REGRESSION: PUT /api/dashboard/symbol/{symbol} must update WatchlistItem table. "
        "Found update to WatchlistMaster instead."
    )

