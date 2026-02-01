"""
Safety test: when EXECUTION_CONTEXT=LOCAL, no private Crypto.com API requests must be made.

Mocks the HTTP client and asserts no requests to paths like /private/ or methods private/*
are sent. Local runs must only use public endpoints (e.g. get-tickers).
Asserts return payload includes {"skipped": True, "reason": SKIP_REASON, "label": ...}.
"""
import os
import pytest
from unittest.mock import patch, MagicMock

from app.core.crypto_com_guardrail import SKIP_REASON

# Module under test reads EXECUTION_CONTEXT at import/call time
LOCAL_ENV = {"EXECUTION_CONTEXT": "LOCAL"}


class TestLocalNoPrivateCryptoCalls:
    """When EXECUTION_CONTEXT=LOCAL, private endpoints must not be called."""

    @pytest.fixture(autouse=True)
    def set_local_context(self):
        with patch.dict(os.environ, LOCAL_ENV, clear=False):
            yield

    @patch("app.services.brokers.crypto_com_trade.http_post")
    def test_get_account_summary_does_not_call_private_when_local(self, mock_http_post):
        """get_account_summary must return skip payload and not call http_post for private."""
        from app.services.brokers.crypto_com_trade import CryptoComTradeClient
        client = CryptoComTradeClient()
        result = client.get_account_summary()
        assert result.get("skipped") is True
        assert result.get("reason") == SKIP_REASON
        assert "label" in result
        assert "accounts" in result
        # No http_post call must have been made to a private path
        for call in (mock_http_post.call_args_list or []):
            url = (call[0][0] if call[0] else None) or (call[1].get("url") if isinstance(call[1], dict) else "")
            if not url and len(call[0]) >= 1:
                url = str(call[0][0])
            assert "/private" not in (url or ""), f"LOCAL must not call private URL: {url}"

    @patch("app.services.brokers.crypto_com_trade.http_post")
    def test_get_open_orders_does_not_call_private_when_local(self, mock_http_post):
        """get_open_orders must return skip payload and not call http_post for private."""
        with patch.dict(os.environ, LOCAL_ENV, clear=False):
            from app.services.brokers.crypto_com_trade import CryptoComTradeClient
            client = CryptoComTradeClient()
            result = client.get_open_orders(page=0, page_size=10)
        assert result.get("skipped") is True
        assert result.get("reason") == SKIP_REASON
        assert "label" in result
        assert "data" in result
        for call in (mock_http_post.call_args_list or []):
            url = (call[0][0] if call[0] else None) or ""
            assert "/private" not in (url or ""), f"LOCAL must not call private URL: {url}"

    @patch("app.services.brokers.crypto_com_trade.http_post")
    def test_place_market_order_returns_skip_and_does_not_call_private_when_local(self, mock_http_post):
        """place_market_order must return skip payload and not call http_post for private."""
        with patch.dict(os.environ, LOCAL_ENV, clear=False):
            from app.services.brokers.crypto_com_trade import CryptoComTradeClient
            client = CryptoComTradeClient()
            result = client.place_market_order(
                symbol="BTC_USDT", side="BUY", notional=100.0, dry_run=False, source="TEST"
            )
        assert result.get("skipped") is True
        assert result.get("reason") == SKIP_REASON
        assert "label" in result
        for call in (mock_http_post.call_args_list or []):
            url = (call[0][0] if call[0] else None) or ""
            assert "/private" not in (url or ""), f"LOCAL must not call private URL: {url}"

    @patch("app.services.brokers.crypto_com_trade.http_post")
    def test_no_private_requests_when_local(self, mock_http_post):
        """Any trade_client method in LOCAL must not result in http_post to /private/."""
        with patch.dict(os.environ, LOCAL_ENV, clear=False):
            from app.services.brokers.crypto_com_trade import CryptoComTradeClient
            client = CryptoComTradeClient()
            client.get_account_summary()
            client.get_open_orders(page=0, page_size=5)
            client.get_trigger_orders(page=0, page_size=5)
            client.get_order_history(page_size=5)
            client.place_market_order(symbol="BTC_USDT", side="BUY", notional=50.0, dry_run=False, source="TEST")
            client.cancel_order("dummy_order_id")
        for call in (mock_http_post.call_args_list or []):
            args, kwargs = call[0], (call[1] if len(call) > 1 else {})
            url = (args[0] if args else None) or kwargs.get("url") or ""
            assert "/private" not in str(url), f"LOCAL must not call private endpoint: {url}"
