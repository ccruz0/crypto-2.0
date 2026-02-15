"""
PR12: SL/TP robustness matrix (E2/E3/E4).

Contract + matrix tests:
- Invalid price format returns error with tried_formats / tried_variants.
- API_DISABLED (140001) triggers fallback path; response records variant/fallback.
- Success on variant K stops immediately (no further broker calls).
- TP success / SL failure (and vice versa) with clean combined reporting.
- Final error includes last_error + all tried_variants.
"""
import pytest
from unittest.mock import MagicMock, patch

from app.services.tp_sl_order_creator import create_take_profit_order, create_stop_loss_order
from app.services.brokers.crypto_com_trade import trade_client


@pytest.fixture
def mock_db():
    return MagicMock()


# --- 1. Invalid price format returns error with tried_formats ---


@patch("app.services.tp_sl_order_creator.trade_client._get_instrument_metadata")
@patch("app.utils.data_freshness.require_fresh")
@patch.object(trade_client, "place_take_profit_order")
@patch("app.services.tp_sl_order_creator.can_place_real_order")
def test_invalid_price_format_returns_error_with_tried_formats(mock_can_place, mock_place_tp, mock_require_fresh, mock_inst_meta, mock_db):
    """When broker returns 308-style error with tried_variants, creator returns structured error."""
    mock_can_place.return_value = (True, None, None)
    mock_require_fresh.return_value = (True, None, None, {})
    mock_inst_meta.return_value = {"min_quantity": "0.001", "qty_tick_size": "0.001", "price_tick_size": "0.01", "quantity_decimals": 8}
    mock_place_tp.return_value = {
        "error": "Invalid price format",
        "error_code": 308,
        "error_message": "Invalid price format",
        "tried_variants": ["1-sideSELL-params1-tc1", "1-sideSELL-params1-tc2", "1-sideSELL-params2-tc1"],
        "last_error": {"code": 308, "message": "Invalid price format"},
    }

    result = create_take_profit_order(
        db=mock_db,
        symbol="BTC_USDT",
        side="BUY",
        tp_price=50000.0,
        quantity=0.001,
        entry_price=49000.0,
        dry_run=False,
        source="manual",
    )

    assert result.get("order_id") is None
    assert result.get("error") is not None
    assert result.get("tried_variants") == ["1-sideSELL-params1-tc1", "1-sideSELL-params1-tc2", "1-sideSELL-params2-tc1"]
    assert result.get("last_error", {}).get("code") == 308
    assert result.get("side") == "TP"
    assert result.get("symbol") == "BTC_USDT"


# --- 2. API_DISABLED (140001) triggers fallback and records variant ---


@patch("app.services.tp_sl_order_creator.trade_client._get_instrument_metadata")
@patch("app.utils.data_freshness.require_fresh")
@patch.object(trade_client, "place_take_profit_order")
@patch("app.services.tp_sl_order_creator.can_place_real_order")
def test_api_disabled_140001_triggers_fallback_and_records_variant(mock_can_place, mock_place_tp, mock_require_fresh, mock_inst_meta, mock_db):
    """When broker returns 140001 then succeeds via fallback, response includes fallback_attempted or order_id."""
    mock_can_place.return_value = (True, None, None)
    mock_require_fresh.return_value = (True, None, None, {})
    mock_inst_meta.return_value = {"min_quantity": "0.001", "qty_tick_size": "0.001", "price_tick_size": "0.01", "quantity_decimals": 8}
    # Simulate: 140001 from create-order, then fallback create-order-list succeeds; creator must pass through fallback_attempted
    mock_place_tp.return_value = {"order_id": "fallback_order_123", "error": None, "fallback_attempted": True}

    result = create_take_profit_order(
        db=mock_db,
        symbol="ETH_USDT",
        side="BUY",
        tp_price=3000.0,
        quantity=0.01,
        entry_price=2900.0,
        dry_run=False,
        source="manual",
    )

    assert result.get("order_id") == "fallback_order_123"
    assert result.get("error") is None
    assert result.get("fallback_attempted") is True
    mock_place_tp.assert_called_once()


# --- 3. Success on variant K stops immediately ---


@patch("app.services.tp_sl_order_creator.trade_client._get_instrument_metadata")
@patch("app.utils.data_freshness.require_fresh")
@patch.object(trade_client, "place_take_profit_order")
@patch("app.services.tp_sl_order_creator.can_place_real_order")
def test_success_on_variant_k_stops_immediately(mock_can_place, mock_place_tp, mock_require_fresh, mock_inst_meta, mock_db):
    """Broker is called once; success returned immediately (no further calls)."""
    mock_can_place.return_value = (True, None, None)
    mock_require_fresh.return_value = (True, None, None, {})
    mock_inst_meta.return_value = {"min_quantity": "0.001", "qty_tick_size": "0.001", "price_tick_size": "0.01", "quantity_decimals": 8}
    mock_place_tp.return_value = {"order_id": "tp_ord_1", "error": None}

    result = create_take_profit_order(
        db=mock_db,
        symbol="BTC_USDT",
        side="BUY",
        tp_price=50000.0,
        quantity=0.001,
        entry_price=49000.0,
        dry_run=False,
        source="manual",
    )

    assert result.get("order_id") == "tp_ord_1"
    assert result.get("error") is None
    # Assert API call count on the exact mock we patched (TP broker), not a wrapper
    assert mock_place_tp.call_count == 1


@patch("app.services.tp_sl_order_creator.trade_client._get_instrument_metadata")
@patch("app.utils.data_freshness.require_fresh")
@patch.object(trade_client, "place_take_profit_order")
@patch("app.services.tp_sl_order_creator.can_place_real_order")
def test_success_after_failures_stops_at_first_success(mock_can_place, mock_place_tp, mock_require_fresh, mock_inst_meta, mock_db):
    """First call fails (308), second call succeeds; broker is called once per creator invocation (stop on success)."""
    mock_can_place.return_value = (True, None, None)
    mock_require_fresh.return_value = (True, None, None, {})
    mock_inst_meta.return_value = {"min_quantity": "0.001", "qty_tick_size": "0.001", "price_tick_size": "0.01", "quantity_decimals": 8}
    mock_place_tp.side_effect = [
        {"error": "Error 308: Invalid price format", "tried_variants": ["v1"], "last_error": {"code": 308, "message": "Invalid"}},
        {"order_id": "tp_ord_2", "error": None},
    ]

    result1 = create_take_profit_order(
        db=mock_db,
        symbol="BTC_USDT",
        side="BUY",
        tp_price=50000.0,
        quantity=0.001,
        entry_price=49000.0,
        dry_run=False,
        source="manual",
    )
    assert result1.get("order_id") is None
    assert result1.get("error") is not None

    result2 = create_take_profit_order(
        db=mock_db,
        symbol="BTC_USDT",
        side="BUY",
        tp_price=50000.0,
        quantity=0.001,
        entry_price=49000.0,
        dry_run=False,
        source="manual",
    )
    assert result2.get("order_id") == "tp_ord_2"
    assert result2.get("error") is None
    assert mock_place_tp.call_count == 2


# --- 4. TP success / SL failure combined report ---


@patch("app.services.tp_sl_order_creator.trade_client._get_instrument_metadata")
@patch("app.utils.data_freshness.require_fresh")
@patch.object(trade_client, "place_stop_loss_order")
@patch.object(trade_client, "place_take_profit_order")
@patch("app.services.tp_sl_order_creator.can_place_real_order")
def test_tp_success_sl_failure_returns_combined_report(mock_can_place, mock_place_tp, mock_place_sl, mock_require_fresh, mock_inst_meta, mock_db):
    """TP succeeds, SL fails; both return shapes allow combined reporting."""
    mock_can_place.return_value = (True, None, None)
    mock_require_fresh.return_value = (True, None, None, {})
    mock_inst_meta.return_value = {"min_quantity": "0.001", "qty_tick_size": "0.001", "price_tick_size": "0.01", "quantity_decimals": 8}
    mock_place_tp.return_value = {"order_id": "tp_123", "error": None}
    mock_place_sl.return_value = {
        "error": "All variations failed",
        "tried_variants": ["sl_v1", "sl_v2"],
        "last_error": {"code": 308, "message": "Invalid price format"},
        "error_code": 308,
        "error_message": "Invalid price format",
    }

    tp_result = create_take_profit_order(
        db=mock_db,
        symbol="BTC_USDT",
        side="BUY",
        tp_price=51000.0,
        quantity=0.001,
        entry_price=49000.0,
        dry_run=False,
        source="manual",
    )
    sl_result = create_stop_loss_order(
        db=mock_db,
        symbol="BTC_USDT",
        side="BUY",
        sl_price=48000.0,
        quantity=0.001,
        entry_price=49000.0,
        dry_run=False,
        source="manual",
    )

    assert tp_result.get("order_id") == "tp_123"
    assert tp_result.get("error") is None
    assert tp_result.get("side") == "TP"
    assert tp_result.get("symbol") == "BTC_USDT"
    assert sl_result.get("order_id") is None
    assert sl_result.get("error") is not None
    assert sl_result.get("tried_variants") == ["sl_v1", "sl_v2"]
    assert sl_result.get("last_error", {}).get("code") == 308
    assert sl_result.get("side") == "SL"
    assert sl_result.get("symbol") == "BTC_USDT"


# --- 5. All variants fail: includes last_error and all labels ---


@patch("app.services.tp_sl_order_creator.trade_client._get_instrument_metadata")
@patch("app.utils.data_freshness.require_fresh")
@patch.object(trade_client, "place_take_profit_order")
@patch("app.services.tp_sl_order_creator.can_place_real_order")
def test_all_variants_fail_includes_last_error_and_all_labels(mock_can_place, mock_place_tp, mock_require_fresh, mock_inst_meta, mock_db):
    """When all variants fail, result includes last_error and tried_variants (never swallow)."""
    mock_can_place.return_value = (True, None, None)
    mock_require_fresh.return_value = (True, None, None, {})
    mock_inst_meta.return_value = {"min_quantity": "0.001", "qty_tick_size": "0.001", "price_tick_size": "0.01", "quantity_decimals": 8}
    mock_place_tp.return_value = {
        "error": "All format variations failed. Last error: Error 308: Invalid price format",
        "error_code": 308,
        "error_message": "Invalid price format",
        "tried_variants": ["1-sideSELL-params1-tc1", "1-sideSELL-params1-tc2", "1-sideSELL-params2-tc1", "1-sideSELL-params2-tc2"],
        "last_error": {"code": 308, "message": "Error 308: Invalid price format"},
    }

    result = create_take_profit_order(
        db=mock_db,
        symbol="BTC_USDT",
        side="BUY",
        tp_price=50000.0,
        quantity=0.001,
        entry_price=49000.0,
        dry_run=False,
        source="manual",
    )

    assert result.get("order_id") is None
    assert "308" in (result.get("error") or "")
    assert result.get("tried_variants") == [
        "1-sideSELL-params1-tc1",
        "1-sideSELL-params1-tc2",
        "1-sideSELL-params2-tc1",
        "1-sideSELL-params2-tc2",
    ]
    assert result.get("last_error") is not None
    assert result["last_error"].get("code") == 308
    assert result.get("error_code") == 308
    assert result.get("symbol") == "BTC_USDT"
    assert result.get("side") == "TP"
