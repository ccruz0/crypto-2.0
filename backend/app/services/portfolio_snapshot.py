"""
Portfolio Snapshot Service
Fetches live portfolio data from Crypto.com Exchange and stores normalized snapshots.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from sqlalchemy.orm import Session
from sqlalchemy import Column, Integer, Float, String, DateTime, Text, JSON
from sqlalchemy.sql import func

from app.database import Base
from app.services.brokers.crypto_com_trade import trade_client
from app.services.portfolio_cache import get_crypto_prices, _normalize_currency_name

logger = logging.getLogger(__name__)

# Diagnostic logging flag
PORTFOLIO_SNAPSHOT_DEBUG = os.getenv("PORTFOLIO_SNAPSHOT_DEBUG", "0") == "1"


class PortfolioSnapshotData(Base):
    """Model for storing complete portfolio snapshots with assets array"""
    __tablename__ = "portfolio_snapshot_data"
    
    id = Column(Integer, primary_key=True, index=True)
    exchange = Column(String, default="Crypto.com Exchange", nullable=False)
    portfolio_value_source = Column(String, nullable=False)  # "crypto_com_live" | "db_snapshot" | "derived_*"
    assets_json = Column(JSON, nullable=True)  # Store assets array as JSON
    total_assets_usd = Column(Float, nullable=True)
    total_collateral_usd = Column(Float, nullable=True)
    total_borrowed_usd = Column(Float, nullable=True)
    total_value_usd = Column(Float, nullable=False)
    unpriced_count = Column(Integer, default=0)  # Count of assets without prices
    as_of = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    def __repr__(self):
        return f"<PortfolioSnapshotData(exchange={self.exchange}, source={self.portfolio_value_source}, total=${self.total_value_usd:,.2f}, as_of={self.as_of})>"


def _ensure_table_exists(db: Session):
    """Ensure portfolio_snapshot_data table exists"""
    try:
        from sqlalchemy import inspect
        inspector = inspect(db.bind)
        if "portfolio_snapshot_data" not in inspector.get_table_names():
            logger.info("Creating portfolio_snapshot_data table...")
            PortfolioSnapshotData.__table__.create(db.bind, checkfirst=True)
            db.commit()
            logger.info("✅ portfolio_snapshot_data table created")
    except Exception as e:
        logger.warning(f"Could not ensure table exists: {e}")


def fetch_live_portfolio_snapshot(db: Session) -> Dict[str, Any]:
    """
    Fetch live portfolio data from Crypto.com Exchange and return normalized snapshot.
    
    Returns:
        {
            "assets": [
                {
                    "symbol": "BTC",
                    "free": 0.5,
                    "locked": 0.0,
                    "total": 0.5,
                    "price_usd": 45000.0,
                    "value_usd": 22500.0
                },
                ...
            ],
            "total_assets_usd": ...,
            "total_collateral_usd": ...,
            "total_borrowed_usd": ...,
            "total_value_usd": ...,
            "portfolio_value_source": "crypto_com_live",
            "as_of": "2026-01-04T01:00:00Z",
            "unpriced_count": 0
        }
    
    Raises:
        ValueError: If API credentials are not configured
        RuntimeError: If API call fails
    """
    try:
        # Check if credentials are configured using resolver
        from app.utils.credential_resolver import resolve_crypto_credentials
        api_key, api_secret, used_pair_name, _ = resolve_crypto_credentials()
        
        if not api_key or not api_secret:
            error_msg = (
                "Crypto.com API credentials not configured. "
                "Set EXCHANGE_CUSTOM_API_KEY and EXCHANGE_CUSTOM_API_SECRET in environment."
            )
            logger.warning(f"[PORTFOLIO_SNAPSHOT] {error_msg}")
            raise ValueError(error_msg)
        
        # Update trade_client with resolved credentials if different
        # (Note: trade_client is a singleton, so we need to update it)
        if trade_client.api_key != api_key or trade_client.api_secret != api_secret:
            trade_client.api_key = api_key
            trade_client.api_secret = api_secret
        
        # Check proxy requirement
        use_proxy = os.getenv("USE_CRYPTO_PROXY", "false").lower() == "true"
        if use_proxy:
            logger.info("[PORTFOLIO_SNAPSHOT] USE_CRYPTO_PROXY=true, using proxy for Crypto.com API calls")
        
        # Fetch account summary from Crypto.com
        logger.info("[PORTFOLIO_SNAPSHOT] Fetching live portfolio data from Crypto.com Exchange...")
        try:
            account_data = trade_client.get_account_summary()
        except Exception as api_err:
            error_str = str(api_err)
            logger.error(f"[PORTFOLIO_SNAPSHOT] Failed to get account summary: {api_err}", exc_info=True)
            
            # Check for network/timeout errors
            if any(keyword in error_str.lower() for keyword in ['timeout', 'connection', 'dns', 'network', 'unreachable']):
                network_error = "network_error: " + error_str.split('\n')[0][:100]  # First 100 chars
                raise RuntimeError(f"Networking issue connecting to Crypto.com: {error_str}. Try USE_CRYPTO_PROXY=true or check VPN.")
            
            # Check for authentication errors
            if "40101" in error_str:
                raise RuntimeError(f"Crypto.com auth failed (40101): {error_str}")
            elif "40103" in error_str:
                raise RuntimeError(f"Crypto.com IP not whitelisted (40103): {error_str}")
            
            # Generic error
            raise RuntimeError(f"Failed to fetch account summary from Crypto.com: {error_str}")
        
        if not account_data:
            logger.error("[PORTFOLIO_SNAPSHOT] No data received from Crypto.com Exchange")
            raise RuntimeError("No data received from Crypto.com Exchange")
        
        # Debug: Log raw account_data structure (only in debug mode)
        if PORTFOLIO_SNAPSHOT_DEBUG:
            logger.debug(f"[PORTFOLIO_SNAPSHOT_DEBUG] account_data keys: {list(account_data.keys()) if isinstance(account_data, dict) else 'not a dict'}")
        
        # Extract accounts/balances
        accounts = []
        if "accounts" in account_data:
            accounts = account_data["accounts"]
        elif "result" in account_data:
            result = account_data["result"]
            if "accounts" in result:
                accounts = result["accounts"]
            elif "data" in result:
                # Handle position_balances format
                data = result["data"]
                if isinstance(data, list) and len(data) > 0:
                    position_data = data[0]
                    if "position_balances" in position_data:
                        for balance in position_data["position_balances"]:
                            instrument = balance.get("instrument_name", "")
                            quantity = float(balance.get("quantity", "0") or 0)
                            
                            # Extract currency from instrument_name
                            currency = _normalize_currency_name(instrument)
                            
                            if quantity > 0 and currency:
                                accounts.append({
                                    "currency": currency,
                                    "balance": str(quantity),
                                    "available": str(balance.get("max_withdrawal_balance", quantity))
                                })
        
        # Always log account count (helpful for debugging)
        logger.info(f"[PORTFOLIO_SNAPSHOT] Retrieved {len(accounts)} account balances from Crypto.com")
        if PORTFOLIO_SNAPSHOT_DEBUG and accounts:
            logger.debug(f"[PORTFOLIO_SNAPSHOT_DEBUG] Sample accounts: {accounts[:3]}")
        
        # Get current prices with fallback priority: Crypto.com → CoinGecko → 0 with error
        prices = {}
        price_sources = {}  # Track source for each price
        
        # Priority 1: Crypto.com public ticker
        try:
            crypto_com_prices = get_crypto_prices()
            for symbol, price in crypto_com_prices.items():
                if price and price > 0:
                    prices[symbol] = price
                    price_sources[symbol] = "crypto_com"
            logger.info(f"[PORTFOLIO_SNAPSHOT] Retrieved {len(prices)} prices from Crypto.com")
        except Exception as price_err:
            logger.warning(f"[PORTFOLIO_SNAPSHOT] Failed to get Crypto.com prices: {price_err}")
        
        # Priority 2: CoinGecko fallback for missing prices
        try:
            from simple_price_fetcher import SimplePriceFetcher
            price_fetcher = SimplePriceFetcher()
            
            # Find symbols that need prices
            missing_price_symbols = []
            for account in accounts:
                currency = _normalize_currency_name(account.get("currency", ""))
                if currency and currency not in prices:
                    missing_price_symbols.append(currency)
            
            if missing_price_symbols:
                logger.info(f"[PORTFOLIO_SNAPSHOT] Fetching {len(missing_price_symbols)} missing prices from CoinGecko...")
                for symbol in missing_price_symbols[:10]:  # Limit to 10 to avoid rate limits
                    try:
                        # Try with _USDT suffix first
                        result = price_fetcher.get_price(f"{symbol}_USDT")
                        if result and result.success and result.price > 0:
                            prices[symbol] = result.price
                            price_sources[symbol] = "coingecko"
                        else:
                            # Try without suffix
                            result = price_fetcher.get_price(symbol)
                            if result and result.success and result.price > 0:
                                prices[symbol] = result.price
                                price_sources[symbol] = "coingecko"
                    except Exception as gecko_err:
                        logger.debug(f"[PORTFOLIO_SNAPSHOT] CoinGecko failed for {symbol}: {gecko_err}")
        except ImportError:
            logger.debug("[PORTFOLIO_SNAPSHOT] simple_price_fetcher not available, skipping CoinGecko fallback")
        except Exception as gecko_err:
            logger.warning(f"[PORTFOLIO_SNAPSHOT] CoinGecko fallback failed: {gecko_err}")
        
        if PORTFOLIO_SNAPSHOT_DEBUG and prices:
            sample_symbols = list(prices.keys())[:5]
            logger.debug(f"[PORTFOLIO_SNAPSHOT_DEBUG] Sample prices: {[(s, prices[s], price_sources.get(s, 'unknown')) for s in sample_symbols]}")
        
        # Build assets array
        assets: List[Dict[str, Any]] = []
        total_assets_usd = 0.0
        unpriced_count = 0
        
        for account in accounts:
            currency = _normalize_currency_name(account.get("currency", ""))
            if not currency:
                continue
            
            # Parse balance values
            try:
                balance_str = account.get("balance", "0") or "0"
                available_str = account.get("available", balance_str) or balance_str
                free = float(available_str)
                locked = float(balance_str) - free
                total = float(balance_str)
            except (ValueError, TypeError):
                logger.warning(f"Could not parse balance for {currency}: {account}")
                continue
            
            # Skip zero balances
            if total <= 0:
                continue
            
            # Get price and source
            price_usd = prices.get(currency)
            source = price_sources.get(currency, "unknown")
            
            if price_usd is None:
                # Try with _USDT suffix
                price_usd = prices.get(f"{currency}_USDT")
                if price_usd:
                    source = price_sources.get(f"{currency}_USDT", source)
            
            # Calculate USD value
            value_usd = None
            if price_usd is not None and price_usd > 0:
                value_usd = total * price_usd
                total_assets_usd += value_usd
            else:
                unpriced_count += 1
                price_usd = 0.0
                source = "unpriced"
                if PORTFOLIO_SNAPSHOT_DEBUG:
                    logger.debug(f"[PORTFOLIO_SNAPSHOT_DEBUG] No price found for {currency}")
            
            assets.append({
                "symbol": currency,
                "coin": currency,  # Alias for compatibility
                "currency": currency,
                "free": free,
                "locked": locked,
                "total": total,
                "balance": total,  # Alias for compatibility
                "price_usd": price_usd,
                "value_usd": value_usd,
                "usd_value": value_usd,  # Alias for compatibility
                "source": source,  # Track price source
            })
        
        # Get margin equity if available (pre-computed NET balance from exchange)
        margin_equity = account_data.get("margin_equity")
        if margin_equity is None and "result" in account_data:
            result = account_data["result"]
            equity_fields = ["equity", "net_equity", "wallet_balance", "margin_equity", 
                           "total_equity", "available_equity", "account_equity", "balance_equity"]
            for field in equity_fields:
                if field in result:
                    try:
                        margin_equity = float(result[field])
                        break
                    except (ValueError, TypeError):
                        continue
        
        # Calculate totals
        # For now, we'll use total_assets_usd as collateral (no haircut in snapshot)
        # In production, this should come from exchange margin data
        total_collateral_usd = total_assets_usd
        total_borrowed_usd = 0.0  # Will be populated from loans if available
        
        # Try to get borrowed amount from loans
        try:
            from app.models.portfolio_loan import PortfolioLoan
            loans = db.query(PortfolioLoan).filter(
                PortfolioLoan.is_active == True
            ).all()
            total_borrowed_usd = sum(float(loan.borrowed_usd_value or 0) for loan in loans)
        except Exception as e:
            logger.debug(f"Could not fetch loans: {e}")
        
        # Calculate total value
        if margin_equity is not None:
            total_value_usd = float(margin_equity)
            portfolio_value_source = "crypto_com_live"
        else:
            # Fallback: assets - borrowed
            total_value_usd = total_collateral_usd - total_borrowed_usd
            portfolio_value_source = "crypto_com_live_derived"
        
        snapshot = {
            "assets": assets,
            "total_assets_usd": total_assets_usd,
            "total_collateral_usd": total_collateral_usd,
            "total_borrowed_usd": total_borrowed_usd,
            "total_value_usd": total_value_usd,
            "portfolio_value_source": portfolio_value_source,
            "as_of": datetime.now(timezone.utc).isoformat(),
            "unpriced_count": unpriced_count,
            "exchange": "Crypto.com Exchange"
        }
        
        # Always log snapshot summary (helpful for debugging)
        logger.info(f"[PORTFOLIO_SNAPSHOT] Snapshot created: {len(assets)} assets, "
                   f"total=${total_value_usd:,.2f}, source={portfolio_value_source}, "
                   f"unpriced={unpriced_count}")
        if PORTFOLIO_SNAPSHOT_DEBUG and assets:
            logger.debug(f"[PORTFOLIO_SNAPSHOT_DEBUG] Sample assets: {assets[:3]}")
        
        # Warn if no assets found
        if len(assets) == 0:
            logger.warning(f"[PORTFOLIO_SNAPSHOT] ⚠️ No assets found in snapshot. "
                          f"Accounts received: {len(accounts)}, prices available: {len(prices)}")
            if len(accounts) == 0:
                logger.warning(f"[PORTFOLIO_SNAPSHOT] ⚠️ No accounts extracted from account_data. "
                              f"Check account_data structure and extraction logic.")
        
        return snapshot
    
    except ValueError as e:
        # Credentials not configured - return error info
        logger.warning(f"Cannot fetch live portfolio: {e}")
        raise
    except RuntimeError as e:
        # Re-raise RuntimeError as-is (already has proper error message)
        raise
    except Exception as e:
        logger.error(f"Error fetching live portfolio snapshot: {e}", exc_info=True)
        # Make sure we don't reference any variables that might not be defined
        error_msg = str(e) if e else "Unknown error"
        raise RuntimeError(f"Failed to fetch portfolio from Crypto.com: {error_msg}")


def store_portfolio_snapshot(db: Session, snapshot: Dict[str, Any]) -> PortfolioSnapshotData:
    """
    Store portfolio snapshot in database.
    
    Returns:
        PortfolioSnapshotData instance
    """
    _ensure_table_exists(db)
    
    try:
        # Parse as_of timestamp
        as_of_str = snapshot.get("as_of")
        if isinstance(as_of_str, str):
            as_of = datetime.fromisoformat(as_of_str.replace("Z", "+00:00"))
        else:
            as_of = datetime.now(timezone.utc)
        
        # Create snapshot record
        snapshot_record = PortfolioSnapshotData(
            exchange=snapshot.get("exchange", "Crypto.com Exchange"),
            portfolio_value_source=snapshot.get("portfolio_value_source", "crypto_com_live"),
            assets_json=snapshot.get("assets", []),
            total_assets_usd=snapshot.get("total_assets_usd"),
            total_collateral_usd=snapshot.get("total_collateral_usd"),
            total_borrowed_usd=snapshot.get("total_borrowed_usd"),
            total_value_usd=snapshot.get("total_value_usd", 0.0),
            unpriced_count=snapshot.get("unpriced_count", 0),
            as_of=as_of
        )
        
        db.add(snapshot_record)
        db.commit()
        db.refresh(snapshot_record)
        
        logger.info(f"✅ Portfolio snapshot stored: {len(snapshot.get('assets', []))} assets, "
                   f"total=${snapshot.get('total_value_usd', 0):,.2f}")
        
        return snapshot_record
    
    except Exception as e:
        db.rollback()
        logger.error(f"Error storing portfolio snapshot: {e}", exc_info=True)
        raise


def get_latest_portfolio_snapshot(db: Session, max_age_minutes: int = 5) -> Optional[Dict[str, Any]]:
    """
    Get latest portfolio snapshot from database if it's fresh (< max_age_minutes).
    
    Returns:
        Snapshot dict if fresh, None otherwise
    """
    _ensure_table_exists(db)
    
    try:
        from datetime import timedelta
        
        snapshot = db.query(PortfolioSnapshotData).order_by(
            PortfolioSnapshotData.as_of.desc()
        ).first()
        
        if not snapshot:
            return None
        
        # Check if snapshot is fresh
        age = datetime.now(timezone.utc) - snapshot.as_of.replace(tzinfo=timezone.utc)
        if age > timedelta(minutes=max_age_minutes):
            if PORTFOLIO_SNAPSHOT_DEBUG:
                logger.debug(f"Snapshot is stale: {age.total_seconds() / 60:.1f} minutes old")
            return None
        
        # Convert to dict
        return {
            "assets": snapshot.assets_json or [],
            "total_assets_usd": snapshot.total_assets_usd,
            "total_collateral_usd": snapshot.total_collateral_usd,
            "total_borrowed_usd": snapshot.total_borrowed_usd,
            "total_value_usd": snapshot.total_value_usd,
            "portfolio_value_source": snapshot.portfolio_value_source,
            "as_of": snapshot.as_of.isoformat(),
            "unpriced_count": snapshot.unpriced_count or 0,
            "exchange": snapshot.exchange
        }
    
    except Exception as e:
        logger.warning(f"Error getting latest snapshot: {e}")
        return None

