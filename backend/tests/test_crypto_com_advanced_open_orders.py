"""Tests for Crypto.com advanced open orders integration."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.services.crypto_com_sync_errors import build_private_api_error, build_private_api_success
from app.services.open_orders_sync_status import reset_open_orders_sync_status_for_tests
from app.services.unified_open_orders_fetch import (
    ADVANCED_SOURCE_ENDPOINT,
    _is_valid_order_id,
    _order_dedup_key,
    classify_advanced_open_order,
    fetch_unified_open_orders,
    _merge_raw_orders,
)


@pytest.fixture(autouse=True)
def _reset_sync_status():
    reset_open_orders_sync_status_for_tests()
    yield
    reset_open_orders_sync_status_for_tests()


def _legacy_sell_82k():
    return {
        "order_id": "5755600489253467765",
        "instrument_name": "BTC_USD",
        "side": "SELL",
        "status": "ACTIVE",
        "order_type": "LIMIT",
        "quantity": "0.29925",
        "limit_price": "82000",
    }


def _advanced_margin_buy_59k():
    return {
        "order_id": "adv-buy-59000",
        "instrument_name": "BTC_USD",
        "side": "BUY",
        "status": "ACTIVE",
        "order_type": "LIMIT",
        "quantity": "0.30000",
        "limit_price": "59000",
        "exec_inst": ["MARGIN_ORDER"],
        "contingency_type": "SPOT_ATTACH",
        "source_endpoint": ADVANCED_SOURCE_ENDPOINT,
    }


def _advanced_tp(order_id: str, ref_price: str):
    return {
        "order_id": order_id,
        "instrument_name": "BTC_USD",
        "side": "SELL",
        "status": "ACTIVE",
        "order_type": "TAKE_PROFIT_LIMIT",
        "quantity": "0.29925",
        "ref_price": ref_price,
        "limit_price": ref_price,
        "source_endpoint": ADVANCED_SOURCE_ENDPOINT,
    }


def _advanced_tp_zero_exchange_id(ref_price: str):
    return {
        "exchange_order_id": "0",
        "instrument_name": "BTC_USD",
        "side": "SELL",
        "status": "ACTIVE",
        "order_type": "TAKE_PROFIT_LIMIT",
        "quantity": "0.29925",
        "ref_price": ref_price,
        "limit_price": ref_price,
        "source_endpoint": ADVANCED_SOURCE_ENDPOINT,
    }


def test_get_trigger_orders_http_400_preserves_error_code_50001():
    from app.services.brokers.crypto_com_trade import CryptoComTradeClient

    client = CryptoComTradeClient()
    client.api_key = "test_key_1234567890"
    client.api_secret = "test_secret_" + "x" * 40
    client.use_proxy = False
    client.base_url = "https://api.crypto.com/exchange/v1"
    client._trigger_orders_available = True
    client._last_trigger_health_check = 9999999999

    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.json.return_value = {"code": 50001, "message": "ERR_INTERNAL"}

    with patch("app.services.brokers.crypto_com_trade.http_post", return_value=mock_response):
        with patch("app.services.brokers.crypto_com_trade.get_execution_context", return_value="AWS"):
            with patch("app.services.brokers.crypto_com_trade.require_aws_or_skip", return_value=None):
                with patch.object(client, "sign_request", return_value={"id": 1, "method": "test", "params": {}, "api_key": "k", "sig": "s"}):
                    result = client.get_trigger_orders()

    assert result["sync_status"] == "api_error"
    assert result["error_code"] == 50001
    assert result["error_message"] == "ERR_INTERNAL"
    assert result.get("http_status") == 400
    assert result.get("endpoint") == "private/get-trigger-orders"


def test_unified_fetch_includes_advanced_margin_buy_and_tp_orders():
    from app.services.brokers.crypto_com_trade import CryptoComTradeClient

    real_client = CryptoComTradeClient.__new__(CryptoComTradeClient)
    mock_client = MagicMock()
    mock_client.get_open_orders.return_value = build_private_api_success([_legacy_sell_82k()])
    mock_client.get_trigger_orders.return_value = build_private_api_error(
        sync_status="api_error",
        error_message="ERR_INTERNAL",
        error_code=50001,
    )
    mock_client.get_advanced_open_orders.return_value = build_private_api_success(
        [
            _advanced_margin_buy_59k(),
            _advanced_tp("tp-71000", "71000"),
            _advanced_tp("tp-78000", "78000"),
        ]
    )
    mock_client._map_incoming_order.side_effect = lambda raw, is_trigger=False: real_client._map_incoming_order(
        raw, is_trigger
    )

    result = fetch_unified_open_orders(mock_client)

    assert result["sync_status"] == "ok"
    assert result["data_verified"] is True
    assert len(result["orders"]) == 4
    symbols_sides = {(o.symbol, o.side, o.order_type) for o in result["orders"]}
    assert ("BTC_USD", "BUY", "LIMIT") in symbols_sides
    assert ("BTC_USD", "SELL", "LIMIT") in symbols_sides
    tp_orders = [o for o in result["orders"] if o.is_trigger]
    assert len(tp_orders) == 2
    assert {float(o.trigger_price) for o in tp_orders} == {71000.0, 78000.0}


def test_unified_fetch_dedups_legacy_and_advanced_sell_82k():
    from app.services.brokers.crypto_com_trade import CryptoComTradeClient

    real_client = CryptoComTradeClient.__new__(CryptoComTradeClient)
    legacy = _legacy_sell_82k()
    advanced_duplicate = dict(legacy)
    advanced_duplicate["source_endpoint"] = ADVANCED_SOURCE_ENDPOINT

    mock_client = MagicMock()
    mock_client.get_open_orders.return_value = build_private_api_success([legacy])
    mock_client.get_trigger_orders.return_value = build_private_api_success([])
    mock_client.get_advanced_open_orders.return_value = build_private_api_success([advanced_duplicate])
    mock_client._map_incoming_order.side_effect = lambda raw, is_trigger=False: real_client._map_incoming_order(
        raw, is_trigger
    )

    result = fetch_unified_open_orders(mock_client)

    sell_limits = [o for o in result["orders"] if o.side == "SELL" and o.order_type == "LIMIT"]
    assert len(sell_limits) == 1
    assert float(sell_limits[0].price) == 82000.0


def test_classify_advanced_margin_buy_limit_not_filtered():
    include, is_trigger = classify_advanced_open_order(_advanced_margin_buy_59k())
    assert include is True
    assert is_trigger is False


def test_classify_advanced_take_profit_limit_is_trigger():
    include, is_trigger = classify_advanced_open_order(_advanced_tp("tp-71000", "71000"))
    assert include is True
    assert is_trigger is True


def test_unified_fetch_trigger_50001_advanced_success_non_fatal():
    from app.services.brokers.crypto_com_trade import CryptoComTradeClient

    real_client = CryptoComTradeClient.__new__(CryptoComTradeClient)
    mock_client = MagicMock()
    mock_client.get_open_orders.return_value = build_private_api_success([_legacy_sell_82k()])
    mock_client.get_trigger_orders.return_value = build_private_api_error(
        sync_status="api_error",
        error_message="ERR_INTERNAL",
        error_code=50001,
    )
    mock_client.get_advanced_open_orders.return_value = build_private_api_success(
        [_advanced_margin_buy_59k(), _advanced_tp("tp-71000", "71000"), _advanced_tp("tp-78000", "78000")]
    )
    mock_client._map_incoming_order.side_effect = lambda raw, is_trigger=False: real_client._map_incoming_order(
        raw, is_trigger
    )

    result = fetch_unified_open_orders(mock_client)

    assert result["sync_status"] == "ok"
    assert result["data_verified"] is True
    assert result["trigger_orders_status"] == "api_error"
    assert result["trigger_orders_error_code"] == 50001
    assert result["trigger_orders_error"] == "ERR_INTERNAL"


def test_ghost_order_protection_advanced_only_live_order_in_merged_id_set():
    from app.services.unified_open_orders_fetch import _merge_raw_orders

    advanced_only = _advanced_margin_buy_59k()
    merged = _merge_raw_orders([], [], [advanced_only])
    all_raw = [raw for raw, _ in merged]

    live_ids: set[str] = set()
    for order in all_raw:
        for id_field in ("order_id", "exchange_order_id", "client_oid"):
            oid = order.get(id_field)
            if oid:
                live_ids.add(str(oid))

    assert "adv-buy-59000" in live_ids
    assert len(merged) == 1


def test_dashboard_api_includes_source_endpoint_and_is_trigger():
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services.open_orders import UnifiedOpenOrder
    from app.services.open_orders_cache import clear_open_orders_cache, store_unified_open_orders
    from app.services.open_orders_sync_status import record_open_orders_sync_success

    clear_open_orders_cache()
    metadata = _advanced_tp("tp-71000", "71000")
    store_unified_open_orders(
        [
            UnifiedOpenOrder(
                order_id="tp-71000",
                symbol="BTC_USD",
                side="SELL",
                order_type="TAKE_PROFIT_LIMIT",
                status="ACTIVE",
                quantity=Decimal("0.29925"),
                price=Decimal("71000"),
                trigger_price=Decimal("71000"),
                is_trigger=True,
                metadata=metadata,
            )
        ]
    )
    record_open_orders_sync_success(order_count=1, trigger_orders_status="api_error", trigger_orders_error_code=50001)

    client = TestClient(app)

    orders_resp = client.get("/api/orders/open")
    assert orders_resp.status_code == 200
    order = orders_resp.json()["orders"][0]
    assert order["is_trigger"] is True
    assert order["source_endpoint"] == ADVANCED_SOURCE_ENDPOINT
    assert order["exchange_order_id"] == "tp-71000"

    dash_resp = client.get("/api/dashboard/open-orders-summary")
    assert dash_resp.status_code == 200
    dash_order = dash_resp.json()["orders"][0]
    assert dash_order["is_trigger"] is True
    assert dash_order["source_endpoint"] == ADVANCED_SOURCE_ENDPOINT


def test_invalid_order_ids_are_not_used_for_dedup():
    assert _is_valid_order_id(None) is False
    assert _is_valid_order_id("") is False
    assert _is_valid_order_id("0") is False
    assert _is_valid_order_id(0) is False
    assert _is_valid_order_id("None") is False
    assert _is_valid_order_id("null") is False
    assert _is_valid_order_id("5755600489253467765") is True

    raw = {
        "exchange_order_id": "0",
        "order_id": "tp-71000",
        "instrument_name": "BTC_USD",
    }
    assert _order_dedup_key(raw) == "tp-71000"


def test_valid_exchange_order_id_dedups_duplicates():
    shared_id = "5755600489253467765"
    first = dict(_legacy_sell_82k())
    second = dict(_legacy_sell_82k())
    second["exchange_order_id"] = shared_id

    merged = _merge_raw_orders([first], [], [second])
    assert len(merged) == 1


def test_advanced_triggers_with_exchange_order_id_zero_are_unique():
    from app.services.brokers.crypto_com_trade import CryptoComTradeClient

    real_client = CryptoComTradeClient.__new__(CryptoComTradeClient)
    triggers = [
        _advanced_tp_zero_exchange_id("65000"),
        _advanced_tp_zero_exchange_id("71000"),
        _advanced_tp_zero_exchange_id("78000"),
    ]

    mock_client = MagicMock()
    mock_client.get_open_orders.return_value = build_private_api_success([_legacy_sell_82k()])
    mock_client.get_trigger_orders.return_value = build_private_api_error(
        sync_status="api_error",
        error_message="ERR_INTERNAL",
        error_code=50001,
    )
    mock_client.get_advanced_open_orders.return_value = build_private_api_success(
        [_advanced_margin_buy_59k(), *triggers]
    )
    mock_client._map_incoming_order.side_effect = lambda raw, is_trigger=False: real_client._map_incoming_order(
        raw, is_trigger
    )

    result = fetch_unified_open_orders(mock_client)

    tp_orders = [o for o in result["orders"] if o.is_trigger]
    assert len(tp_orders) == 3
    assert {float(o.trigger_price) for o in tp_orders} == {65000.0, 71000.0, 78000.0}
    assert len(result["orders"]) == 5
