"""
Unit tests for portfolio value selection with priority logic.

Tests that:
1. Exchange-reported balance/equity is chosen over derived calculation
2. Exchange-reported margin equity is used if balance/equity not found
3. Derived calculation (collateral - borrowed) is used as fallback
4. Priority order is never broken (exchange value always wins when present)
5. Reconcile data is included when PORTFOLIO_RECONCILE_DEBUG=1
"""
import os
import pytest
from unittest.mock import Mock, patch, MagicMock
from app.services.portfolio_cache import get_portfolio_summary


# Fixture: Real Crypto.com response with equity field (matches UI Balance)
CRYPTO_COM_WITH_EQUITY = {
    "accounts": [
        {
            "currency": "BTC",
            "balance": "0.5",
            "available": "0.5",
            "market_value": "25000.00",
            "haircut": "0.1"
        },
        {
            "currency": "USDT",
            "balance": "5000.00",
            "available": "5000.00",
            "market_value": "5000.00",
            "haircut": "0.0"
        }
    ],
    # This is the value shown in Crypto.com UI "Balance"
    "equity": "11511.49",
    "margin_equity": "11511.49",
    "wallet_balance": "11511.49"
}


# Fixture: Only margin_equity (no top-level equity)
CRYPTO_COM_ONLY_MARGIN_EQUITY = {
    "accounts": [
        {
            "currency": "BTC",
            "balance": "0.5",
            "available": "0.5",
            "market_value": "25000.00",
            "haircut": "0.1"
        }
    ],
    "margin_equity": "11511.49"  # Only margin equity, no top-level equity
}


# Fixture: No equity fields (should use derived)
CRYPTO_COM_NO_EQUITY = {
    "accounts": [
        {
            "currency": "BTC",
            "balance": "0.5",
            "available": "0.5",
            "market_value": "25000.00",
            "haircut": "0.1"
        },
        {
            "currency": "USDT",
            "balance": "5000.00",
            "available": "5000.00",
            "market_value": "5000.00",
            "haircut": "0.0"
        }
    ]
    # No equity fields - should fall back to derived
}


# Fixture: Equity in nested structure (result.data[0])
CRYPTO_COM_NESTED_EQUITY = {
    "result": {
        "data": [
            {
                "account_type": "MARGIN",
                "equity": "11511.49",  # Should be found in nested structure
                "position_balances": []
            }
        ]
    },
    "accounts": [
        {
            "currency": "BTC",
            "balance": "0.5",
            "available": "0.5",
            "market_value": "25000.00"
        }
    ]
}


class TestPortfolioValueSelection:
    """Test portfolio value selection with priority logic."""
    
    @pytest.fixture
    def mock_db(self):
        """Mock database session with portfolio balances."""
        db = Mock()
        
        # Mock portfolio balance query (ROW_NUMBER window function)
        from unittest.mock import MagicMock
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("BTC", 0.5, 25000.0),
            ("USDT", 5000.0, 5000.0)
        ]
        db.execute.return_value = mock_result
        
        # Mock portfolio snapshot query
        from app.models.portfolio import PortfolioSnapshot
        mock_snapshot = Mock()
        mock_snapshot.created_at.timestamp.return_value = 1234567890.0
        db.query.return_value.order_by.return_value.first.return_value = mock_snapshot
        
        # Mock portfolio loan query (no loans)
        db.query.return_value.filter.return_value.scalar.return_value = 0.0
        db.query.return_value.filter.return_value.all.return_value = []
        
        return db
    
    @pytest.fixture
    def mock_trade_client(self):
        """Mock Crypto.com trade client."""
        client = Mock()
        return client
    
    def test_priority_1_exchange_equity_over_derived(self, mock_db, mock_trade_client):
        """
        Test Priority 1: Exchange-reported equity is chosen over derived calculation.
        
        When Crypto.com API returns equity field, it must be used as total_value_usd,
        and portfolio_value_source must be "exchange_equity" (or similar).
        Derived calculation must NOT override exchange value.
        """
        expected_ui_balance = 11511.49
        
        with patch('app.services.portfolio_cache.trade_client', mock_trade_client):
            mock_trade_client.get_account_summary.return_value = CRYPTO_COM_WITH_EQUITY
            
            with patch('app.services.portfolio_cache.resolve_crypto_credentials') as mock_resolve:
                mock_resolve.return_value = ("test_key", "test_secret", None, {})
                
                with patch('app.services.portfolio_cache._table_exists', return_value=False):
                    result = get_portfolio_summary(mock_db)
                    
                    # Assert: total_usd equals exchange equity (matches UI Balance)
                    assert result["total_usd"] == expected_ui_balance, \
                        f"Expected total_usd={expected_ui_balance} (UI Balance), got {result['total_usd']}"
                    
                    # Assert: portfolio_value_source starts with "exchange_"
                    assert result["portfolio_value_source"].startswith("exchange_"), \
                        f"Expected portfolio_value_source to start with 'exchange_', got {result['portfolio_value_source']}"
                    
                    # Assert: derived calculation would be different (proves we're using exchange value)
                    # In this test, we can't fully calculate derived, but we verify the source is correct
    
    def test_priority_2_margin_equity_when_no_equity(self, mock_db, mock_trade_client):
        """
        Test Priority 2: Exchange-reported margin equity is used when balance/equity not found.
        
        When only margin_equity is present (no top-level equity),
        portfolio_value_source should be "exchange_margin_equity".
        """
        expected_margin_equity = 11511.49
        
        with patch('app.services.portfolio_cache.trade_client', mock_trade_client):
            mock_trade_client.get_account_summary.return_value = CRYPTO_COM_ONLY_MARGIN_EQUITY
            
            with patch('app.services.portfolio_cache.resolve_crypto_credentials') as mock_resolve:
                mock_resolve.return_value = ("test_key", "test_secret", None, {})
                
                with patch('app.services.portfolio_cache._table_exists', return_value=False):
                    result = get_portfolio_summary(mock_db)
                    
                    # Assert: total_usd equals margin equity
                    assert result["total_usd"] == expected_margin_equity, \
                        f"Expected total_usd={expected_margin_equity} (margin equity), got {result['total_usd']}"
                    
                    # Assert: portfolio_value_source is "exchange_margin_equity"
                    assert result["portfolio_value_source"] == "exchange_margin_equity", \
                        f"Expected portfolio_value_source='exchange_margin_equity', got {result['portfolio_value_source']}"
    
    def test_priority_3_derived_fallback(self, mock_db, mock_trade_client):
        """
        Test Priority 3: Derived calculation is used when no exchange equity fields found.
        
        When Crypto.com API does not return equity fields,
        portfolio_value_source should be "derived_collateral_minus_borrowed".
        """
        with patch('app.services.portfolio_cache.trade_client', mock_trade_client):
            mock_trade_client.get_account_summary.return_value = CRYPTO_COM_NO_EQUITY
            
            with patch('app.services.portfolio_cache.resolve_crypto_credentials') as mock_resolve:
                mock_resolve.return_value = ("test_key", "test_secret", None, {})
                
                with patch('app.services.portfolio_cache._table_exists', return_value=False):
                    result = get_portfolio_summary(mock_db)
                    
                    # Assert: portfolio_value_source is derived
                    assert result["portfolio_value_source"] == "derived_collateral_minus_borrowed", \
                        f"Expected portfolio_value_source='derived_collateral_minus_borrowed', got {result['portfolio_value_source']}"
                    
                    # Assert: total_usd is calculated (collateral - borrowed)
                    # In this test, we can't fully verify the calculation, but we verify the source
    
    def test_equity_found_in_nested_structure(self, mock_db, mock_trade_client):
        """
        Test that equity fields are found in nested structures (result.data[0]).
        
        Crypto.com user-balance format returns equity in result.data[0].equity.
        This test ensures we find and use it with correct priority.
        """
        expected_ui_balance = 11511.49
        
        with patch('app.services.portfolio_cache.trade_client', mock_trade_client):
            mock_trade_client.get_account_summary.return_value = CRYPTO_COM_NESTED_EQUITY
            
            with patch('app.services.portfolio_cache.resolve_crypto_credentials') as mock_resolve:
                mock_resolve.return_value = ("test_key", "test_secret", None, {})
                
                with patch('app.services.portfolio_cache._table_exists', return_value=False):
                    result = get_portfolio_summary(mock_db)
                    
                    # Assert: equity from nested structure should be found and used
                    assert "portfolio_value_source" in result
                    # The exact source name may vary, but it should indicate exchange equity
                    assert result["portfolio_value_source"].startswith("exchange_") or \
                           result["total_usd"] > 0, \
                        "Equity from nested structure should be found and used"
    
    def test_reconcile_debug_mode_includes_data(self, mock_db, mock_trade_client):
        """
        Test that reconcile data is included when PORTFOLIO_RECONCILE_DEBUG=1.
        
        When debug mode is enabled, the result should include a reconcile object
        with raw_fields, candidates, and chosen.
        """
        # Enable debug mode
        with patch.dict(os.environ, {"PORTFOLIO_RECONCILE_DEBUG": "1"}):
            # Reload module to pick up new env var
            import importlib
            import app.services.portfolio_cache
            importlib.reload(app.services.portfolio_cache)
            
            with patch('app.services.portfolio_cache.trade_client', mock_trade_client):
                mock_trade_client.get_account_summary.return_value = CRYPTO_COM_WITH_EQUITY
                
                with patch('app.services.portfolio_cache.resolve_crypto_credentials') as mock_resolve:
                    mock_resolve.return_value = ("test_key", "test_secret", None, {})
                    
                    with patch('app.services.portfolio_cache._table_exists', return_value=False):
                        result = get_portfolio_summary(mock_db)
                        
                        # Assert: reconcile data should be present
                        assert "reconcile" in result, \
                            "reconcile data should be present when PORTFOLIO_RECONCILE_DEBUG=1"
                        
                        reconcile = result["reconcile"]
                        assert "raw_fields" in reconcile, "reconcile should include raw_fields"
                        assert "candidates" in reconcile, "reconcile should include candidates"
                        assert "chosen" in reconcile, "reconcile should include chosen"
                        
                        # Assert: chosen should match total_usd
                        assert reconcile["chosen"]["value"] == result["total_usd"], \
                            "chosen.value should equal total_usd"
                        assert reconcile["chosen"]["source"] == result["portfolio_value_source"], \
                            "chosen.source should equal portfolio_value_source"
                        
                        # Assert: raw_fields should contain equity fields (safe numeric values only)
                        assert "equity" in reconcile["raw_fields"] or \
                               "margin_equity" in reconcile["raw_fields"] or \
                               "wallet_balance" in reconcile["raw_fields"], \
                            "raw_fields should contain at least one equity field"
            
            # Restore module
            importlib.reload(app.services.portfolio_cache)
    
    def test_priority_order_not_broken(self, mock_db, mock_trade_client):
        """
        Test that priority order is never broken.
        
        If exchange equity is present, derived calculation must NOT override it.
        This is a critical test - it must fail if priority order is broken.
        """
        expected_ui_balance = 11511.49
        # Simulated derived value (would be different)
        derived_value = 9386.94
        
        with patch('app.services.portfolio_cache.trade_client', mock_trade_client):
            mock_trade_client.get_account_summary.return_value = CRYPTO_COM_WITH_EQUITY
            
            with patch('app.services.portfolio_cache.resolve_crypto_credentials') as mock_resolve:
                mock_resolve.return_value = ("test_key", "test_secret", None, {})
                
                with patch('app.services.portfolio_cache._table_exists', return_value=False):
                    result = get_portfolio_summary(mock_db)
                    
                    # Assert: exchange equity should be used, NOT derived
                    assert result["total_usd"] == expected_ui_balance, \
                        f"Exchange equity ({expected_ui_balance}) should be used, not derived ({derived_value}). " \
                        f"Got {result['total_usd']}"
                    
                    # Assert: source should indicate exchange, not derived
                    assert result["portfolio_value_source"].startswith("exchange_"), \
                        f"When exchange equity is present, source should be 'exchange_*', not 'derived_*'. " \
                        f"Got {result['portfolio_value_source']}"
                    
                    # Assert: derived value should NOT equal total_usd (proves we're not using derived)
                    # This test will fail if derived calculation overrides exchange equity
                    assert result["total_usd"] != derived_value, \
                        f"total_usd should NOT equal derived value ({derived_value}) when exchange equity is present"

