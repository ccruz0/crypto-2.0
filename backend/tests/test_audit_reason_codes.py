"""
Regression tests for audit script reason codes.

Tests cover:
1. Telegram failure scenario
2. Cooldown active with remaining seconds
3. Market data stale scenario

These tests ensure the auditor correctly identifies blocking reasons.
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch, MagicMock
from sqlalchemy.orm import Session

# Import the audit functions
import sys
from pathlib import Path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from scripts.audit_no_alerts_no_trades import (
    analyze_symbol,
    check_telegram_health,
    check_market_data_freshness,
    SKIP_TELEGRAM_FAILURE,
    SKIP_COOLDOWN_ACTIVE,
    SKIP_MARKET_DATA_STALE,
    SKIP_NO_SIGNAL,
    SKIP_ALERT_DISABLED,
    EXEC_ALERT_SENT,
)
from app.models.watchlist import WatchlistItem
from app.models.market_price import MarketPrice
from app.models.signal_throttle import SignalThrottleState


@pytest.fixture
def mock_db():
    """Create a mock database session"""
    return Mock(spec=Session)


@pytest.fixture
def sample_watchlist_item():
    """Create a sample watchlist item for testing"""
    item = Mock(spec=WatchlistItem)
    item.symbol = "ETH_USDT"
    item.alert_enabled = True
    item.trade_enabled = True
    item.buy_alert_enabled = True
    item.sell_alert_enabled = True
    item.trade_amount_usd = 100.0
    item.min_price_change_pct = 1.0
    item.is_deleted = False
    return item


@pytest.fixture
def now_utc():
    """Current UTC time for testing"""
    return datetime.now(timezone.utc)


class TestTelegramFailure:
    """Test scenario 1: Telegram failure"""
    
    def test_telegram_disabled_identified(self, mock_db):
        """Test that audit correctly identifies when Telegram is disabled"""
        # Mock Telegram notifier as disabled
        with patch('scripts.audit_no_alerts_no_trades.telegram_notifier') as mock_notifier:
            mock_notifier.enabled = False
            mock_notifier.bot_token = None
            mock_notifier.chat_id = None
            
            result = check_telegram_health(since_hours=168, db=mock_db)
            
            assert result["status"] == "FAIL"
            assert not result["enabled"]
            assert not result["bot_token_present"]
            assert not result["chat_id_present"]
            assert "TELEGRAM_BOT_TOKEN not set" in result["evidence"]
            # Check for any evidence mentioning Telegram disabled
            assert any("Telegram notifier disabled" in ev or "disabled" in ev.lower() for ev in result["evidence"])
    
    def test_telegram_missing_credentials(self, mock_db):
        """Test that audit identifies missing credentials"""
        with patch('scripts.audit_no_alerts_no_trades.telegram_notifier') as mock_notifier:
            mock_notifier.enabled = False
            mock_notifier.bot_token = ""
            mock_notifier.chat_id = ""
            
            # Mock environment
            with patch.dict('os.environ', {'ENVIRONMENT': 'local'}):
                result = check_telegram_health(since_hours=168, db=mock_db)
                
                assert result["status"] == "FAIL"
                assert "ENVIRONMENT=" in result["evidence"][-1] or "ENVIRONMENT=local" in str(result["evidence"])
    
    def test_telegram_enabled_passes(self, mock_db):
        """Test that audit passes when Telegram is properly configured"""
        with patch('scripts.audit_no_alerts_no_trades.telegram_notifier') as mock_notifier:
            mock_notifier.enabled = True
            mock_notifier.bot_token = "test_token"
            mock_notifier.chat_id = "test_chat_id"
            
            with patch.dict('os.environ', {'ENVIRONMENT': 'aws'}):
                result = check_telegram_health(since_hours=168, db=mock_db)
                
                # Should pass if enabled and credentials present
                assert result["enabled"] is True
                assert result["bot_token_present"] is True
                assert result["chat_id_present"] is True


class TestCooldownActive:
    """Test scenario 2: Cooldown active with remaining seconds"""
    
    def test_cooldown_active_identified(self, mock_db, sample_watchlist_item, now_utc):
        """Test that audit correctly identifies active cooldown"""
        # Create a throttle state with recent timestamp (within 60s cooldown)
        recent_time = now_utc - timedelta(seconds=30)  # 30 seconds ago
        
        with patch('scripts.audit_no_alerts_no_trades.fetch_signal_states') as mock_fetch:
            # Mock throttle state showing recent BUY signal
            mock_snapshot = Mock()
            mock_snapshot.timestamp = recent_time
            mock_snapshot.price = 2000.0
            mock_snapshot.force_next_signal = False
            
            mock_fetch.return_value = {"BUY": mock_snapshot}
            
            # Mock market price
            mock_price = Mock(spec=MarketPrice)
            mock_price.price = 2100.0
            mock_price.updated_at = now_utc - timedelta(minutes=5)
            mock_db.query.return_value.filter.return_value.first.return_value = mock_price
            
            # Mock get_signals to return buy signal
            with patch('scripts.audit_no_alerts_no_trades.get_signals') as mock_signals:
                mock_signals.return_value = {"buy": True, "sell": False}
                
                # Mock resolve_strategy_profile
                with patch('scripts.audit_no_alerts_no_trades.resolve_strategy_profile') as mock_resolve:
                    mock_resolve.return_value = (Mock(value="swing"), Mock(value="conservative"))
                    
                    result = analyze_symbol(
                        "ETH_USDT",
                        sample_watchlist_item,
                        mock_db,
                        now_utc
                    )
                    
                    # Should identify cooldown as blocking reason
                    assert result["alert_reason"] == SKIP_COOLDOWN_ACTIVE
                    assert SKIP_COOLDOWN_ACTIVE in result["alert_blocked_by"]
                    assert "remaining" in result["alert_blocked_by"].lower() or "30" in result["alert_blocked_by"]
                    assert "cooldown_remaining" in result["evidence"]
                    assert result["evidence"]["cooldown_remaining"] < 60.0
                    assert result["evidence"]["cooldown_remaining"] > 0
    
    def test_cooldown_expired_allows_alert(self, mock_db, sample_watchlist_item, now_utc):
        """Test that audit allows alert when cooldown has expired"""
        # Create a throttle state with old timestamp (beyond 60s cooldown)
        old_time = now_utc - timedelta(seconds=120)  # 2 minutes ago
        
        with patch('scripts.audit_no_alerts_no_trades.fetch_signal_states') as mock_fetch:
            mock_snapshot = Mock()
            mock_snapshot.timestamp = old_time
            mock_snapshot.price = 2000.0
            mock_snapshot.force_next_signal = False
            
            mock_fetch.return_value = {"BUY": mock_snapshot}
            
            # Mock market price
            mock_price = Mock(spec=MarketPrice)
            mock_price.price = 2100.0  # 5% price change
            mock_price.updated_at = now_utc - timedelta(minutes=5)
            mock_db.query.return_value.filter.return_value.first.return_value = mock_price
            
            with patch('scripts.audit_no_alerts_no_trades.get_signals') as mock_signals:
                mock_signals.return_value = {"buy": True, "sell": False}
                
                with patch('scripts.audit_no_alerts_no_trades.resolve_strategy_profile') as mock_resolve:
                    mock_resolve.return_value = (Mock(value="swing"), Mock(value="conservative"))
                    
                    result = analyze_symbol(
                        "ETH_USDT",
                        sample_watchlist_item,
                        mock_db,
                        now_utc
                    )
                    
                    # Should allow alert (cooldown expired and price change sufficient)
                    assert result["alert_decision"] == "EXEC"
                    assert result["alert_reason"] == EXEC_ALERT_SENT


class TestMarketDataStale:
    """Test scenario 3: Market data stale"""
    
    def test_stale_market_data_identified(self, mock_db, sample_watchlist_item, now_utc):
        """Test that audit correctly identifies stale market data"""
        # Create market price with old timestamp (>30 minutes)
        stale_time = now_utc - timedelta(minutes=45)
        
        mock_price = Mock(spec=MarketPrice)
        mock_price.price = 2000.0
        mock_price.updated_at = stale_time
        mock_db.query.return_value.filter.return_value.first.return_value = mock_price
        
        result = analyze_symbol(
            "ETH_USDT",
            sample_watchlist_item,
            mock_db,
            now_utc
        )
        
        # Should identify stale market data as blocking reason
        assert result["alert_reason"] == SKIP_MARKET_DATA_STALE
        assert result["alert_blocked_by"] == SKIP_MARKET_DATA_STALE
        assert "price_age_minutes" in result["evidence"]
        assert result["evidence"]["price_age_minutes"] > 30
    
    def test_fresh_market_data_passes(self, mock_db, sample_watchlist_item, now_utc):
        """Test that audit passes when market data is fresh"""
        # Create market price with recent timestamp (<30 minutes)
        recent_time = now_utc - timedelta(minutes=10)
        
        mock_price = Mock(spec=MarketPrice)
        mock_price.price = 2000.0
        mock_price.updated_at = recent_time
        mock_db.query.return_value.filter.return_value.first.return_value = mock_price
        
        # Mock get_signals to return no signal (so we don't need to mock throttle)
        with patch('scripts.audit_no_alerts_no_trades.get_signals') as mock_signals:
            mock_signals.return_value = {"buy": False, "sell": False}
            
            with patch('scripts.audit_no_alerts_no_trades.resolve_strategy_profile') as mock_resolve:
                mock_resolve.return_value = (Mock(value="swing"), Mock(value="conservative"))
                
                result = analyze_symbol(
                    "ETH_USDT",
                    sample_watchlist_item,
                    mock_db,
                    now_utc
                )
                
                # Should not be blocked by stale data
                assert result["alert_reason"] != SKIP_MARKET_DATA_STALE
                assert result["current_price"] == 2000.0
                assert result["last_price_update"] is not None
    
    def test_market_data_freshness_check_function(self, mock_db):
        """Test the market data freshness check function directly"""
        now = datetime.now(timezone.utc)
        stale_time = now - timedelta(minutes=45)
        
        # Mock MarketPrice query
        mock_price = Mock(spec=MarketPrice)
        mock_price.symbol = "ETH_USDT"
        mock_price.updated_at = stale_time
        
        mock_query = Mock()
        mock_query.filter.return_value.first.return_value = mock_price
        mock_db.query.return_value = mock_query
        
        with patch('scripts.audit_no_alerts_no_trades.MarketPrice'):
            result = check_market_data_freshness(symbols=["ETH_USDT"], since_hours=168, db=mock_db)
            
            assert result["status"] == "FAIL"
            assert len(result["stale_symbols"]) > 0
            assert any(s["symbol"] == "ETH_USDT" for s in result["stale_symbols"])
            assert any(s["age_minutes"] > 30 for s in result["stale_symbols"])


class TestReasonCodeConsistency:
    """Test that reason codes are consistent and canonical"""
    
    def test_no_signal_reason_code(self, mock_db, sample_watchlist_item, now_utc):
        """Test SKIP_NO_SIGNAL reason code"""
        mock_price = Mock(spec=MarketPrice)
        mock_price.price = 2000.0
        mock_price.updated_at = now_utc - timedelta(minutes=10)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_price
        
        with patch('scripts.audit_no_alerts_no_trades.get_signals') as mock_signals:
            mock_signals.return_value = {"buy": False, "sell": False}
            
            with patch('scripts.audit_no_alerts_no_trades.resolve_strategy_profile') as mock_resolve:
                mock_resolve.return_value = (Mock(value="swing"), Mock(value="conservative"))
                
                result = analyze_symbol(
                    "ETH_USDT",
                    sample_watchlist_item,
                    mock_db,
                    now_utc
                )
                
                assert result["alert_reason"] == SKIP_NO_SIGNAL
                assert result["alert_blocked_by"] == SKIP_NO_SIGNAL
    
    def test_alert_disabled_reason_code(self, mock_db, now_utc):
        """Test SKIP_ALERT_DISABLED reason code"""
        item = Mock(spec=WatchlistItem)
        item.symbol = "ETH_USDT"
        item.alert_enabled = False  # Disabled
        item.trade_enabled = False
        item.buy_alert_enabled = False
        item.sell_alert_enabled = False
        item.trade_amount_usd = None
        item.is_deleted = False
        
        mock_price = Mock(spec=MarketPrice)
        mock_price.price = 2000.0
        mock_price.updated_at = now_utc - timedelta(minutes=10)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_price
        
        with patch('scripts.audit_no_alerts_no_trades.get_signals') as mock_signals:
            mock_signals.return_value = {"buy": True, "sell": False}
            
            with patch('scripts.audit_no_alerts_no_trades.resolve_strategy_profile') as mock_resolve:
                mock_resolve.return_value = (Mock(value="swing"), Mock(value="conservative"))
                
                result = analyze_symbol(
                    "ETH_USDT",
                    item,
                    mock_db,
                    now_utc
                )
                
                assert result["alert_reason"] == SKIP_ALERT_DISABLED
                assert result["alert_blocked_by"] == SKIP_ALERT_DISABLED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

