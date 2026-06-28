"""Tests for skip_empty_fallbacks on get_order_history."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.brokers.crypto_com_trade import CryptoComTradeClient


def _empty_history_response() -> dict:
    return {
        "code": 0,
        "result": {"data": []},
    }


@patch("app.services.brokers.crypto_com_trade.http_post")
@patch.object(CryptoComTradeClient, "sign_request", return_value={"id": 1, "method": "private/get-order-history"})
@patch.object(CryptoComTradeClient, "_refresh_runtime_flags")
def test_skip_empty_fallbacks_avoids_retry_chain(mock_refresh, mock_sign, mock_post):
    client = CryptoComTradeClient()
    client.api_key = "key"
    client.api_secret = "secret"
    client.use_proxy = False
    client.base_url = "https://api.crypto.com/exchange/v1"

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = _empty_history_response()
    mock_post.return_value = response

    result = client.get_order_history(
        page_size=100,
        start_time=1_700_000_000_000,
        end_time=1_700_100_000_000,
        instrument_name="BTC_USD",
        skip_empty_fallbacks=True,
    )

    assert result["data"] == []
    assert mock_post.call_count == 1
