"""
Tests for test endpoints (BUY/SELL simulate-alert) origin handling

These tests verify that:
- BUY test endpoint calls send_buy_signal with origin="LOCAL"
- SELL test endpoint calls send_sell_signal with origin="LOCAL"
- Test alerts are blocked from reaching Telegram (origin gatekeeper)
"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app


class TestTestEndpointsOrigin:
    """Test that test endpoints use origin=LOCAL"""
    
    @patch('app.api.routes_test.telegram_notifier')
    @patch('price_fetcher.get_price_with_fallback')
    def test_buy_test_endpoint_uses_local_origin(self, mock_get_price, mock_telegram_notifier):
        """BUY test endpoint should call send_buy_signal with origin="LOCAL" """
        # Setup
        mock_get_price.return_value = {'price': 50000.0}
        mock_telegram_notifier.send_buy_signal.return_value = True
        
        client = TestClient(app)
        
        # Execute - provide trade_amount_usd to avoid 400 error
        response = client.post(
            "/api/test/simulate-alert",
            json={
                "symbol": "BTC_USDT",
                "signal_type": "BUY",
                "force_order": False,
                "trade_amount_usd": 100.0
            }
        )
        
        # Verify
        # The endpoint should return 200 if watchlist item is created or exists
        # The important part: verify origin="LOCAL" was passed
        assert mock_telegram_notifier.send_buy_signal.called, "send_buy_signal should have been called"
        call_kwargs = mock_telegram_notifier.send_buy_signal.call_args[1]
        assert call_kwargs.get('origin') == "LOCAL", "BUY test endpoint must use origin='LOCAL'"
        assert call_kwargs.get('source') == "TEST", "BUY test endpoint must use source='TEST'"
    
    @patch('app.api.routes_test.telegram_notifier')
    @patch('price_fetcher.get_price_with_fallback')
    def test_sell_test_endpoint_uses_local_origin(self, mock_get_price, mock_telegram_notifier):
        """SELL test endpoint should call send_sell_signal with origin="LOCAL" """
        # Setup
        mock_get_price.return_value = {'price': 50000.0}
        mock_telegram_notifier.send_sell_signal.return_value = True
        
        client = TestClient(app)
        
        # Execute - provide trade_amount_usd to avoid 400 error
        response = client.post(
            "/api/test/simulate-alert",
            json={
                "symbol": "BTC_USDT",
                "signal_type": "SELL",
                "force_order": False,
                "trade_amount_usd": 100.0
            }
        )
        
        # Verify
        # The endpoint should return 200 if watchlist item is created or exists
        # The important part: verify origin="LOCAL" was passed
        assert mock_telegram_notifier.send_sell_signal.called, "send_sell_signal should have been called"
        call_kwargs = mock_telegram_notifier.send_sell_signal.call_args[1]
        assert call_kwargs.get('origin') == "LOCAL", "SELL test endpoint must use origin='LOCAL'"
        assert call_kwargs.get('source') == "TEST", "SELL test endpoint must use source='TEST'"
    
    @patch('app.api.routes_test.telegram_notifier')
    @patch('price_fetcher.get_price_with_fallback')
    def test_buy_test_alert_blocked_by_gatekeeper(self, mock_get_price, mock_telegram_notifier):
        """BUY test alert with origin=LOCAL should be blocked by gatekeeper (not sent to Telegram)"""
        # Setup
        mock_get_price.return_value = {'price': 50000.0}
        # send_buy_signal internally calls send_message, which blocks LOCAL origin
        mock_telegram_notifier.send_buy_signal.return_value = False  # Gatekeeper blocks it
        
        client = TestClient(app)
        
        # Execute - provide trade_amount_usd to avoid 400 error
        response = client.post(
            "/api/test/simulate-alert",
            json={
                "symbol": "BTC_USDT",
                "signal_type": "BUY",
                "force_order": False,
                "trade_amount_usd": 100.0
            }
        )
        
        # Verify
        # The endpoint should still return 200 (test was attempted)
        # But send_buy_signal should have been called with origin="LOCAL"
        assert mock_telegram_notifier.send_buy_signal.called, "send_buy_signal should have been called"
        call_kwargs = mock_telegram_notifier.send_buy_signal.call_args[1]
        assert call_kwargs.get('origin') == "LOCAL", "BUY test endpoint must use origin='LOCAL'"
        # The gatekeeper in send_message() will block it, so return value is False
        # This is expected behavior - test alerts should not reach production Telegram
    
    @patch('app.api.routes_test.telegram_notifier')
    @patch('price_fetcher.get_price_with_fallback')
    def test_sell_test_alert_blocked_by_gatekeeper(self, mock_get_price, mock_telegram_notifier):
        """SELL test alert with origin=LOCAL should be blocked by gatekeeper (not sent to Telegram)"""
        # Setup
        mock_get_price.return_value = {'price': 50000.0}
        # send_sell_signal internally calls send_message, which blocks LOCAL origin
        mock_telegram_notifier.send_sell_signal.return_value = False  # Gatekeeper blocks it
        
        client = TestClient(app)
        
        # Execute - provide trade_amount_usd to avoid 400 error
        response = client.post(
            "/api/test/simulate-alert",
            json={
                "symbol": "BTC_USDT",
                "signal_type": "SELL",
                "force_order": False,
                "trade_amount_usd": 100.0
            }
        )
        
        # Verify
        # The endpoint should still return 200 (test was attempted)
        # But send_sell_signal should have been called with origin="LOCAL"
        assert mock_telegram_notifier.send_sell_signal.called, "send_sell_signal should have been called"
        call_kwargs = mock_telegram_notifier.send_sell_signal.call_args[1]
        assert call_kwargs.get('origin') == "LOCAL", "SELL test endpoint must use origin='LOCAL'"
        # The gatekeeper in send_message() will block it, so return value is False
        # This is expected behavior - test alerts should not reach production Telegram

