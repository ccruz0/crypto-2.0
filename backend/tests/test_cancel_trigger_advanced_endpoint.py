"""Cancel TP/SL via advanced endpoint when spot detail is empty."""

from __future__ import annotations

import os
from unittest.mock import patch

from app.api.routes_orders import _order_type_for_cancel
from app.services.brokers.crypto_com_trade import (
    ADVANCED_CANCEL_ORDER_ENDPOINT,
    CryptoComTradeClient,
)


def test_order_type_for_cancel_maps_role_when_type_missing():
    assert _order_type_for_cancel(order_type=None, order_role="STOP_LOSS") == "STOP_LIMIT"
    assert _order_type_for_cancel(order_type=None, order_role="TAKE_PROFIT") == "TAKE_PROFIT_LIMIT"
    assert _order_type_for_cancel(order_type="STOP_LIMIT", order_role=None) == "STOP_LIMIT"


def _live_client() -> CryptoComTradeClient:
    with patch.dict(os.environ, {"LIVE_TRADING": "true"}, clear=False):
        with patch("app.core.runtime.is_aws_runtime", return_value=False):
            return CryptoComTradeClient()


def test_cancel_uses_advanced_when_order_type_passed():
    client = _live_client()
    with patch("app.services.brokers.crypto_com_trade.require_aws_or_skip", return_value=None):
        with patch.object(client, "_resolve_actual_dry_run", return_value=False):
            with patch("app.services.live_trading_gate.require_mutation_allowed_for_broker"):
                with patch.object(client, "_get_order_detail_summary", return_value=None):
                    with patch.object(client, "get_advanced_order_detail") as adv:
                        with patch.object(
                            client,
                            "sign_request",
                            side_effect=lambda method, params, **kw: {
                                "id": 1,
                                "method": method,
                                "params": params,
                            },
                        ) as sign:
                            with patch(
                                "app.services.brokers.crypto_com_trade.http_post"
                            ) as post:
                                post.return_value.status_code = 200
                                post.return_value.json.return_value = {
                                    "code": 0,
                                    "result": {"order_id": "tp-1"},
                                }
                                # Force direct API path (no proxy).
                                client.use_proxy = False
                                out = client.cancel_order(
                                    "tp-1", order_type="TAKE_PROFIT_LIMIT", dry_run=False
                                )
    adv.assert_not_called()
    assert out.get("order_id") == "tp-1"
    assert sign.call_args.args[0] == ADVANCED_CANCEL_ORDER_ENDPOINT
    assert ADVANCED_CANCEL_ORDER_ENDPOINT in str(post.call_args.args[0])


def test_cancel_falls_back_to_advanced_detail_when_spot_empty():
    """DOGE ops bug: spot detail None → wrong endpoint → false OK."""
    client = _live_client()
    with patch("app.services.brokers.crypto_com_trade.require_aws_or_skip", return_value=None):
        with patch.object(client, "_resolve_actual_dry_run", return_value=False):
            with patch("app.services.live_trading_gate.require_mutation_allowed_for_broker"):
                with patch.object(client, "_get_order_detail_summary", return_value=None):
                    with patch.object(
                        client,
                        "get_advanced_order_detail",
                        return_value={
                            "code": 0,
                            "result": {
                                "order_id": "73817490102070478",
                                "type": "STOP_LIMIT",
                                "status": "ACTIVE",
                            },
                        },
                    ):
                        with patch.object(
                            client,
                            "sign_request",
                            side_effect=lambda method, params, **kw: {
                                "id": 1,
                                "method": method,
                                "params": params,
                            },
                        ) as sign:
                            with patch(
                                "app.services.brokers.crypto_com_trade.http_post"
                            ) as post:
                                post.return_value.status_code = 200
                                post.return_value.json.return_value = {
                                    "code": 0,
                                    "result": {"order_id": "73817490102070478"},
                                }
                                client.use_proxy = False
                                out = client.cancel_order(
                                    "73817490102070478", dry_run=False
                                )
    assert "error" not in out
    assert sign.call_args.args[0] == ADVANCED_CANCEL_ORDER_ENDPOINT


def test_cancel_rejects_nonzero_exchange_code():
    client = _live_client()
    with patch("app.services.brokers.crypto_com_trade.require_aws_or_skip", return_value=None):
        with patch.object(client, "_resolve_actual_dry_run", return_value=False):
            with patch("app.services.live_trading_gate.require_mutation_allowed_for_broker"):
                with patch.object(
                    client,
                    "_get_order_detail_summary",
                    return_value={"type": "LIMIT"},
                ):
                    with patch.object(client, "_is_advanced_oto_order", return_value=False):
                        with patch.object(
                            client,
                            "sign_request",
                            return_value={"id": 1, "method": "private/cancel-order"},
                        ):
                            with patch(
                                "app.services.brokers.crypto_com_trade.http_post"
                            ) as post:
                                post.return_value.status_code = 200
                                post.return_value.json.return_value = {
                                    "code": 10004,
                                    "message": "Order not found",
                                }
                                client.use_proxy = False
                                out = client.cancel_order("missing-1", dry_run=False)
    assert out.get("error")
    assert out.get("code") == 10004
