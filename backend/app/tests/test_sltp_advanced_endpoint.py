"""
Tests for the 2026-02-20 Crypto.com conditional-order endpoint migration.

Root cause of the 2026-07-03 real-money incident: Crypto.com removed STOP_LOSS / STOP_LIMIT /
TAKE_PROFIT / TAKE_PROFIT_LIMIT from `type` on `private/create-order` (rejected with code 140001).
Conditional orders must now be created via `private/advanced/create-order` (with `ref_price_type`)
and cancelled via `private/advanced/cancel-order`.

These tests assert the routing without hitting the network, by stubbing the proxy call and the
instrument-metadata / gate seams.
"""

import pytest

from app.services.brokers import crypto_com_trade as cct
from app.services.brokers.crypto_com_trade import (
    CryptoComTradeClient,
    CONDITIONAL_ORDER_TYPES,
    ADVANCED_CREATE_ORDER_ENDPOINT,
    ADVANCED_CANCEL_ORDER_ENDPOINT,
    DEFAULT_REF_PRICE_TYPE,
    _is_conditional_order_type,
)

_META = {
    "instrument_name": "DOT_USDT",
    "price_tick_size": "0.001",
    "qty_tick_size": "0.01",
    "min_quantity": "0.01",
    "price_decimals": 3,
    "quantity_decimals": 2,
}


def _make_client(monkeypatch, captured):
    """Build a client that never touches the network; proxy calls are captured."""
    client = CryptoComTradeClient.__new__(CryptoComTradeClient)
    # Minimal attributes needed by the placement/cancel paths.
    client._use_proxy_default = True  # force the proxy branch (no signing / no HTTP)
    client.base_url = "https://api.crypto.com/exchange/v1"
    client.api_key = "test-key"
    client.api_secret = "test-secret"
    client.live_trading = True
    client._instrument_cache = {}
    client._sltp_preferred_variants = {}
    client._last_trigger_alert_time = 0

    # Stub the seams.
    monkeypatch.setattr(client, "_refresh_runtime_flags", lambda: None)
    monkeypatch.setattr(client, "_resolve_actual_dry_run", lambda dry_run: False)
    monkeypatch.setattr(client, "_get_instrument_metadata", lambda symbol: dict(_META))

    def _fake_call_proxy(method, params):
        captured.append((method, dict(params)))
        return {"code": 0, "result": {"order_id": "OID-TEST-123"}}

    monkeypatch.setattr(client, "_call_proxy", _fake_call_proxy)

    # The live-trading gate is imported inside the methods; make it a no-op.
    import app.services.live_trading_gate as gate
    monkeypatch.setattr(gate, "require_mutation_allowed_for_broker", lambda *a, **k: None)

    return client


def test_is_conditional_order_type():
    for t in ("STOP_LOSS", "STOP_LIMIT", "TAKE_PROFIT", "TAKE_PROFIT_LIMIT"):
        assert _is_conditional_order_type(t) is True
        assert _is_conditional_order_type(t.lower()) is True
    for t in ("MARKET", "LIMIT", "", None):
        assert _is_conditional_order_type(t) is False
    assert CONDITIONAL_ORDER_TYPES == {"STOP_LOSS", "STOP_LIMIT", "TAKE_PROFIT", "TAKE_PROFIT_LIMIT"}


def test_stop_loss_routes_to_advanced_endpoint(monkeypatch):
    captured = []
    client = _make_client(monkeypatch, captured)

    result = client.place_stop_loss_order(
        symbol="DOT_USDT",
        side="SELL",
        price=4.123,
        qty=0.5,
        trigger_price=4.123,
        entry_price=4.5,  # provided so no DB lookup happens
        dry_run=False,
        source="test",
    )

    assert result.get("order_id") == "OID-TEST-123"
    assert captured, "expected a proxy call"
    method, params = captured[0]
    assert method == ADVANCED_CREATE_ORDER_ENDPOINT
    assert params["type"] == "STOP_LIMIT"
    assert params["ref_price_type"] == DEFAULT_REF_PRICE_TYPE == "MARK_PRICE"
    assert "ref_price" in params and "trigger_price" in params


def test_take_profit_routes_to_advanced_endpoint(monkeypatch):
    captured = []
    client = _make_client(monkeypatch, captured)

    result = client.place_take_profit_order(
        symbol="DOT_USDT",
        side="SELL",
        price=5.678,
        qty=0.5,
        trigger_price=5.678,
        entry_price=4.5,
        dry_run=False,
        source="test",
    )

    assert result.get("order_id") == "OID-TEST-123"
    assert captured, "expected a proxy call"
    method, params = captured[0]
    assert method == ADVANCED_CREATE_ORDER_ENDPOINT
    assert params["type"] == "TAKE_PROFIT_LIMIT"
    assert params["ref_price_type"] == DEFAULT_REF_PRICE_TYPE
    # First attempt should match the verified minimal payload: no trigger_condition.
    assert "trigger_condition" not in params


@pytest.mark.parametrize("order_type", sorted(CONDITIONAL_ORDER_TYPES))
def test_cancel_conditional_routes_to_advanced(monkeypatch, order_type):
    captured = []
    client = _make_client(monkeypatch, captured)
    # cancel_order calls require_aws_or_skip at the top; make it a no-op.
    monkeypatch.setattr(cct, "require_aws_or_skip", lambda *a, **k: None)
    # Order detail says this is a conditional order.
    monkeypatch.setattr(
        client, "_get_order_detail_summary", lambda oid: {"type": order_type, "status": "ACTIVE"}
    )

    client.cancel_order("OID-TEST-123")

    assert captured, "expected a proxy call"
    method, _params = captured[0]
    assert method == ADVANCED_CANCEL_ORDER_ENDPOINT


def test_cancel_regular_order_uses_standard_endpoint(monkeypatch):
    captured = []
    client = _make_client(monkeypatch, captured)
    monkeypatch.setattr(cct, "require_aws_or_skip", lambda *a, **k: None)
    monkeypatch.setattr(
        client, "_get_order_detail_summary", lambda oid: {"type": "LIMIT", "status": "ACTIVE"}
    )

    client.cancel_order("OID-TEST-123")

    assert captured, "expected a proxy call"
    method, _params = captured[0]
    assert method == "private/cancel-order"


def test_advanced_fallback_helper_uses_advanced_endpoint(monkeypatch):
    captured = []
    client = _make_client(monkeypatch, captured)

    ok, order_id, raw = client._try_create_order_list_with_params(
        {
            "instrument_name": "DOT_USDT",
            "side": "SELL",
            "type": "STOP_LIMIT",
            "price": "4.123",
            "quantity": "0.50",
            "trigger_price": "4.123",
            "ref_price": "4.123",
        }
    )

    assert ok is True
    assert order_id == "OID-TEST-123"
    assert raw is None
    assert captured, "expected a proxy call"
    method, params = captured[0]
    assert method == ADVANCED_CREATE_ORDER_ENDPOINT
    assert params["ref_price_type"] == DEFAULT_REF_PRICE_TYPE
