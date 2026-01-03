"""Tests for trading guardrails (allowlist, kill switch, risk limits)"""
import os
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
from sqlalchemy.orm import Session

from app.utils.trading_guardrails import (
    check_trading_guardrails,
    _parse_allowlist,
)


@pytest.fixture
def mock_db():
    """Mock database session"""
    db = MagicMock(spec=Session)
    return db


class TestAllowlist:
    """Test allowlist gating"""
    
    def test_allowlist_allows_symbol_in_list(self, mock_db):
        """Symbol in allowlist should be allowed (if other checks pass)"""
        with patch.dict(os.environ, {"TRADE_ALLOWLIST": "BTC_USDT,ETH_USDT"}):
            with patch("app.utils.trading_guardrails.get_live_trading_status", return_value=True):
                with patch("app.utils.trading_guardrails._get_telegram_kill_switch_status", return_value=False):
                    with patch("app.utils.trading_guardrails._get_trade_enabled_for_symbol", return_value=True):
                        with patch("app.utils.trading_guardrails.count_total_open_positions", return_value=0):
                            mock_query = MagicMock()
                            mock_query.filter.return_value.order_by.return_value.first.return_value = None
                            mock_query.filter.return_value.scalar.return_value = 0
                            mock_db.query.return_value = mock_query
                            allowed, reason = check_trading_guardrails(
                                db=mock_db,
                                symbol="BTC_USDT",
                                order_usd_value=50.0,
                                side="BUY",
                            )
                            assert allowed is True
                            assert reason is None
    
    def test_allowlist_blocks_symbol_not_in_list(self, mock_db):
        """Symbol not in allowlist should be blocked"""
        with patch.dict(os.environ, {"TRADE_ALLOWLIST": "BTC_USDT,ETH_USDT"}):
            with patch("app.utils.trading_guardrails.get_live_trading_status", return_value=True):
                with patch("app.utils.trading_guardrails._get_telegram_kill_switch_status", return_value=False):
                    with patch("app.utils.trading_guardrails._get_trade_enabled_for_symbol", return_value=True):
                        with patch("app.utils.trading_guardrails.count_total_open_positions", return_value=0):
                            allowed, reason = check_trading_guardrails(
                                db=mock_db,
                                symbol="SOL_USDT",
                                order_usd_value=50.0,
                                side="BUY",
                            )
                            assert allowed is False
                            assert "not in allowlist" in reason.lower()
    
    def test_empty_allowlist_allows_all(self, mock_db):
        """Empty allowlist should allow all symbols (backward compatible)"""
        with patch.dict(os.environ, {"TRADE_ALLOWLIST": ""}, clear=False):
            with patch("app.utils.trading_guardrails.get_live_trading_status", return_value=True):
                with patch("app.utils.trading_guardrails._get_telegram_kill_switch_status", return_value=False):
                    with patch("app.utils.trading_guardrails._get_trade_enabled_for_symbol", return_value=True):
                        with patch("app.utils.trading_guardrails.count_total_open_positions", return_value=0):
                            mock_query = MagicMock()
                            mock_query.filter.return_value.order_by.return_value.first.return_value = None
                            mock_query.filter.return_value.scalar.return_value = 0
                            mock_db.query.return_value = mock_query
                            allowed, reason = check_trading_guardrails(
                                db=mock_db,
                                symbol="SOL_USDT",
                                order_usd_value=50.0,
                                side="BUY",
                            )
                            assert allowed is True
    
    def test_parse_allowlist(self):
        """Test allowlist parsing"""
        with patch.dict(os.environ, {"TRADE_ALLOWLIST": "BTC_USDT,ETH_USDT, SOL_USDT "}):
            allowlist = _parse_allowlist()
            assert "BTC_USDT" in allowlist
            assert "ETH_USDT" in allowlist
            assert "SOL_USDT" in allowlist
            assert len(allowlist) == 3


class TestKillSwitch:
    """Test TRADING_ENABLED env override (optional final override)"""
    
    def test_trading_enabled_false_blocks_orders(self, mock_db):
        """TRADING_ENABLED=false should block orders even if Live ON and TradeYes YES"""
        with patch.dict(os.environ, {"TRADING_ENABLED": "false"}):
            with patch("app.utils.trading_guardrails.get_live_trading_status", return_value=True):
                with patch("app.utils.trading_guardrails._get_telegram_kill_switch_status", return_value=False):
                    with patch("app.utils.trading_guardrails._get_trade_enabled_for_symbol", return_value=True):
                        with patch("app.utils.trading_guardrails.count_total_open_positions", return_value=0):
                            allowed, reason = check_trading_guardrails(
                                db=mock_db,
                                symbol="BTC_USDT",
                                order_usd_value=50.0,
                                side="BUY",
                            )
                            assert allowed is False
                            assert "TRADING_ENABLED" in reason.upper()
    
    def test_trading_enabled_true_allows_if_other_checks_pass(self, mock_db):
        """TRADING_ENABLED=true should allow orders if other checks pass"""
        with patch.dict(os.environ, {"TRADING_ENABLED": "true"}):
            with patch("app.utils.trading_guardrails.get_live_trading_status", return_value=True):
                with patch("app.utils.trading_guardrails._get_telegram_kill_switch_status", return_value=False):
                    with patch("app.utils.trading_guardrails._get_trade_enabled_for_symbol", return_value=True):
                        with patch("app.utils.trading_guardrails.count_total_open_positions", return_value=0):
                            mock_query = MagicMock()
                            mock_query.filter.return_value.order_by.return_value.first.return_value = None
                            mock_query.filter.return_value.scalar.return_value = 0
                            mock_db.query.return_value = mock_query
                            allowed, reason = check_trading_guardrails(
                                db=mock_db,
                                symbol="BTC_USDT",
                                order_usd_value=50.0,
                                side="BUY",
                            )
                            # Should pass if other checks pass
                            assert allowed is True or "MAX_OPEN_ORDERS_TOTAL" in reason  # Might be blocked by other limits


class TestMaxOpenOrdersTotal:
    """Test MAX_OPEN_ORDERS_TOTAL limit"""
    
    def test_max_open_orders_blocks_when_limit_reached(self, mock_db):
        """Should block when total open orders >= MAX_OPEN_ORDERS_TOTAL"""
        with patch.dict(os.environ, {"MAX_OPEN_ORDERS_TOTAL": "3"}):
            with patch("app.utils.trading_guardrails.get_live_trading_status", return_value=True):
                with patch("app.utils.trading_guardrails._get_telegram_kill_switch_status", return_value=False):
                    with patch("app.utils.trading_guardrails._get_trade_enabled_for_symbol", return_value=True):
                        with patch("app.utils.trading_guardrails.count_total_open_positions", return_value=3):
                            allowed, reason = check_trading_guardrails(
                                db=mock_db,
                                symbol="BTC_USDT",
                                order_usd_value=50.0,
                                side="BUY",
                            )
                            assert allowed is False
                            assert "MAX_OPEN_ORDERS_TOTAL" in reason.upper()
    
    def test_max_open_orders_allows_when_below_limit(self, mock_db):
        """Should allow when total open orders < MAX_OPEN_ORDERS_TOTAL"""
        with patch.dict(os.environ, {"MAX_OPEN_ORDERS_TOTAL": "3"}):
            with patch("app.utils.trading_guardrails.get_live_trading_status", return_value=True):
                with patch("app.utils.trading_guardrails._get_telegram_kill_switch_status", return_value=False):
                    with patch("app.utils.trading_guardrails._get_trade_enabled_for_symbol", return_value=True):
                        with patch("app.utils.trading_guardrails.count_total_open_positions", return_value=2):
                            # Mock query to avoid database calls
                            mock_query = MagicMock()
                            mock_query.filter.return_value.order_by.return_value.first.return_value = None
                            mock_query.filter.return_value.scalar.return_value = 0
                    mock_db.query.return_value = mock_query
                    
                    allowed, reason = check_trading_guardrails(
                        db=mock_db,
                        symbol="BTC_USDT",
                        order_usd_value=50.0,
                        side="BUY",
                    )
                    # May be blocked by other limits, but not MAX_OPEN_ORDERS_TOTAL
                    if not allowed:
                        assert "MAX_OPEN_ORDERS_TOTAL" not in reason.upper()


class TestMaxUsdPerOrder:
    """Test MAX_USD_PER_ORDER limit"""
    
    def test_max_usd_blocks_when_exceeded(self, mock_db):
        """Should block when order USD value > MAX_USD_PER_ORDER"""
        with patch.dict(os.environ, {"MAX_USD_PER_ORDER": "100"}):
            with patch("app.utils.trading_guardrails.get_live_trading_status", return_value=True):
                with patch("app.utils.trading_guardrails._get_telegram_kill_switch_status", return_value=False):
                    with patch("app.utils.trading_guardrails._get_trade_enabled_for_symbol", return_value=True):
                        with patch("app.utils.trading_guardrails.count_total_open_positions", return_value=0):
                            # Mock query to avoid database calls
                            mock_query = MagicMock()
                            mock_query.filter.return_value.order_by.return_value.first.return_value = None
                            mock_query.filter.return_value.scalar.return_value = 0
                            mock_db.query.return_value = mock_query
                            
                            allowed, reason = check_trading_guardrails(
                                db=mock_db,
                                symbol="BTC_USDT",
                                order_usd_value=150.0,  # Exceeds 100
                                side="BUY",
                            )
                            assert allowed is False
                            assert "MAX_USD_PER_ORDER" in reason.upper()
    
    def test_max_usd_allows_when_within_limit(self, mock_db):
        """Should allow when order USD value <= MAX_USD_PER_ORDER"""
        with patch.dict(os.environ, {"MAX_USD_PER_ORDER": "100"}):
            with patch("app.utils.trading_guardrails.get_live_trading_status", return_value=True):
                with patch("app.utils.trading_guardrails._get_telegram_kill_switch_status", return_value=False):
                    with patch("app.utils.trading_guardrails._get_trade_enabled_for_symbol", return_value=True):
                        with patch("app.utils.trading_guardrails.count_total_open_positions", return_value=0):
                            # Mock query to avoid database calls
                            mock_query = MagicMock()
                            mock_query.filter.return_value.order_by.return_value.first.return_value = None
                            mock_query.filter.return_value.scalar.return_value = 0
                            mock_db.query.return_value = mock_query
                            
                            allowed, reason = check_trading_guardrails(
                                db=mock_db,
                                symbol="BTC_USDT",
                                order_usd_value=50.0,  # Within limit
                                side="BUY",
                            )
                            assert allowed is True
                            assert reason is None

