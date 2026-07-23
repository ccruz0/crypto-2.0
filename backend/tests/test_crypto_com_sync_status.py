"""Tests for Crypto.com sync error handling and open orders sync status."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.crypto_com_sync_errors import (
    build_private_api_error,
    build_private_api_success,
    extract_sync_failure,
    is_sync_failure_response,
    parse_http_auth_error,
)
from app.services.open_orders_sync_status import (
    record_open_orders_sync_failure,
    record_open_orders_sync_success,
    reset_open_orders_sync_status_for_tests,
    sync_status_public_dict,
)


@pytest.fixture(autouse=True)
def _reset_sync_status():
    reset_open_orders_sync_status_for_tests()
    yield
    reset_open_orders_sync_status_for_tests()


def test_auth_diagnostic_masks_secrets():
    import importlib.util
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts" / "diagnose_crypto_com_auth.py"
    spec = importlib.util.spec_from_file_location("diagnose_crypto_com_auth", script)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    assert mod._mask("abcdefghij") == "abcd....ghij"
    assert mod._mask("") == "<NOT_SET>"
    assert mod._mask("abc") == "<SET>"


def test_40101_maps_to_failed_auth():
    payload = parse_http_auth_error({"code": 40101, "message": "Authentication failure"})
    assert payload["sync_status"] == "failed_auth"
    assert payload["data_verified"] is False
    assert payload["error_code"] == 40101
    assert "data" not in payload


def test_missing_credentials_maps_to_missing_credentials():
    payload = build_private_api_error(
        sync_status="missing_credentials",
        error_message="API credentials not configured",
    )
    assert payload["sync_status"] == "missing_credentials"
    assert is_sync_failure_response(payload) is True


def test_private_api_error_does_not_return_verified_empty_list():
    failure = build_private_api_error(sync_status="failed_auth", error_message="nope", error_code=40101)
    assert is_sync_failure_response(failure) is True
    assert failure.get("data_verified") is False
    success_empty = build_private_api_success([])
    assert success_empty["data_verified"] is True
    assert success_empty["data"] == []


def test_dashboard_payload_includes_data_verified_false_on_auth_failure():
    record_open_orders_sync_failure(
        sync_status="failed_auth",
        error_code=40101,
        error_message="Authentication failure",
    )
    meta = sync_status_public_dict()
    assert meta["data_verified"] is False
    assert meta["sync_status"] == "failed_auth"
    assert meta["error_code"] == 40101


def test_get_open_orders_returns_structured_auth_failure():
    from app.services.brokers.crypto_com_trade import CryptoComTradeClient

    client = CryptoComTradeClient()
    client.api_key = "test_key_1234567890"
    client.api_secret = "test_secret_" + "x" * 40
    client.use_proxy = False
    client.base_url = "https://api.crypto.com/exchange/v1"

    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.json.return_value = {"code": 40101, "message": "Authentication failure"}

    with patch("app.services.brokers.crypto_com_trade.http_post", return_value=mock_response):
        with patch("app.services.brokers.crypto_com_trade.get_execution_context", return_value="AWS"):
            with patch("app.services.brokers.crypto_com_trade.require_aws_or_skip", return_value=None):
                result = client.get_open_orders()

    assert result["sync_status"] == "failed_auth"
    assert result["data_verified"] is False
    assert "data" not in result or result.get("data") is None


def test_exchange_sync_preserves_cache_on_auth_failure():
    from app.services.exchange_sync import ExchangeSyncService
    from app.services.open_orders_cache import store_unified_open_orders, get_unified_open_orders, clear_open_orders_cache
    from app.services.open_orders import UnifiedOpenOrder

    from decimal import Decimal

    clear_open_orders_cache()
    existing = [
        UnifiedOpenOrder(
            order_id="123",
            symbol="BTC_USDT",
            side="BUY",
            order_type="LIMIT",
            status="ACTIVE",
            quantity=Decimal("1"),
            price=Decimal("100"),
            is_trigger=False,
        )
    ]
    store_unified_open_orders(existing)

    svc = ExchangeSyncService()
    db = MagicMock()
    fetch_payload = {
        "orders": [],
        "regular_raw": [],
        "trigger_raw": [],
        "sync_status": "failed_auth",
        "data_verified": False,
        "error_code": 40101,
        "error_message": "Authentication failure",
        "trigger_orders_status": None,
        "trigger_orders_error": None,
        "trigger_orders_error_code": None,
        "regular_count": 0,
        "trigger_count": 0,
    }
    with patch("app.services.unified_open_orders_fetch.fetch_unified_open_orders", return_value=fetch_payload):
        svc.sync_open_orders(db)

    orders, _ = get_unified_open_orders()
    assert len(orders) == 1
    meta = sync_status_public_dict()
    assert meta["sync_status"] == "failed_auth"
    assert meta["data_verified"] is False


def test_record_success_sets_data_verified_true():
    record_open_orders_sync_success(order_count=2)
    meta = sync_status_public_dict()
    assert meta["sync_status"] == "ok"
    assert meta["data_verified"] is True


def test_extract_sync_failure_from_legacy_error_shape():
    failure = extract_sync_failure({"error": "Authentication failed: 40101 - Authentication failure", "error_code": 40101})
    assert failure["sync_status"] == "failed_auth"


def _btc_usd_regular_order():
    return {
        "order_id": "5755600489253467765",
        "instrument_name": "BTC_USD",
        "side": "SELL",
        "status": "ACTIVE",
        "order_type": "LIMIT",
        "quantity": "0.001",
        "limit_price": "100000",
        "create_time": 1700000000000,
    }


def test_fetch_unified_open_orders_regular_ok_without_legacy_trigger_endpoint():
    from app.services.unified_open_orders_fetch import fetch_unified_open_orders
    from app.services.crypto_com_sync_errors import build_private_api_success
    from app.services.brokers.crypto_com_trade import CryptoComTradeClient

    real_client = CryptoComTradeClient.__new__(CryptoComTradeClient)
    mock_client = MagicMock()
    mock_client.get_open_orders.return_value = build_private_api_success([_btc_usd_regular_order()])
    mock_client.get_advanced_open_orders.return_value = build_private_api_success([])
    mock_client._map_incoming_order.side_effect = lambda raw, is_trigger=False: real_client._map_incoming_order(
        raw, is_trigger
    )

    result = fetch_unified_open_orders(mock_client)

    assert result["sync_status"] == "ok"
    assert result["data_verified"] is True
    assert len(result["orders"]) == 1
    assert result["orders"][0].symbol == "BTC_USD"
    assert result["orders"][0].side == "SELL"
    assert result["orders"][0].status == "ACTIVE"
    assert result["orders"][0].order_type == "LIMIT"
    assert result["trigger_orders_status"] == "ok"
    assert result["trigger_orders_error_code"] is None
    mock_client.get_trigger_orders.assert_not_called()


def test_exchange_sync_updates_cache_when_trigger_orders_fail():
    from app.services.exchange_sync import ExchangeSyncService
    from app.services.open_orders_cache import get_unified_open_orders, clear_open_orders_cache
    from app.services.unified_open_orders_fetch import fetch_unified_open_orders
    from app.services.crypto_com_sync_errors import build_private_api_error, build_private_api_success
    from app.services.brokers.crypto_com_trade import CryptoComTradeClient

    clear_open_orders_cache()
    real_client = CryptoComTradeClient.__new__(CryptoComTradeClient)
    fetch_payload = {
        "orders": [real_client._map_incoming_order(_btc_usd_regular_order(), False)],
        "regular_raw": [_btc_usd_regular_order()],
        "trigger_raw": [],
        "sync_status": "ok",
        "data_verified": True,
        "error_code": None,
        "error_message": None,
        "trigger_orders_status": "api_error",
        "trigger_orders_error": "Invalid request",
        "trigger_orders_error_code": 50001,
        "regular_count": 1,
        "trigger_count": 0,
    }

    svc = ExchangeSyncService()
    db = MagicMock()
    with patch("app.services.unified_open_orders_fetch.fetch_unified_open_orders", return_value=fetch_payload):
        svc.sync_open_orders(db)

    orders, _ = get_unified_open_orders()
    assert len(orders) == 1
    assert orders[0].symbol == "BTC_USD"
    meta = sync_status_public_dict()
    assert meta["sync_status"] == "ok"
    assert meta["data_verified"] is True
    assert meta["trigger_orders_status"] == "api_error"


def test_fetch_unified_open_orders_40101_maps_to_failed_auth():
    from app.services.unified_open_orders_fetch import fetch_unified_open_orders
    from app.services.crypto_com_sync_errors import build_private_api_error

    mock_client = MagicMock()
    mock_client.get_open_orders.return_value = build_private_api_error(
        sync_status="failed_auth",
        error_message="Authentication failure",
        error_code=40101,
    )

    result = fetch_unified_open_orders(mock_client)

    assert result["sync_status"] == "failed_auth"
    assert result["data_verified"] is False
    assert result["orders"] == []


def test_fetch_unified_open_orders_missing_credentials():
    from app.services.unified_open_orders_fetch import fetch_unified_open_orders
    from app.services.crypto_com_sync_errors import build_private_api_error

    mock_client = MagicMock()
    mock_client.get_open_orders.return_value = build_private_api_error(
        sync_status="missing_credentials",
        error_message="API credentials not configured",
    )

    result = fetch_unified_open_orders(mock_client)

    assert result["sync_status"] == "missing_credentials"
    assert result["data_verified"] is False


def test_orders_open_api_returns_btc_usd_from_cache():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services.open_orders import UnifiedOpenOrder
    from app.services.open_orders_cache import store_unified_open_orders, clear_open_orders_cache
    from app.services.open_orders_sync_status import record_open_orders_sync_success
    from decimal import Decimal

    clear_open_orders_cache()
    store_unified_open_orders(
        [
            UnifiedOpenOrder(
                order_id="5755600489253467765",
                symbol="BTC_USD",
                side="SELL",
                order_type="LIMIT",
                status="ACTIVE",
                quantity=Decimal("0.001"),
                price=Decimal("100000"),
                is_trigger=False,
                created_at="2024-01-01T00:00:00+00:00",
            )
        ]
    )
    record_open_orders_sync_success(
        order_count=1,
        trigger_orders_status="api_error",
        trigger_orders_error="Invalid request",
        trigger_orders_error_code=50001,
    )

    client = TestClient(app)
    response = client.get("/api/orders/open")
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["sync_status"] == "ok"
    assert payload["data_verified"] is True
    assert payload["trigger_orders_status"] == "api_error"
    order = payload["orders"][0]
    assert order["order_id"] == "5755600489253467765"
    assert order["instrument_name"] == "BTC_USD"
    assert order["side"] == "SELL"
    assert order["status"] == "ACTIVE"


def test_dashboard_open_orders_summary_matches_cache_count():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services.open_orders import UnifiedOpenOrder
    from app.services.open_orders_cache import store_unified_open_orders, clear_open_orders_cache
    from app.services.open_orders_sync_status import record_open_orders_sync_success
    from decimal import Decimal

    clear_open_orders_cache()
    store_unified_open_orders(
        [
            UnifiedOpenOrder(
                order_id="5755600489253467765",
                symbol="BTC_USD",
                side="SELL",
                order_type="LIMIT",
                status="ACTIVE",
                quantity=Decimal("0.001"),
                price=Decimal("100000"),
                is_trigger=False,
            )
        ]
    )
    record_open_orders_sync_success(order_count=1, trigger_orders_status="api_error")

    client = TestClient(app)
    response = client.get("/api/dashboard/open-orders-summary")
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["sync_status"] == "ok"
    assert payload["data_verified"] is True
    assert payload["orders"][0]["symbol"] == "BTC_USD"
