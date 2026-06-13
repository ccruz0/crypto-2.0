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
    from app.services.open_orders_cache import store_unified_open_orders, get_unified_open_orders
    from app.services.open_orders import UnifiedOpenOrder

    from decimal import Decimal

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
    auth_error = build_private_api_error(
        sync_status="failed_auth",
        error_message="Authentication failure",
        error_code=40101,
    )
    with patch("app.services.exchange_sync.trade_client") as mock_client:
        mock_client.get_open_orders.return_value = auth_error
        mock_client.get_trigger_orders.return_value = auth_error
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
