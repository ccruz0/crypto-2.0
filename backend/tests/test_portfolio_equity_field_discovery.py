"""
Tests for portfolio equity field discovery, including camelCase and override behavior.
"""

import pytest
import os
from unittest.mock import patch, MagicMock
from app.services.portfolio_cache import get_portfolio_summary


def test_camelcase_field_discovery():
    """Test that camelCase fields are discovered correctly."""
    # Mock API response with camelCase fields
    mock_response = {
        "result": {
            "data": [{
                "walletBalanceAfterHaircut": 12345.67,
                "marginEquity": 12000.00,
                "netEquity": 11500.00
            }]
        }
    }
    
    with patch("app.services.portfolio_cache.trade_client") as mock_client:
        mock_client.get_account_summary.return_value = mock_response
        mock_client.api_key = "test_key"
        mock_client.api_secret = "test_secret"
        
        # Mock database session
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.execute.return_value.fetchall.return_value = []
        
        # Enable reconcile debug
        with patch.dict(os.environ, {"PORTFOLIO_RECONCILE_DEBUG": "1"}):
            result = get_portfolio_summary(mock_db, request_context={"reconcile_debug": True})
            
            # Check that camelCase fields are in raw_fields
            reconcile = result.get("reconcile", {})
            raw_fields = reconcile.get("raw_fields", {})
            
            # Should find camelCase fields
            assert any("walletBalanceAfterHaircut" in k or "wallet_balance_after_haircut" in k.lower() for k in raw_fields.keys()), \
                "camelCase walletBalanceAfterHaircut should be discovered"
            assert any("marginEquity" in k or "margin_equity" in k.lower() for k in raw_fields.keys()), \
                "camelCase marginEquity should be discovered"


def test_after_haircut_priority():
    """Test that after_haircut fields have priority 0."""
    # Mock API response with multiple equity fields
    mock_response = {
        "wallet_balance_after_haircut": 12345.67,
        "wallet_balance": 12000.00,
        "equity": 11500.00,
        "margin_equity": 11000.00
    }
    
    with patch("app.services.portfolio_cache.trade_client") as mock_client:
        mock_client.get_account_summary.return_value = mock_response
        mock_client.api_key = "test_key"
        mock_client.api_secret = "test_secret"
        
        # Mock database session
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.execute.return_value.fetchall.return_value = []
        
        # Enable reconcile debug
        with patch.dict(os.environ, {"PORTFOLIO_RECONCILE_DEBUG": "1"}):
            result = get_portfolio_summary(mock_db, request_context={"reconcile_debug": True})
            
            # Check that after_haircut field is chosen
            portfolio_value_source = result.get("portfolio_value_source", "")
            assert portfolio_value_source.startswith("exchange:"), \
                "Should use exchange-reported field"
            assert "after_haircut" in portfolio_value_source.lower() or "afterHaircut" in portfolio_value_source, \
                "Should prioritize after_haircut field"
            
            # Check priority in reconcile.chosen
            reconcile = result.get("reconcile", {})
            chosen = reconcile.get("chosen", {})
            assert chosen.get("priority") == 0, \
                "after_haircut fields should have priority 0"


def test_override_behavior():
    """Test PORTFOLIO_EQUITY_FIELD_OVERRIDE behavior."""
    # Mock API response
    mock_response = {
        "result": {
            "data": [{
                "wallet_balance_after_haircut": 12345.67,
                "margin_equity": 12000.00,
                "custom_equity_field": 15000.00
            }]
        }
    }
    
    with patch("app.services.portfolio_cache.trade_client") as mock_client:
        mock_client.get_account_summary.return_value = mock_response
        mock_client.api_key = "test_key"
        mock_client.api_secret = "test_secret"
        
        # Mock database session
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.execute.return_value.fetchall.return_value = []
        
        # Test override with matching field
        with patch.dict(os.environ, {
            "PORTFOLIO_RECONCILE_DEBUG": "1",
            "PORTFOLIO_EQUITY_FIELD_OVERRIDE": "custom_equity_field"
        }):
            result = get_portfolio_summary(mock_db, request_context={"reconcile_debug": True})
            
            portfolio_value_source = result.get("portfolio_value_source", "")
            assert "custom_equity_field" in portfolio_value_source, \
                "Override should select custom_equity_field"
            assert result.get("total_value_usd") == 15000.00, \
                "Should use override field value"
        
        # Test override with non-matching field
        with patch.dict(os.environ, {
            "PORTFOLIO_RECONCILE_DEBUG": "1",
            "PORTFOLIO_EQUITY_FIELD_OVERRIDE": "nonexistent_field"
        }):
            result = get_portfolio_summary(mock_db, request_context={"reconcile_debug": True})
            
            reconcile = result.get("reconcile", {})
            chosen = reconcile.get("chosen", {})
            assert "error" in chosen, \
                "Should include error when override field not found"
            # Should fall back to normal priority
            assert result.get("portfolio_value_source", "").startswith("exchange:"), \
                "Should fall back to normal priority selection"

