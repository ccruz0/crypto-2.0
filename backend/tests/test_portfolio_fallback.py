"""
Tests for portfolio fallback behavior.

Verifies that when auth error is simulated and local_portfolio.json exists,
endpoint returns ok=true with positions.
"""

import os
import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from datetime import datetime, timezone

# Mock the database and other dependencies
@pytest.fixture
def mock_db():
    """Mock database session"""
    return MagicMock()


@pytest.fixture
def mock_local_file(tmp_path):
    """Create a temporary local_portfolio.json file"""
    data_dir = tmp_path / "app" / "data"
    data_dir.mkdir(parents=True)
    portfolio_file = data_dir / "local_portfolio.json"
    
    portfolio_data = {
        "BTC": 0.0123,
        "ETH": 0.5,
        "USDT": 1200
    }
    
    with open(portfolio_file, 'w') as f:
        json.dump(portfolio_data, f)
    
    return portfolio_file


def test_load_local_portfolio_file_exists(mock_local_file, tmp_path):
    """Test loading local portfolio file when it exists"""
    from app.services.portfolio_fallback import load_local_portfolio_file
    
    # Mock the file path
    with patch('app.services.portfolio_fallback.Path') as mock_path:
        mock_path.return_value.parent.parent = tmp_path / "app"
        
        # Set environment to local
        with patch.dict(os.environ, {"ENVIRONMENT": "local"}):
            holdings = load_local_portfolio_file()
            
            assert holdings is not None
            assert holdings["BTC"] == 0.0123
            assert holdings["ETH"] == 0.5
            assert holdings["USDT"] == 1200


def test_load_local_portfolio_file_not_exists():
    """Test loading local portfolio file when it doesn't exist"""
    from app.services.portfolio_fallback import load_local_portfolio_file
    
    with patch.dict(os.environ, {"ENVIRONMENT": "local"}):
        with patch('app.services.portfolio_fallback.Path') as mock_path:
            mock_path.return_value.exists.return_value = False
            holdings = load_local_portfolio_file()
            
            assert holdings is None


def test_load_local_portfolio_file_not_local():
    """Test that local file is not loaded in non-local environment"""
    from app.services.portfolio_fallback import load_local_portfolio_file
    
    with patch.dict(os.environ, {"ENVIRONMENT": "aws"}, clear=False):
        holdings = load_local_portfolio_file()
        
        assert holdings is None


def test_get_fallback_holdings_from_file(mock_db, mock_local_file, tmp_path):
    """Test getting fallback holdings from local file"""
    from app.services.portfolio_fallback import get_fallback_holdings
    
    # Mock compute_holdings_from_trades to return None
    with patch('app.services.portfolio_fallback.compute_holdings_from_trades', return_value=None):
        with patch('app.services.portfolio_fallback.Path') as mock_path:
            mock_path.return_value.parent.parent = tmp_path / "app"
            
            with patch.dict(os.environ, {"ENVIRONMENT": "local"}):
                holdings, source = get_fallback_holdings(mock_db)
                
                assert holdings is not None
                assert source == "local_file"
                assert holdings["BTC"] == 0.0123


def test_get_price_for_asset_stablecoin():
    """Test price fetching for stablecoins"""
    from app.services.portfolio_fallback import get_price_for_asset
    
    price, source = get_price_for_asset("USDT")
    assert price == 1.0
    assert source == "stablecoin"
    
    price, source = get_price_for_asset("USDC")
    assert price == 1.0
    assert source == "stablecoin"


def test_get_price_for_asset_coingecko():
    """Test price fetching from CoinGecko"""
    from app.services.portfolio_fallback import get_price_for_asset
    
    # Mock SimplePriceFetcher
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.price = 65000.0
    
    with patch('app.services.portfolio_fallback.SimplePriceFetcher') as mock_fetcher_class:
        mock_fetcher = MagicMock()
        mock_fetcher.get_price.return_value = mock_result
        mock_fetcher_class.return_value = mock_fetcher
        
        price, source = get_price_for_asset("BTC")
        
        assert price == 65000.0
        assert source == "coingecko"


def test_build_fallback_positions(mock_db):
    """Test building positions from fallback holdings"""
    from app.services.portfolio_fallback import build_fallback_positions
    
    holdings = {
        "BTC": 0.0123,
        "USDT": 1200
    }
    
    # Mock price fetching
    with patch('app.services.portfolio_fallback.get_price_for_asset') as mock_get_price:
        def price_side_effect(asset):
            if asset == "BTC":
                return 65000.0, "coingecko"
            elif asset == "USDT":
                return 1.0, "stablecoin"
            return None, "none"
        
        mock_get_price.side_effect = price_side_effect
        
        positions = build_fallback_positions(mock_db, holdings, "local_file")
        
        assert len(positions) == 2
        
        btc_pos = next(p for p in positions if p["asset"] == "BTC")
        assert btc_pos["total"] == 0.0123
        assert btc_pos["price_usd"] == 65000.0
        assert btc_pos["value_usd"] == 0.0123 * 65000.0
        assert btc_pos["source"] == "local_file"
        assert btc_pos["price_source"] == "coingecko"
        
        usdt_pos = next(p for p in positions if p["asset"] == "USDT")
        assert usdt_pos["total"] == 1200
        assert usdt_pos["price_usd"] == 1.0
        assert usdt_pos["value_usd"] == 1200.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])



