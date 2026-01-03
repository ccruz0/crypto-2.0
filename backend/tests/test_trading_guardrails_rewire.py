"""Tests for rewired trading guardrails (Live toggle, Telegram kill switch, Trade Yes per symbol)"""
import os
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy.orm import Session

from app.utils.trading_guardrails import can_place_real_order
from app.utils.live_trading import get_live_trading_status
from app.models.trading_settings import TradingSettings
from app.models.watchlist import WatchlistItem


@pytest.fixture
def mock_db():
    """Mock database session"""
    db = MagicMock(spec=Session)
    return db


@pytest.fixture
def mock_watchlist_item():
    """Mock WatchlistItem with trade_enabled=True"""
    item = MagicMock(spec=WatchlistItem)
    item.symbol = "BTC_USDT"
    item.trade_enabled = True
    item.is_deleted = False
    return item


class TestLiveToggle:
    """Test Live toggle blocking"""
    
    @patch('app.utils.trading_guardrails.get_live_trading_status')
    @patch('app.utils.trading_guardrails._get_telegram_kill_switch_status')
    @patch('app.utils.trading_guardrails._get_trade_enabled_for_symbol')
    @patch('app.utils.trading_guardrails.count_total_open_positions')
    def test_live_off_blocks_orders(self, mock_count, mock_trade_enabled, mock_kill_switch, mock_live, mock_db):
        """Live toggle OFF should block orders even if TRADING_ENABLED=true"""
        mock_live.return_value = False  # Live OFF
        mock_kill_switch.return_value = False  # Kill switch OFF
        mock_trade_enabled.return_value = True  # Trade Yes ON
        mock_count.return_value = 0  # Below limit
        
        # Mock query for risk limits
        mock_query = MagicMock()
        mock_query.filter.return_value.order_by.return_value.first.return_value = None
        mock_query.filter.return_value.scalar.return_value = 0
        mock_db.query.return_value = mock_query
        
        # Set TRADING_ENABLED=true (should still be blocked by Live OFF)
        with patch.dict(os.environ, {"TRADING_ENABLED": "true"}):
            allowed, reason = can_place_real_order(
                db=mock_db,
                symbol="BTC_USDT",
                order_usd_value=50.0,
                side="BUY",
            )
            
            assert allowed is False
            assert "Live toggle is OFF" in reason
            assert "TRADING_ENABLED" not in reason.upper()  # Should be blocked by Live, not env
    
    @patch('app.utils.trading_guardrails.get_live_trading_status')
    @patch('app.utils.trading_guardrails._get_telegram_kill_switch_status')
    @patch('app.utils.trading_guardrails._get_trade_enabled_for_symbol')
    @patch('app.utils.trading_guardrails.count_total_open_positions')
    def test_live_on_allows_if_other_checks_pass(self, mock_count, mock_trade_enabled, mock_kill_switch, mock_live, mock_db):
        """Live toggle ON should allow if other checks pass"""
        mock_live.return_value = True  # Live ON
        mock_kill_switch.return_value = False  # Kill switch OFF
        mock_trade_enabled.return_value = True  # Trade Yes ON
        mock_count.return_value = 0  # Below limit
        
        # Mock query for risk limits
        mock_query = MagicMock()
        mock_query.filter.return_value.order_by.return_value.first.return_value = None
        mock_query.filter.return_value.scalar.return_value = 0
        mock_db.query.return_value = mock_query
        
        allowed, reason = can_place_real_order(
            db=mock_db,
            symbol="BTC_USDT",
            order_usd_value=50.0,
            side="BUY",
        )
        
        assert allowed is True
        assert reason is None


class TestTelegramKillSwitch:
    """Test Telegram kill switch blocking"""
    
    @patch('app.utils.trading_guardrails.get_live_trading_status')
    @patch('app.utils.trading_guardrails._get_telegram_kill_switch_status')
    @patch('app.utils.trading_guardrails._get_trade_enabled_for_symbol')
    @patch('app.utils.trading_guardrails.count_total_open_positions')
    def test_kill_switch_on_blocks_orders(self, mock_count, mock_trade_enabled, mock_kill_switch, mock_live, mock_db):
        """Telegram kill switch ON should block orders even if Live ON and TradeYes YES"""
        mock_live.return_value = True  # Live ON
        mock_kill_switch.return_value = True  # Kill switch ON (trading disabled)
        mock_trade_enabled.return_value = True  # Trade Yes ON
        mock_count.return_value = 0  # Below limit
        
        allowed, reason = can_place_real_order(
            db=mock_db,
            symbol="BTC_USDT",
            order_usd_value=50.0,
            side="BUY",
        )
        
        assert allowed is False
        assert "kill switch" in reason.lower()
    
    @patch('app.utils.trading_guardrails.get_live_trading_status')
    @patch('app.utils.trading_guardrails._get_telegram_kill_switch_status')
    @patch('app.utils.trading_guardrails._get_trade_enabled_for_symbol')
    @patch('app.utils.trading_guardrails.count_total_open_positions')
    def test_kill_switch_off_allows_if_other_checks_pass(self, mock_count, mock_trade_enabled, mock_kill_switch, mock_live, mock_db):
        """Telegram kill switch OFF should allow if other checks pass"""
        mock_live.return_value = True  # Live ON
        mock_kill_switch.return_value = False  # Kill switch OFF
        mock_trade_enabled.return_value = True  # Trade Yes ON
        mock_count.return_value = 0  # Below limit
        
        # Mock query for risk limits
        mock_query = MagicMock()
        mock_query.filter.return_value.order_by.return_value.first.return_value = None
        mock_query.filter.return_value.scalar.return_value = 0
        mock_db.query.return_value = mock_query
        
        allowed, reason = can_place_real_order(
            db=mock_db,
            symbol="BTC_USDT",
            order_usd_value=50.0,
            side="BUY",
        )
        
        assert allowed is True
        assert reason is None


class TestTradeYesPerSymbol:
    """Test Trade Yes per symbol blocking"""
    
    @patch('app.utils.trading_guardrails.get_live_trading_status')
    @patch('app.utils.trading_guardrails._get_telegram_kill_switch_status')
    @patch('app.utils.trading_guardrails._get_trade_enabled_for_symbol')
    @patch('app.utils.trading_guardrails.count_total_open_positions')
    def test_trade_yes_off_blocks_orders(self, mock_count, mock_trade_enabled, mock_kill_switch, mock_live, mock_db):
        """Trade Yes OFF should block orders even if Live ON"""
        mock_live.return_value = True  # Live ON
        mock_kill_switch.return_value = False  # Kill switch OFF
        mock_trade_enabled.return_value = False  # Trade Yes OFF
        mock_count.return_value = 0  # Below limit
        
        allowed, reason = can_place_real_order(
            db=mock_db,
            symbol="BTC_USDT",
            order_usd_value=50.0,
            side="BUY",
        )
        
        assert allowed is False
        assert "Trade Yes is OFF" in reason
        assert "BTC_USDT" in reason
    
    @patch('app.utils.trading_guardrails.get_live_trading_status')
    @patch('app.utils.trading_guardrails._get_telegram_kill_switch_status')
    @patch('app.utils.trading_guardrails._get_trade_enabled_for_symbol')
    @patch('app.utils.trading_guardrails.count_total_open_positions')
    def test_trade_yes_on_allows_if_other_checks_pass(self, mock_count, mock_trade_enabled, mock_kill_switch, mock_live, mock_db):
        """Trade Yes ON should allow if other checks pass"""
        mock_live.return_value = True  # Live ON
        mock_kill_switch.return_value = False  # Kill switch OFF
        mock_trade_enabled.return_value = True  # Trade Yes ON
        mock_count.return_value = 0  # Below limit
        
        # Mock query for risk limits
        mock_query = MagicMock()
        mock_query.filter.return_value.order_by.return_value.first.return_value = None
        mock_query.filter.return_value.scalar.return_value = 0
        mock_db.query.return_value = mock_query
        
        allowed, reason = can_place_real_order(
            db=mock_db,
            symbol="BTC_USDT",
            order_usd_value=50.0,
            side="BUY",
        )
        
        assert allowed is True
        assert reason is None


class TestTradingEnabledEnvOverride:
    """Test TRADING_ENABLED env as optional final override"""
    
    @patch('app.utils.trading_guardrails.get_live_trading_status')
    @patch('app.utils.trading_guardrails._get_telegram_kill_switch_status')
    @patch('app.utils.trading_guardrails._get_trade_enabled_for_symbol')
    @patch('app.utils.trading_guardrails.count_total_open_positions')
    def test_trading_enabled_false_always_blocks(self, mock_count, mock_trade_enabled, mock_kill_switch, mock_live, mock_db):
        """TRADING_ENABLED=false should always block even if Live ON and TradeYes YES"""
        mock_live.return_value = True  # Live ON
        mock_kill_switch.return_value = False  # Kill switch OFF
        mock_trade_enabled.return_value = True  # Trade Yes ON
        mock_count.return_value = 0  # Below limit
        
        # Mock query for risk limits
        mock_query = MagicMock()
        mock_query.filter.return_value.order_by.return_value.first.return_value = None
        mock_query.filter.return_value.scalar.return_value = 0
        mock_db.query.return_value = mock_query
        
        with patch.dict(os.environ, {"TRADING_ENABLED": "false"}):
            allowed, reason = can_place_real_order(
                db=mock_db,
                symbol="BTC_USDT",
                order_usd_value=50.0,
                side="BUY",
            )
            
            assert allowed is False
            assert "TRADING_ENABLED" in reason.upper()
    
    @patch('app.utils.trading_guardrails.get_live_trading_status')
    @patch('app.utils.trading_guardrails._get_telegram_kill_switch_status')
    @patch('app.utils.trading_guardrails._get_trade_enabled_for_symbol')
    @patch('app.utils.trading_guardrails.count_total_open_positions')
    def test_trading_enabled_true_does_not_override_live_off(self, mock_count, mock_trade_enabled, mock_kill_switch, mock_live, mock_db):
        """TRADING_ENABLED=true should NOT allow if Live is OFF"""
        mock_live.return_value = False  # Live OFF
        mock_kill_switch.return_value = False  # Kill switch OFF
        mock_trade_enabled.return_value = True  # Trade Yes ON
        mock_count.return_value = 0  # Below limit
        
        with patch.dict(os.environ, {"TRADING_ENABLED": "true"}):
            allowed, reason = can_place_real_order(
                db=mock_db,
                symbol="BTC_USDT",
                order_usd_value=50.0,
                side="BUY",
            )
            
            assert allowed is False
            assert "Live toggle is OFF" in reason
            # Should be blocked by Live OFF, not by TRADING_ENABLED
            assert "TRADING_ENABLED" not in reason.upper()

