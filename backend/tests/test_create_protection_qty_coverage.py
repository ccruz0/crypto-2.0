"""create-protection-smart must gap-fill when parent has dust SL/TP vs uncovered qty."""

from unittest.mock import MagicMock, patch

from app.api.routes_orders import _existing_protection_covers_request


def test_existing_protection_covers_request_dust_vs_uncovered():
    assert _existing_protection_covers_request(0.0006, 0.0515) is False
    assert _existing_protection_covers_request(0.0515, 0.0515) is True
    assert _existing_protection_covers_request(0.052, 0.0515) is True
    assert _existing_protection_covers_request(0.0, 0.0515) is False
    assert _existing_protection_covers_request(0.05, 0.0) is True


@patch("app.services.tp_sl_order_creator.trade_client")
@patch("app.services.tp_sl_order_creator.can_place_real_order", return_value=(True, None))
@patch("app.services.tp_sl_order_creator.resolve_sltp_margin_context", return_value=(True, 5.0))
@patch("app.utils.sl_trigger_guard.fetch_last_price", return_value=1870.0)
@patch(
    "app.utils.sl_trigger_guard.ensure_valid_tp_trigger",
    side_effect=lambda **kw: (kw["tp_price"], None),
)
def test_create_take_profit_gap_fills_when_existing_smaller(
    _ensure_tp,
    _last,
    _margin,
    _can_place,
    mock_trade_client,
):
    from app.services.tp_sl_order_creator import create_take_profit_order

    existing = MagicMock()
    existing.exchange_order_id = "tp-dust"
    existing.quantity = 0.0006

    mock_trade_client._get_instrument_metadata.return_value = {
        "min_quantity": "0.0001",
        "qty_tick_size": "0.0001",
        "min_notional": "1",
        "quantity_decimals": 4,
    }
    mock_trade_client.normalize_quantity.return_value = "0.0515"
    mock_trade_client.place_take_profit_order.return_value = {
        "order_id": "tp-gap",
    }

    db = MagicMock()
    with patch(
        "app.services.sl_tp_protection.get_active_protection_order",
        return_value=existing,
    ):
        result = create_take_profit_order(
            db=db,
            symbol="ETH_USD",
            side="SELL",
            tp_price=1843.0,
            quantity=0.0515,
            entry_price=1862.0,
            parent_order_id="entry-1",
            dry_run=False,
            source="manual",
        )

    assert result["order_id"] == "tp-gap"
    mock_trade_client.place_take_profit_order.assert_called_once()


@patch("app.services.tp_sl_order_creator.trade_client")
def test_create_take_profit_reuses_when_existing_covers(mock_trade_client):
    from app.services.tp_sl_order_creator import create_take_profit_order

    existing = MagicMock()
    existing.exchange_order_id = "tp-full"
    existing.quantity = 0.106

    db = MagicMock()
    with patch(
        "app.services.sl_tp_protection.get_active_protection_order",
        return_value=existing,
    ):
        result = create_take_profit_order(
            db=db,
            symbol="AAVE_USD",
            side="BUY",
            tp_price=94.0,
            quantity=0.106,
            entry_price=93.5,
            parent_order_id="entry-aave",
            dry_run=False,
            source="manual",
        )

    assert result["order_id"] == "tp-full"
    mock_trade_client.place_take_profit_order.assert_not_called()
