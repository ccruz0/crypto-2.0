"""Short TAKE_PROFIT must use <= trigger_condition (long uses >=)."""
from unittest.mock import MagicMock, patch

from app.services.brokers.crypto_com_trade import take_profit_trigger_operator
from app.services.sl_tp_price_adjust import compute_strategy_sl_tp_prices


def test_take_profit_trigger_operator_long_vs_short():
    assert take_profit_trigger_operator("SELL") == ">="
    assert take_profit_trigger_operator("BUY") == "<="
    assert take_profit_trigger_operator("sell") == ">="
    assert take_profit_trigger_operator("buy") == "<="


def test_short_tp_already_passed_places_below_market():
    """AAVE-like: short entry ~100, mark already below strategy TP → adjust under mark."""
    sl, tp, meta = compute_strategy_sl_tp_prices(
        entry_side="SELL",
        entry_price=100.01,
        sl_pct=3.0,
        tp_pct=3.0,
        current_price=94.10,
        buffer_pct=0.15,
    )
    assert meta["tp_adjusted"] is True
    assert tp < 94.10
    assert abs(tp - 94.10 * (1 - 0.0015)) < 0.01
    assert sl > 100.01  # short SL stays above entry when mark is below SL


_FAKE_INST_META = {
    "price_tick_size": "0.01",
    "price_decimals": 2,
    "qty_tick_size": "0.001",
    "quantity_decimals": 3,
    "min_quantity": "0.001",
    "min_notional": "1",
}


def _reject_until_trigger_op(required_op: str):
    """Fail create-order until a params payload uses the required trigger comparator."""

    def _side_effect(url, *args, **kwargs):
        payload = (kwargs or {}).get("json") or {}
        params = payload.get("params") or {}
        tc = params.get("trigger_condition") or ""
        r = MagicMock()
        if str(tc).startswith(required_op):
            r.ok = True
            r.status_code = 200
            r.json.return_value = {
                "code": 0,
                "result": {"order_id": f"tp-{required_op}-oid", "client_oid": "client"},
            }
            return r
        r.ok = False
        r.status_code = 400
        r.json.return_value = {"code": 50007, "message": "INVALID_TRIGGER_PRICE"}
        return r

    return _side_effect


@patch(
    "app.services.brokers.crypto_com_trade.CryptoComTradeClient._get_instrument_metadata",
    return_value=_FAKE_INST_META,
)
@patch.dict("os.environ", {"EXECUTION_CONTEXT": "AWS", "LIVE_TRADING": "true"}, clear=False)
def test_place_take_profit_buy_short_uses_lte_trigger(mock_inst_meta):
    from app.services.brokers.crypto_com_trade import CryptoComTradeClient

    client = CryptoComTradeClient()
    client.live_trading = True
    client.use_proxy = False
    client.base_url = "https://api.crypto.com/exchange/v1"

    with patch(
        "app.services.brokers.crypto_com_trade.http_post",
        side_effect=_reject_until_trigger_op("<="),
    ) as mock_http_post:
        with patch.object(
            client,
            "sign_request",
            side_effect=lambda method, params: {
                "id": 1,
                "method": method,
                "params": params,
                "api_key": "redacted",
                "sig": "redacted",
            },
        ):
            result = client.place_take_profit_order(
                symbol="AAVE_USD",
                side="BUY",  # closing side for short entry
                price=93.96,
                qty=0.065,
                trigger_price=93.96,
                dry_run=False,
                source="test",
            )

    assert result.get("order_id") == "tp-<=-oid"
    assert result.get("error") is None

    trigger_conditions = []
    for call in mock_http_post.call_args_list:
        params = ((call.kwargs or {}).get("json") or {}).get("params") or {}
        tc = params.get("trigger_condition")
        if tc:
            trigger_conditions.append(str(tc))

    assert any(tc.startswith("<=") for tc in trigger_conditions)
    assert not any(tc.startswith(">=") for tc in trigger_conditions)


@patch(
    "app.services.brokers.crypto_com_trade.CryptoComTradeClient._get_instrument_metadata",
    return_value=_FAKE_INST_META,
)
@patch.dict("os.environ", {"EXECUTION_CONTEXT": "AWS", "LIVE_TRADING": "true"}, clear=False)
def test_place_take_profit_sell_long_still_uses_gte_trigger(mock_inst_meta):
    from app.services.brokers.crypto_com_trade import CryptoComTradeClient

    client = CryptoComTradeClient()
    client.live_trading = True
    client.use_proxy = False
    client.base_url = "https://api.crypto.com/exchange/v1"

    with patch(
        "app.services.brokers.crypto_com_trade.http_post",
        side_effect=_reject_until_trigger_op(">="),
    ) as mock_http_post:
        with patch.object(
            client,
            "sign_request",
            side_effect=lambda method, params: {
                "id": 1,
                "method": method,
                "params": params,
                "api_key": "redacted",
                "sig": "redacted",
            },
        ):
            result = client.place_take_profit_order(
                symbol="BTC_USD",
                side="SELL",
                price=52000.0,
                qty=0.001,
                trigger_price=52000.0,
                dry_run=False,
                source="test",
            )

    assert result.get("order_id") == "tp->=-oid"
    assert result.get("error") is None

    trigger_conditions = []
    for call in mock_http_post.call_args_list:
        params = ((call.kwargs or {}).get("json") or {}).get("params") or {}
        tc = params.get("trigger_condition")
        if tc:
            trigger_conditions.append(str(tc))

    assert any(tc.startswith(">=") for tc in trigger_conditions)
    assert not any(tc.startswith("<=") for tc in trigger_conditions)
