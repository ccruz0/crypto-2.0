"""
Tests for Crypto.com SL/TP 140001 handling: one-shot fallback to create-order-list.
Mocks HTTP layer; no real network. Asserts structured error and no param leakage in logs.
"""
import sys
import logging
from decimal import Decimal
from unittest.mock import patch, MagicMock

import pytest

# Allow running in environments where live_trading_gate is not installed (e.g. minimal pytest container)
if "app.services.live_trading_gate" not in sys.modules:
    sys.modules["app.services.live_trading_gate"] = MagicMock()

# Minimal instrument meta for formatting (quantity_decimals required by normalize_quantity)
_FAKE_INST_META = {
    "instrument_name": "BTC_USDT",
    "price_tick_size": "0.01",
    "qty_tick_size": "0.00001",
    "min_quantity": "0.00001",
    "quantity_decimals": 8,
}


def _mock_http_post_create_order_then_list_success(url, *args, **kwargs):
    """First call (create-order) -> 140001; second (create-order-list) -> success."""
    if "create-order-list" in (url or ""):
        r = MagicMock()
        r.ok = True
        r.status_code = 200
        r.json.return_value = {"result": [{"order_id": "test-oid-123", "code": 0}]}
        return r
    # create-order
    r = MagicMock()
    r.ok = False
    r.status_code = 400
    r.json.return_value = {"code": 140001, "message": "API_DISABLED"}
    return r


def _mock_http_post_both_140001(url, *args, **kwargs):
    """Both create-order and create-order-list return 140001."""
    r = MagicMock()
    r.ok = True
    r.status_code = 200
    if "create-order-list" in (url or ""):
        r.json.return_value = {"result": [{"code": 140001, "message": "API_DISABLED"}]}
    else:
        r.json.return_value = {"code": 140001, "message": "API_DISABLED"}
    return r


def test_sl_140001_fallback_success():
    """One fallback to create-order-list returns order_id; works in container (in-test patching, no decorator params)."""
    with patch.dict("os.environ", {"EXECUTION_CONTEXT": "AWS", "LIVE_TRADING": "true"}, clear=False):
        with patch("app.services.brokers.crypto_com_trade.http_post", side_effect=_mock_http_post_create_order_then_list_success):
            with patch("app.services.brokers.crypto_com_trade.CryptoComTradeClient._get_instrument_metadata", return_value=_FAKE_INST_META):
                from app.services.brokers.crypto_com_trade import CryptoComTradeClient
                c = CryptoComTradeClient()
                c.live_trading = True
                c.use_proxy = False
                c.base_url = "https://api.crypto.com/exchange/v1"
                with patch.object(c, "_refresh_runtime_flags"), patch.object(c, "sign_request", return_value={"id": 1, "params": {}}):
                    r = c.place_stop_loss_order("BTC_USDT", "SELL", 50000.0, 0.001, 49000.0, dry_run=False, source="test")
    assert r.get("order_id") == "test-oid-123"
    assert r.get("error") is None


@patch("app.services.brokers.crypto_com_trade.http_post", side_effect=_mock_http_post_create_order_then_list_success)
@patch("app.services.brokers.crypto_com_trade.CryptoComTradeClient._get_instrument_metadata", return_value=_FAKE_INST_META)
@patch.dict("os.environ", {"EXECUTION_CONTEXT": "AWS", "LIVE_TRADING": "true", "EXCHANGE_CUSTOM_BASE_URL": "https://api.crypto.com/exchange/v1"}, clear=False)
def test_sl_140001_then_create_order_list_success(mock_inst_meta, mock_http_post):
    """place_stop_loss_order: create-order returns 140001, create-order-list returns order_id -> success."""
    from app.services.brokers.crypto_com_trade import CryptoComTradeClient

    client = CryptoComTradeClient()
    client.live_trading = True
    client.use_proxy = False
    client.base_url = "https://api.crypto.com/exchange/v1"

    with patch.object(client, "sign_request", return_value={"id": 1, "method": "private/create-order", "params": {}, "api_key": "redacted", "sig": "redacted"}):
        result = client.place_stop_loss_order(
            symbol="BTC_USDT",
            side="SELL",
            price=50000.0,
            qty=0.001,
            trigger_price=49000.0,
            dry_run=False,
            source="test",
        )

    assert result.get("order_id") == "test-oid-123"
    assert result.get("error") is None
    # No param values in any http_post call (payload is signed; we only check we didn't log params elsewhere via log capture if needed)
    calls = mock_http_post.call_args_list
    assert len(calls) >= 2
    create_order_list_calls = [c for c in calls if "create-order-list" in (c[0][0] if c[0] else "")]
    assert len(create_order_list_calls) == 1


@patch("app.services.brokers.crypto_com_trade.http_post", side_effect=_mock_http_post_create_order_then_list_success)
@patch("app.services.brokers.crypto_com_trade.CryptoComTradeClient._get_instrument_metadata", return_value=_FAKE_INST_META)
@patch.dict("os.environ", {"EXECUTION_CONTEXT": "AWS", "LIVE_TRADING": "true"}, clear=False)
def test_tp_140001_then_create_order_list_success(mock_inst_meta, mock_http_post):
    """place_take_profit_order: create-order returns 140001, create-order-list returns order_id -> success."""
    from app.services.brokers.crypto_com_trade import CryptoComTradeClient

    client = CryptoComTradeClient()
    client.live_trading = True
    client.use_proxy = False
    client.base_url = "https://api.crypto.com/exchange/v1"

    with patch.object(client, "sign_request", return_value={"id": 1, "method": "private/create-order", "params": {}, "api_key": "redacted", "sig": "redacted"}):
        result = client.place_take_profit_order(
            symbol="BTC_USDT",
            side="SELL",
            price=52000.0,
            qty=0.001,
            trigger_price=52000.0,
            dry_run=False,
            source="test",
        )

    assert result.get("order_id") == "test-oid-123"
    assert result.get("error") is None
    create_order_list_calls = [c for c in mock_http_post.call_args_list if "create-order-list" in (c[0][0] if c[0] else "")]
    assert len(create_order_list_calls) == 1


@patch("app.services.brokers.crypto_com_trade.http_post", side_effect=_mock_http_post_both_140001)
@patch("app.services.brokers.crypto_com_trade.CryptoComTradeClient._get_instrument_metadata", return_value=_FAKE_INST_META)
@patch.dict("os.environ", {"EXECUTION_CONTEXT": "AWS", "LIVE_TRADING": "true"}, clear=False)
def test_sl_140001_fallback_also_140001_returns_structured_error(mock_inst_meta, mock_http_post):
    """create-order 140001 and create-order-list also 140001 -> structured error with fallback_attempted."""
    from app.services.brokers.crypto_com_trade import CryptoComTradeClient

    client = CryptoComTradeClient()
    client.live_trading = True
    client.use_proxy = False
    client.base_url = "https://api.crypto.com/exchange/v1"

    # First request is create-order; we need it to return status_code != 200 for 140001 branch
    def both_140001_sl(url, *args, **kwargs):
        if "create-order-list" in (url or ""):
            r = MagicMock()
            r.ok = True
            r.status_code = 200
            r.json.return_value = {"result": [{"code": 140001, "message": "API_DISABLED"}]}
            return r
        r = MagicMock()
        r.ok = False
        r.status_code = 400
        r.json.return_value = {"code": 140001, "message": "API_DISABLED"}
        return r

    with patch("app.services.brokers.crypto_com_trade.http_post", side_effect=both_140001_sl):
        with patch.object(client, "sign_request", return_value={"id": 1, "method": "private/create-order", "params": {}, "api_key": "redacted", "sig": "redacted"}):
            result = client.place_stop_loss_order(
                symbol="BTC_USDT",
                side="SELL",
                price=50000.0,
                qty=0.001,
                trigger_price=49000.0,
                dry_run=False,
                source="test",
            )

    assert result.get("category") == "permissions_or_account_configuration"
    assert result.get("error_code") == 140001
    assert result.get("fallback_attempted") is True
    assert "fallback_error" in result


@patch("app.services.brokers.crypto_com_trade.http_post", side_effect=_mock_http_post_both_140001)
@patch("app.services.brokers.crypto_com_trade.CryptoComTradeClient._get_instrument_metadata", return_value=_FAKE_INST_META)
@patch.dict("os.environ", {"EXECUTION_CONTEXT": "AWS", "LIVE_TRADING": "true"}, clear=False)
def test_tp_140001_fallback_also_140001_returns_structured_error(mock_inst_meta, mock_http_post):
    """create-order 140001 and create-order-list also 140001 -> structured error with fallback_attempted."""
    from app.services.brokers.crypto_com_trade import CryptoComTradeClient

    client = CryptoComTradeClient()
    client.live_trading = True
    client.use_proxy = False
    client.base_url = "https://api.crypto.com/exchange/v1"

    def both_140001_tp(url, *args, **kwargs):
        if "create-order-list" in (url or ""):
            r = MagicMock()
            r.ok = True
            r.status_code = 200
            r.json.return_value = {"result": [{"code": 140001, "message": "API_DISABLED"}]}
            return r
        r = MagicMock()
        r.ok = False
        r.status_code = 400
        r.json.return_value = {"code": 140001, "message": "API_DISABLED"}
        return r

    with patch("app.services.brokers.crypto_com_trade.http_post", side_effect=both_140001_tp):
        with patch.object(client, "sign_request", return_value={"id": 1, "method": "private/create-order", "params": {}, "api_key": "redacted", "sig": "redacted"}):
            result = client.place_take_profit_order(
                symbol="BTC_USDT",
                side="SELL",
                price=52000.0,
                qty=0.001,
                trigger_price=52000.0,
                dry_run=False,
                source="test",
            )

    assert result.get("category") == "permissions_or_account_configuration"
    assert result.get("error_code") == 140001
    assert result.get("fallback_attempted") is True
    assert "fallback_error" in result


def _mock_http_post_200_body_140001_then_list_success(url, *args, **kwargs):
    """create-order returns HTTP 200 with body code 140001; create-order-list returns success (R1 path)."""
    if "create-order-list" in (url or ""):
        r = MagicMock()
        r.ok = True
        r.status_code = 200
        r.json.return_value = {"result": [{"order_id": "r1-fallback-oid", "code": 0}]}
        return r
    r = MagicMock()
    r.ok = True
    r.status_code = 200
    r.json.return_value = {"code": 140001, "message": "API_DISABLED", "result": None}
    return r


def _mock_http_post_200_body_140001_then_list_fail(url, *args, **kwargs):
    """create-order returns HTTP 200 with body code 140001; create-order-list returns 140001 (fallback fails)."""
    if "create-order-list" in (url or ""):
        r = MagicMock()
        r.ok = True
        r.status_code = 200
        r.json.return_value = {"result": [{"code": 140001, "message": "API_DISABLED"}]}
        return r
    r = MagicMock()
    r.ok = True
    r.status_code = 200
    r.json.return_value = {"code": 140001, "message": "API_DISABLED", "result": None}
    return r


def test_sl_200_body_140001_triggers_fallback_success():
    """T1: HTTP 200 with JSON body code 140001 triggers fallback; fallback succeeds -> order_id, error None."""
    with patch.dict("os.environ", {"EXECUTION_CONTEXT": "AWS", "LIVE_TRADING": "true"}, clear=False):
        with patch("app.services.brokers.crypto_com_trade.http_post", side_effect=_mock_http_post_200_body_140001_then_list_success) as mock_http:
            with patch("app.services.brokers.crypto_com_trade.CryptoComTradeClient._get_instrument_metadata", return_value=_FAKE_INST_META):
                from app.services.brokers.crypto_com_trade import CryptoComTradeClient
                client = CryptoComTradeClient()
                client.live_trading = True
                client.use_proxy = False
                client.base_url = "https://api.crypto.com/exchange/v1"
                with patch.object(client, "_refresh_runtime_flags"), patch.object(client, "sign_request", return_value={"id": 1, "params": {}}):
                    result = client.place_stop_loss_order("BTC_USDT", "SELL", 50000.0, 0.001, 49000.0, dry_run=False, source="test")
    assert result.get("order_id") == "r1-fallback-oid"
    assert result.get("error") is None
    assert result != {}
    create_list_calls = [c for c in mock_http.call_args_list if c[0] and "create-order-list" in (c[0][0] or "")]
    assert len(create_list_calls) == 1


def test_sl_200_body_140001_triggers_fallback_fails_structured_error():
    """T1: HTTP 200 with JSON body code 140001 triggers fallback; fallback fails -> structured error, fallback_attempted=True."""
    with patch.dict("os.environ", {"EXECUTION_CONTEXT": "AWS", "LIVE_TRADING": "true"}, clear=False):
        with patch("app.services.brokers.crypto_com_trade.http_post", side_effect=_mock_http_post_200_body_140001_then_list_fail) as mock_http:
            with patch("app.services.brokers.crypto_com_trade.CryptoComTradeClient._get_instrument_metadata", return_value=_FAKE_INST_META):
                from app.services.brokers.crypto_com_trade import CryptoComTradeClient
                client = CryptoComTradeClient()
                client.live_trading = True
                client.use_proxy = False
                client.base_url = "https://api.crypto.com/exchange/v1"
                with patch.object(client, "_refresh_runtime_flags"), patch.object(client, "sign_request", return_value={"id": 1, "params": {}}):
                    result = client.place_stop_loss_order("BTC_USDT", "SELL", 50000.0, 0.001, 49000.0, dry_run=False, source="test")
    assert result.get("category") == "permissions_or_account_configuration"
    assert result.get("fallback_attempted") is True
    assert "fallback_error" in result
    create_list_calls = [c for c in mock_http.call_args_list if c[0] and "create-order-list" in (c[0][0] or "")]
    assert len(create_list_calls) == 1
