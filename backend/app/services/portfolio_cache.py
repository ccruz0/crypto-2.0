"""Service for caching portfolio data in the database"""
import logging
import os
from sqlalchemy.orm import Session
from app.models.portfolio import PortfolioBalance, PortfolioSnapshot
from app.services.brokers.crypto_com_trade import trade_client
from app.utils.http_client import http_get
import time
from typing import List, Dict, Optional
import threading
from functools import lru_cache

logger = logging.getLogger(__name__)

# Diagnostic logging flag (set PORTFOLIO_DEBUG=1 to enable)
PORTFOLIO_DEBUG = os.getenv("PORTFOLIO_DEBUG", "0") == "1"

# Reconciliation debug mode (set PORTFOLIO_RECONCILE_DEBUG=1 to enable)
# When enabled, includes reconciliation bundle in portfolio response showing all candidate values
# Can also be enabled via request context (for SSM/local debugging only)
PORTFOLIO_RECONCILE_DEBUG = os.getenv("PORTFOLIO_RECONCILE_DEBUG", "0") == "1"
reconcile_debug_enabled = PORTFOLIO_RECONCILE_DEBUG  # Alias for backward compatibility

def _should_enable_reconcile_debug(request_context: Optional[Dict] = None) -> bool:
    """
    Determine if reconciliation debug should be enabled.
    
    Checks:
    1. reconcile_debug_enabled env var
    2. Request header X-Portfolio-Reconcile-Debug (only for local/SSM sessions)
    
    Args:
        request_context: Optional dict with 'headers' key for request headers
    
    Returns:
        bool: True if reconcile debug should be enabled
    """
    # Check env var first (preferred method)
    if PORTFOLIO_RECONCILE_DEBUG:
        return True
    
    # Check request context (header or query param) for local debugging via SSM
    if request_context and isinstance(request_context, dict):
        # Check query parameter first (easier for testing)
        if request_context.get("reconcile_debug") is True:
            runtime_origin = os.getenv("RUNTIME_ORIGIN", "").upper()
            environment = os.getenv("ENVIRONMENT", "").lower()
            if environment != "aws":  # Allow for non-AWS or unset
                logger.info("[RECONCILE_DEBUG] Enabled via query param (env=%s, origin=%s)", environment, runtime_origin)
                return True
        
        # Check request header (only for local debugging via SSM)
        headers = request_context.get("headers", {})
        if isinstance(headers, dict):
            # Check for header (case-insensitive, handle both dash and underscore)
            header_found = False
            header_value = None
            for key, value in headers.items():
                key_lower = key.lower().replace("-", "_")
                if key_lower == "x_portfolio_reconcile_debug":
                    header_found = True
                    header_value = str(value).lower()
                    break
            
            if header_found and header_value in ("1", "true", "yes"):
                # For SSM port-forward debugging, be more permissive
                # Check if we're in a safe environment (local dev or SSM port-forward)
                runtime_origin = os.getenv("RUNTIME_ORIGIN", "").upper()
                environment = os.getenv("ENVIRONMENT", "").lower()
                
                # Allow if explicitly local, or if runtime origin indicates local/SSM access
                if environment == "local" or runtime_origin in ("LOCAL", "SSM"):
                    logger.info("[RECONCILE_DEBUG] Enabled via header (safe environment: env=%s, origin=%s)", environment, runtime_origin)
                    return True
                
                # For SSM port-forward, allow if environment is not explicitly "aws" (safer default)
                # This allows debugging via SSM without requiring env var changes
                if environment != "aws":
                    logger.info("[RECONCILE_DEBUG] Enabled via header (non-AWS environment: env=%s, origin=%s)", environment, runtime_origin)
                    return True
                else:
                    logger.warning("[RECONCILE_DEBUG] Header present but blocked (AWS environment detected - use PORTFOLIO_RECONCILE_DEBUG=1 env var instead)")
    
    return False

# Cache for table existence checks (avoid repeated inspector calls)
_table_cache = {}
_table_cache_lock = threading.Lock()

# Request deduplication for portfolio updates
_update_lock = threading.Lock()
_last_update_time = 0
_last_update_result = None
_min_update_interval = 60  # Minimum seconds between cache updates


def _normalize_currency_name(value: Optional[str]) -> str:
    """
    Canonical currency key used across portfolio ingestion/storage/serialization.
    Ensures that BTC_USDT, btc-usd, etc. are all treated as BTC.
    """
    if not value:
        return ""
    normalized = value.strip().upper().replace("-", "_")
    if "_" in normalized:
        normalized = normalized.split("_")[0]
    return normalized


def _table_exists(db: Session, table_name: str) -> bool:
    """
    Check if a table exists, with caching to avoid repeated inspector calls.
    This significantly improves performance when called multiple times.
    """
    cache_key = f"{id(db.bind)}:{table_name}"
    
    with _table_cache_lock:
        if cache_key in _table_cache:
            return _table_cache[cache_key]
    
    try:
        from sqlalchemy import inspect
        inspector = inspect(db.bind)
        tables = inspector.get_table_names()
        exists = table_name in tables
        
        with _table_cache_lock:
            _table_cache[cache_key] = exists
        
        return exists
    except Exception as e:
        logger.debug(f"Error checking table existence for {table_name}: {e}")
        return False


def get_crypto_prices() -> Dict[str, float]:
    """Get current prices for major cryptocurrencies"""
    try:
        url = "https://api.crypto.com/exchange/v1/public/get-tickers"
        response = http_get(url, timeout=10, calling_module="portfolio_cache")
        response.raise_for_status()
        result = response.json()
        
        prices = {}
        if "result" in result and "data" in result["result"]:
            for ticker in result["result"]["data"]:
                instrument_name = ticker.get("i", "")
                last_price = float(ticker.get("a", 0))
                
                # Convert BTC_USDT -> BTC, SOL_USDT -> SOL, etc.
                if instrument_name.endswith("_USDT"):
                    currency = instrument_name.replace("_USDT", "")
                    prices[currency] = last_price
        
        return prices
    except Exception as e:
        logger.error(f"Error fetching prices: {e}")
        return {}


def update_portfolio_cache(db: Session) -> Dict:
    """
    Fetch fresh portfolio data from Crypto.com and update database cache
    Gets ALL available data from Crypto.com: balances, available, reserved, market values, etc.
    
    Includes request deduplication to prevent multiple concurrent updates.
    Includes authentication error handling to prevent repeated failed attempts.
    
    Returns:
        dict: Summary of the update operation with last_updated timestamp
    """
    global _last_update_time, _last_update_result
    
    # Request deduplication: Check if an update is already in progress or was recently completed
    current_time = time.time()
    with _update_lock:
        # If an update completed recently, return cached result
        if _last_update_result and (current_time - _last_update_time) < _min_update_interval:
            logger.debug(f"Skipping portfolio cache update - last update was {current_time - _last_update_time:.1f}s ago (min interval: {_min_update_interval}s)")
            return _last_update_result
        
        # Mark that we're starting an update
        _last_update_time = current_time
    
    try:
        logger.info("Starting portfolio cache update - fetching ALL data from Crypto.com...")
        
        # Update trade_client credentials using resolver (same as portfolio_snapshot)
        # This ensures we use the same credential resolution logic
        from app.utils.credential_resolver import resolve_crypto_credentials
        api_key, api_secret, used_pair_name, _ = resolve_crypto_credentials()
        
        if api_key and api_secret:
            # Update trade_client with resolved credentials if different
            if trade_client.api_key != api_key or trade_client.api_secret != api_secret:
                logger.debug(f"[PORTFOLIO_CACHE] Updating trade_client credentials from pair: {used_pair_name}")
                trade_client.api_key = api_key
                trade_client.api_secret = api_secret
        elif not api_key or not api_secret:
            logger.warning("[PORTFOLIO_CACHE] No credentials found via resolver, using trade_client defaults")
        
        # Fetch balance from Crypto.com (NO SIMULATED DATA)
        # Catch authentication errors specifically to provide better error messages
        try:
            balance_data = trade_client.get_account_summary()
        except Exception as auth_err:
            error_str = str(auth_err)
            # Check for authentication errors (40101, 40103)
            if "40101" in error_str or "40103" in error_str or "Authentication failure" in error_str or "Authentication failed" in error_str:
                # Extract error code for more specific messaging
                error_code = "40101" if "40101" in error_str else ("40103" if "40103" in error_str else "401")
                error_msg = f"Crypto.com API authentication failed: {error_str}"
                if error_code == "40101":
                    error_msg += " Possible causes: Invalid API key/secret, missing Read permission, or API key disabled. Check: 1) API credentials match Crypto.com Exchange exactly, 2) API key has 'Read' permission enabled, 3) API key is Active (not Disabled/Suspended)."
                elif error_code == "40103":
                    error_msg += " IP address not whitelisted. Add your server's IP to the IP whitelist in Crypto.com Exchange API Key settings."
                logger.error(error_msg)
                result = {
                    "success": False,
                    "error": error_msg,
                    "last_updated": None,
                    "auth_error": True,  # Flag to indicate this is an auth error
                    "error_code": error_code  # Include error code for better handling
                }
                with _update_lock:
                    _last_update_result = result
                return result
            # Re-raise other errors
            raise
        
        if not balance_data or "accounts" not in balance_data:
            logger.error("No balance data received from Crypto.com")
            return {"success": False, "last_updated": None, "error": "No balance data received"}
        
        # CRITICAL FIX: Use ONLY Crypto.com prices (no CoinGecko fallback)
        # Crypto.com Exchange UI uses market_value from API or Crypto.com ticker prices
        # Using external price sources (CoinGecko) causes mismatches with Crypto.com UI
        prices = get_crypto_prices()  # Gets prices from Crypto.com tickers API
        all_prices = prices  # Only use Crypto.com prices
        
        if PORTFOLIO_DEBUG:
            logger.info(f"[PORTFOLIO_DEBUG] Crypto.com ticker prices loaded: {len(prices)} symbols")
            for symbol, price in sorted(prices.items(), key=lambda x: x[1], reverse=True)[:10]:
                logger.info(f"[PORTFOLIO_DEBUG]   {symbol}: ${price:.8f}")
        
        # Diagnostic data structure for detailed logging
        diagnostic_data = [] if PORTFOLIO_DEBUG else None
        
        # Clear old balances
        db.query(PortfolioBalance).delete()
        
        # Calculate total portfolio value
        # Track both raw assets (for display) and collateral (after haircut, for Wallet Balance)
        total_usd = 0.0
        total_collateral_usd = 0.0
        balances_to_insert = []
        
        # Initialize asset breakdown list for debug output
        asset_breakdown = []
        
        logger.info(f"Processing {len(balance_data.get('accounts', []))} account balances from Crypto.com...")
        
        for account in balance_data.get("accounts", []):
            # Normalize every Crypto.com balance before storing so downstream aggregation sees one symbol per coin.
            currency = _normalize_currency_name(
                account.get("currency") or account.get("instrument_name") or account.get("symbol")
            )
            if not currency:
                logger.debug(f"Skipping account with no currency or symbol: {account}")
                continue
                
            balance = float(account.get("balance", 0))
            available = float(account.get("available", account.get("balance", 0)))
            reserved = float(account.get("reserved", balance - available))
            
            # Extract haircut from API response (for margin collateral calculation)
            # Crypto.com Margin Wallet Balance uses collateral = raw_value * (1 - haircut)
            # Check multiple possible field names
            haircut = 0.0
            haircut_raw = account.get("haircut") or account.get("collateral_ratio") or account.get("discount") or account.get("haircut_rate")
            if haircut_raw is not None:
                try:
                    if isinstance(haircut_raw, str):
                        # Handle "--" or empty strings as 0
                        haircut_str = haircut_raw.strip().replace("--", "").strip()
                        if haircut_str and haircut_str.lower() not in ["0", "0.0", "0.00"]:
                            haircut = float(haircut_str)
                    else:
                        haircut = float(haircut_raw)
                except (ValueError, TypeError):
                    haircut = 0.0
            
            # Stablecoins and USD should have 0 haircut (or use API value if provided)
            if currency in ["USD", "USDT", "USDC"]:
                haircut = 0.0
            
            # CRITICAL: Use market_value from Crypto.com API if available (matches Crypto.com UI exactly)
            # Crypto.com Exchange UI shows portfolio value using market_value from account summary
            # This is the source of truth - do NOT calculate from external prices if market_value exists
            market_value_from_api = account.get("market_value")
            price_source = None
            price_used = None
            
            if PORTFOLIO_DEBUG:
                logger.debug(f"[PORTFOLIO_DEBUG] Processing {currency}: balance={balance:.8f}, available={available:.8f}, reserved={reserved:.8f}, market_value_from_api={market_value_from_api}, haircut={haircut}")
            
            usd_value = 0.0
            
            # PRIORITY 1: Use market_value from Crypto.com API (matches Crypto.com UI exactly)
            if market_value_from_api:
                try:
                    # Handle both string and numeric formats
                    if isinstance(market_value_from_api, str):
                        # Remove any commas or whitespace
                        market_value_str = market_value_from_api.strip().replace(",", "").replace(" ", "")
                        # Only parse if not empty and not "0"
                        if market_value_str and market_value_str.lower() not in ["0", "0.0", "0.00", "0.000", "0.0000"]:
                            parsed_value = float(market_value_str)
                            if parsed_value > 0:
                                usd_value = parsed_value
                                price_source = "crypto_com_market_value"
                                price_used = None  # market_value is already USD, no price needed
                                logger.info(f"✅ Using market_value from Crypto.com API for {currency}: ${usd_value:.2f} (from string '{market_value_from_api}')")
                            else:
                                logger.debug(f"market_value parsed as 0 for {currency}, will calculate from prices")
                                usd_value = 0.0
                        else:
                            logger.debug(f"market_value is empty or '0' for {currency} ('{market_value_from_api}'), will calculate from prices")
                            usd_value = 0.0
                    else:
                        # Numeric format
                        parsed_value = float(market_value_from_api)
                        if parsed_value > 0:
                            usd_value = parsed_value
                            price_source = "crypto_com_market_value"
                            price_used = None  # market_value is already USD, no price needed
                            logger.info(f"✅ Using market_value from Crypto.com API for {currency}: ${usd_value:.2f} (from numeric {market_value_from_api})")
                        else:
                            logger.debug(f"market_value is 0 for {currency}, will calculate from prices")
                            usd_value = 0.0
                except (ValueError, TypeError) as e:
                    logger.warning(f"⚠️ Could not parse market_value '{market_value_from_api}' for {currency}: {e}, will calculate from prices")
                    usd_value = 0.0
            else:
                logger.debug(f"No market_value from API for {currency}, will calculate from prices")
            
            # PRIORITY 2: If no market_value, calculate using Crypto.com ticker prices ONLY
            # Do NOT use CoinGecko or other external sources - they cause mismatches with Crypto.com UI
            if usd_value == 0 or usd_value is None:
                logger.debug(f"Calculating USD value for {currency} from Crypto.com prices (balance: {balance:.8f})")
                if currency == "USDT" or currency == "USD" or currency == "USDC":
                    usd_value = balance
                    price_source = "stablecoin_1to1"
                    price_used = 1.0
                    logger.info(f"✅ {currency}: stablecoin, calculated USD value: ${usd_value:.2f}")
                elif currency in all_prices:
                    price = all_prices[currency]
                    price_source = "crypto_com_ticker_cache"
                    price_used = price
                    usd_value = balance * price
                    logger.info(f"✅ {currency}: calculated USD value from Crypto.com ticker ${price:.8f} × {balance:.8f} = ${usd_value:.2f}")
                else:
                    # Try Crypto.com API directly for this specific currency (USDT pair first, then USD)
                    price_found = False
                    
                    # Try Crypto.com API directly for this specific currency (USDT pair)
                    try:
                        ticker_url = f"https://api.crypto.com/exchange/v1/public/get-ticker?instrument_name={currency}_USDT"
                        ticker_response = http_get(ticker_url, timeout=5, calling_module="portfolio_cache")
                        if ticker_response.status_code == 200:
                            ticker_data = ticker_response.json()
                            if "result" in ticker_data and "data" in ticker_data["result"]:
                                ticker = ticker_data["result"]["data"]
                                price = float(ticker.get("a", 0))  # ask price
                                if price > 0:
                                    all_prices[currency] = price
                                    price_source = "crypto_com_ticker_api_usdt"
                                    price_used = price
                                    usd_value = balance * price
                                    logger.info(f"✅ Found price for {currency}: ${price:.8f} via Crypto.com API (USDT pair) → USD value: ${usd_value:.2f} (balance: {balance:.8f})")
                                    price_found = True
                                else:
                                    logger.debug(f"Price from Crypto.com API is 0 for {currency}_USDT")
                    except Exception as e:
                        logger.debug(f"Could not fetch price for {currency}_USDT from Crypto.com: {e}")
                    
                    # If USDT pair failed, try USD pair
                    if not price_found:
                        try:
                            ticker_url = f"https://api.crypto.com/exchange/v1/public/get-ticker?instrument_name={currency}_USD"
                            ticker_response = http_get(ticker_url, timeout=5, calling_module="portfolio_cache")
                            if ticker_response.status_code == 200:
                                ticker_data = ticker_response.json()
                                if "result" in ticker_data and "data" in ticker_data["result"]:
                                    ticker = ticker_data["result"]["data"]
                                    price = float(ticker.get("a", 0))  # ask price
                                    if price > 0:
                                        all_prices[currency] = price
                                        price_source = "crypto_com_ticker_api_usd"
                                        price_used = price
                                        usd_value = balance * price
                                        logger.info(f"✅ Found price for {currency}: ${price:.8f} via Crypto.com API (USD pair) → USD value: ${usd_value:.2f} (balance: {balance:.8f})")
                                        price_found = True
                                    else:
                                        logger.debug(f"Price from Crypto.com API is 0 for {currency}_USD")
                        except Exception as e:
                            logger.debug(f"Could not fetch price for {currency}_USD from Crypto.com: {e}")
                    
                    # CRITICAL: Do NOT use CoinGecko or other external sources
                    # Crypto.com UI only uses Crypto.com prices, so we must match that
                    if not price_found:
                        logger.warning(f"⚠️ Could not find Crypto.com price for {currency} - asset will have $0 USD value (may cause mismatch with Crypto.com UI)")
                        price_source = "not_found"
                        price_used = None
            
            # Only skip negative balances (debts/loans), but save zero balances
            # This ensures all assets are tracked even if balance is temporarily 0
            if balance < 0:
                logger.debug(f"Skipping {currency}: balance is negative (likely a loan/debt)")
                continue
            
            # For stablecoins, use balance as USD value if not already calculated
            # This check happens after all price calculations, so it's a final fallback
            if (usd_value == 0 or usd_value is None) and currency in ["USD", "USDT", "USDC"]:
                usd_value = balance
                logger.info(f"✅ {currency}: stablecoin fallback, using balance as USD value: ${usd_value:.2f}")
            
            # Calculate collateral value (after haircut) for margin Wallet Balance
            # collateral_value = raw_value * (1 - haircut)
            collateral_value = usd_value * (1 - haircut) if usd_value > 0 else 0.0
            
            # Store diagnostic data if enabled
            if PORTFOLIO_DEBUG and diagnostic_data is not None:
                diagnostic_data.append({
                    "symbol": currency,
                    "quantity": balance,
                    "price_used": price_used,
                    "price_source": price_source,
                    "computed_usd_value": usd_value,
                    "haircut": haircut,
                    "collateral_value": collateral_value,
                    "included": usd_value > 0,
                    "reason": "positive_usd_value" if usd_value > 0 else ("zero_balance" if balance == 0 else "no_price_found")
                })
            
            # Store asset breakdown data for verification (always track, log only if PORTFOLIO_DEBUG)
            if usd_value > 0:
                asset_breakdown.append({
                    "symbol": currency,
                    "quantity": balance,
                    "raw_value_usd": usd_value,
                    "haircut": haircut,
                    "collateral_value_usd": collateral_value
                })
            
            # Always save the balance to database, even if usd_value is 0 (might be updated later or price data missing)
            # This ensures we have a record of all balances
            # Track raw assets (for display) and collateral (for Wallet Balance calculation)
            if usd_value > 0:
                total_usd += usd_value  # Raw gross assets
                total_collateral_usd += collateral_value  # Collateral after haircut
                logger.info(f"✅ {currency}: balance={balance:.8f}, raw_value=${usd_value:.2f}, haircut={haircut:.4f}, collateral=${collateral_value:.2f} → added to totals")
            else:
                # Warn for non-stablecoins with balance > 0 but no USD value
                if currency not in ["USD", "USDT", "USDC"]:
                    logger.warning(f"⚠️ Could not calculate USD value for {currency} (balance: {balance:.8f}) - Crypto.com price not found (may cause mismatch with Crypto.com UI)")
                else:
                    logger.debug(f"{currency}: balance is 0, skipping USD calculation")
            
            # Create portfolio balance record with ALL available data
            # Always save, even if usd_value is 0 - this ensures we have records of all balances
            portfolio_balance = PortfolioBalance(
                currency=currency,
                balance=balance,
                usd_value=usd_value
            )
            balances_to_insert.append(portfolio_balance)
            
            # Log detailed information for each coin (including those with 0 USD value for debugging)
            if usd_value > 0:
                logger.info(f"💰 {currency}: balance={balance:.8f}, available={available:.8f}, reserved={reserved:.8f}, usd_value=${usd_value:.2f} → SAVED")
            else:
                logger.debug(f"💰 {currency}: balance={balance:.8f}, available={available:.8f}, reserved={reserved:.8f}, usd_value=$0.00 → SAVED (will be updated on next sync)")
        
        # Insert all balances
        db.bulk_save_objects(balances_to_insert)
        
        # Process loans/borrowed amounts from API
        # Look for negative balances or explicit loan fields in account data
        from app.models.portfolio_loan import PortfolioLoan
        loans_found = []
        
        for account in balance_data.get("accounts", []):
            currency = _normalize_currency_name(
                account.get("currency") or account.get("instrument_name") or account.get("symbol")
            )
            if not currency:
                continue
            
            # Check for explicit loan fields
            borrowed_balance = float(account.get("borrowed_balance", 0))
            borrowed_value = float(account.get("borrowed_value", 0))
            loan_amount = float(account.get("loan_amount", 0))
            loan_value = float(account.get("loan_value", 0))
            debt_amount = float(account.get("debt_amount", 0))
            debt_value = float(account.get("debt_value", 0))
            
            # Check for negative balance (indicates borrowed/loan)
            balance = float(account.get("balance", 0))
            is_negative = balance < 0
            
            # Determine if this is a loan
            has_loan = (borrowed_balance != 0 or borrowed_value != 0 or 
                       loan_amount != 0 or loan_value != 0 or 
                       debt_amount != 0 or debt_value != 0 or is_negative)
            
            if has_loan:
                # Calculate total borrowed amount
                total_borrowed = abs(borrowed_balance or loan_amount or debt_amount or balance)
                total_borrowed_usd = abs(borrowed_value or loan_value or debt_value)
                
                # If USD value not available, calculate it
                if total_borrowed_usd == 0 and total_borrowed > 0:
                    if currency in ["USD", "USDT", "USDC"]:
                        total_borrowed_usd = total_borrowed
                    elif currency in all_prices:
                        total_borrowed_usd = total_borrowed * all_prices[currency]
                
                if total_borrowed > 0:
                    logger.info(f"🔴 Found loan for {currency}: {total_borrowed:.8f} (${total_borrowed_usd:.2f})")
                    loans_found.append({
                        "currency": currency,
                        "borrowed_amount": total_borrowed,
                        "borrowed_usd_value": total_borrowed_usd
                    })
        
        # Update loans in database
        if loans_found:
            try:
                # Check if portfolio_loans table exists before using it (use cached check)
                if _table_exists(db, 'portfolio_loans'):
                    logger.info(f"Syncing {len(loans_found)} loans to database...")
                    
                    # Deactivate all existing loans for currencies we have data for
                    currencies_with_loans = [loan["currency"] for loan in loans_found]
                    db.query(PortfolioLoan).filter(
                        PortfolioLoan.currency.in_(currencies_with_loans)
                    ).update({"is_active": False}, synchronize_session=False)
                    
                    # Add new loans
                    for loan_data in loans_found:
                        new_loan = PortfolioLoan(
                            currency=loan_data["currency"],
                            borrowed_amount=loan_data["borrowed_amount"],
                            borrowed_usd_value=loan_data["borrowed_usd_value"],
                            notes="Auto-synced from Crypto.com",
                            is_active=True
                        )
                        db.add(new_loan)
                        logger.info(f"💰 Synced loan: {loan_data['currency']} ${loan_data['borrowed_usd_value']:.2f}")
                else:
                    logger.debug("portfolio_loans table does not exist, skipping loans sync")
            except Exception as loan_update_err:
                logger.warning(f"Could not update loans: {loan_update_err}")
        else:
            logger.info("No loans found in account data")
        
        # Create portfolio snapshot
        # Store both raw assets (for display) and collateral (for Wallet Balance calculation)
        # Note: PortfolioSnapshot.total_usd stores raw assets, we'll add collateral calculation in get_portfolio_summary
        snapshot = PortfolioSnapshot(total_usd=total_usd)
        db.add(snapshot)
        
        # Store total_collateral_usd in a way we can retrieve it
        # For now, we'll recalculate it in get_portfolio_summary from fresh API data
        # This ensures we always use current haircuts
        
        db.commit()
        
        last_updated = time.time()
        
        # Log diagnostic table if enabled
        if PORTFOLIO_DEBUG and diagnostic_data:
            logger.info(f"[PORTFOLIO_DEBUG] ========== PORTFOLIO VALUATION BREAKDOWN (with haircuts) ==========")
            logger.info(f"[PORTFOLIO_DEBUG] {'Symbol':<12} {'Quantity':<20} {'Price':<15} {'Price Source':<25} {'Raw USD':<12} {'Haircut':<10} {'Collateral':<12} {'Included':<10}")
            logger.info(f"[PORTFOLIO_DEBUG] {'-'*12} {'-'*20} {'-'*15} {'-'*25} {'-'*12} {'-'*10} {'-'*12} {'-'*10}")
            
            # Sort by USD value descending
            sorted_diag = sorted(diagnostic_data, key=lambda x: x["computed_usd_value"], reverse=True)
            for item in sorted_diag:
                price_str = f"${item['price_used']:.8f}" if item['price_used'] else "N/A"
                raw_val = item['computed_usd_value']
                haircut_val = item.get('haircut', 0.0)
                collateral_val = item.get('collateral_value', raw_val)
                logger.info(f"[PORTFOLIO_DEBUG] {item['symbol']:<12} {item['quantity']:<20.8f} {price_str:<15} {item['price_source']:<25} ${raw_val:<11.2f} {haircut_val:<9.4f} ${collateral_val:<11.2f} {'YES' if item['included'] else 'NO':<10}")
            
            logger.info(f"[PORTFOLIO_DEBUG] {'-'*12} {'-'*20} {'-'*15} {'-'*25} {'-'*12} {'-'*10} {'-'*12} {'-'*10}")
            logger.info(f"[PORTFOLIO_DEBUG] TOTAL RAW ASSETS USD: ${total_usd:,.2f}")
            logger.info(f"[PORTFOLIO_DEBUG] TOTAL COLLATERAL USD: ${total_collateral_usd:,.2f}")
            logger.info(f"[PORTFOLIO_DEBUG] ==================================================")
        
        # Calculate total borrowed for breakdown totals
        total_borrowed_usd_for_breakdown = sum(loan.get("borrowed_usd_value", 0) for loan in loans_found) if loans_found else 0.0
        
        # Log asset breakdown table (matches Crypto.com Wallet Balances table format)
        if PORTFOLIO_DEBUG and asset_breakdown:
            logger.info(f"[PORTFOLIO_DEBUG] ========== ASSET BREAKDOWN (Crypto.com Wallet Balance format) ==========")
            logger.info(f"[PORTFOLIO_DEBUG] {'Symbol':<12} {'Quantity':<20} {'Raw Value USD':<15} {'Haircut':<10} {'Collateral USD':<15}")
            logger.info(f"[PORTFOLIO_DEBUG] {'-'*12} {'-'*20} {'-'*15} {'-'*10} {'-'*15}")
            
            # Sort by raw_value_usd descending
            sorted_breakdown = sorted(asset_breakdown, key=lambda x: x["raw_value_usd"], reverse=True)
            for item in sorted_breakdown:
                logger.info(f"[PORTFOLIO_DEBUG] {item['symbol']:<12} {item['quantity']:<20.8f} ${item['raw_value_usd']:<14.2f} {item['haircut']:<9.4f} ${item['collateral_value_usd']:<14.2f}")
            
            logger.info(f"[PORTFOLIO_DEBUG] {'-'*12} {'-'*20} {'-'*15} {'-'*10} {'-'*15}")
            logger.info(f"[PORTFOLIO_DEBUG] TOTAL RAW ASSETS USD: ${total_usd:,.2f}")
            logger.info(f"[PORTFOLIO_DEBUG] TOTAL COLLATERAL USD: ${total_collateral_usd:,.2f}")
            logger.info(f"[PORTFOLIO_DEBUG] TOTAL BORROWED USD: ${total_borrowed_usd_for_breakdown:,.2f}")
            logger.info(f"[PORTFOLIO_DEBUG] NET WALLET BALANCE USD: ${total_collateral_usd - total_borrowed_usd_for_breakdown:,.2f}")
            logger.info(f"[PORTFOLIO_DEBUG] ==================================================")
        
        logger.info(f"Portfolio cache updated successfully. Raw assets: ${total_usd:,.2f}, Collateral: ${total_collateral_usd:,.2f}")
        
        result = {
            "success": True,
            "last_updated": last_updated,
            "total_usd": total_usd,
            "balance_count": len(balances_to_insert)
        }
        
        # Cache the result for request deduplication
        with _update_lock:
            _last_update_result = result
            _last_update_time = time.time()
        
        return result
        
    except Exception as e:
        error_str = str(e)
        logger.error(f"Error updating portfolio cache: {e}")
        db.rollback()
        
        # Extract error code if it's an authentication error
        error_code = None
        if "40101" in error_str:
            error_code = "40101"
        elif "40103" in error_str:
            error_code = "40103"
        
        result = {
            "success": False,
            "error": error_str,
            "last_updated": None,
            "auth_error": ("40101" in error_str or "40103" in error_str or "Authentication" in error_str),
            "error_code": error_code if error_code else None
        }
        
        # Cache the error result (but with shorter TTL for errors)
        with _update_lock:
            _last_update_result = result
            _last_update_time = time.time()
        
        return result


def get_cached_portfolio(db: Session) -> List[Dict]:
    """
    Get cached portfolio data from database
    
    Returns:
        List of portfolio balance dictionaries
    """
    try:
        balances = db.query(PortfolioBalance).order_by(
            PortfolioBalance.usd_value.desc()
        ).all()
        
        result = []
        for balance in balances:
            # Ensure usd_value is converted to float (may be Numeric type from DB)
            usd_value = float(balance.usd_value) if balance.usd_value is not None else 0.0
            result.append({
                "currency": balance.currency,
                "balance": float(balance.balance),
                "usd_value": usd_value
            })
        
        return result
    except Exception as e:
        logger.error(f"Error getting cached portfolio: {e}")
        return []


def get_last_updated(db: Session) -> float:
    """
    Get timestamp of last successful portfolio update
    
    Returns:
        Unix timestamp or None
    """
    try:
        snapshot = db.query(PortfolioSnapshot).order_by(
            PortfolioSnapshot.created_at.desc()
        ).first()
        
        if snapshot:
            return snapshot.created_at.timestamp()
        return None
    except Exception as e:
        logger.error(f"Error getting last updated timestamp: {e}")
        return None


def get_portfolio_summary(db: Session, request_context: Optional[Dict] = None) -> Dict:
    """
    Get summary of cached portfolio data with last updated timestamp
    OPTIMIZED: Uses efficient SQL queries and caching to minimize database calls
    Includes borrowed amounts (loans) subtracted from total value
    
    Args:
        db: Database session
        request_context: Optional request context (for header-based debug toggles)
    """
    import time as time_module
    start_time = time_module.time()
    query_start = start_time
    try:
        from sqlalchemy import func, text
        from app.models.portfolio_loan import PortfolioLoan
        from app.utils.http_client import http_get, http_post
        
        # OPTIMIZATION 1: Use SQL subquery to get latest balance per currency in one query
        # This is much faster than fetching all and deduplicating in Python
        try:
            # Try to use window function for better performance (PostgreSQL, SQLite 3.25+)
            # Get the latest balance per currency using ROW_NUMBER()
            # Use the actual table name from the model
            table_name = PortfolioBalance.__tablename__
            balances_query = db.execute(text(f"""
                SELECT currency, balance, usd_value
                FROM (
                    SELECT currency, balance, usd_value,
                           ROW_NUMBER() OVER (PARTITION BY currency ORDER BY id DESC) as rn
                    FROM {table_name}
                ) ranked
                WHERE rn = 1
                ORDER BY usd_value DESC
            """)).fetchall()
            
            # Convert to list of tuples for consistency
            balances_data = [(row[0], row[1], row[2]) for row in balances_query]
        except Exception:
            # Fallback: Use SQLAlchemy ORM with optimized query
            # Get only the latest balance per currency using a subquery
            try:
                # First, get max id per currency
                subquery = db.query(
                    PortfolioBalance.currency,
                    func.max(PortfolioBalance.id).label('max_id')
                ).group_by(PortfolioBalance.currency).subquery()
                
                # Then join to get the full balance records
                balances_query = db.query(
                    PortfolioBalance.currency,
                    PortfolioBalance.balance,
                    PortfolioBalance.usd_value
                ).join(
                    subquery,
                    (PortfolioBalance.currency == subquery.c.currency) &
                    (PortfolioBalance.id == subquery.c.max_id)
                ).order_by(PortfolioBalance.usd_value.desc()).all()
                
                balances_data = [(b.currency, b.balance, b.usd_value) for b in balances_query]
            except Exception:
                # Final fallback: Get all and deduplicate in Python (slower but works)
                balances_query = db.query(
                    PortfolioBalance.currency,
                    PortfolioBalance.balance,
                    PortfolioBalance.usd_value,
                    PortfolioBalance.id
                ).order_by(PortfolioBalance.currency, PortfolioBalance.id.desc()).all()
                
                # Deduplicate by currency (keep most recent by id)
                balances_by_currency = {}
                for balance in balances_query:
                    currency = _normalize_currency_name(balance.currency)
                    if not currency:
                        continue
                    balance_id = balance.id
                    if currency not in balances_by_currency:
                        balances_by_currency[currency] = balance
                    else:
                        existing = balances_by_currency[currency]
                        if balance_id > existing.id:
                            balances_by_currency[currency] = balance
                
                balances_data = [(b.currency, b.balance, b.usd_value) for b in balances_by_currency.values()]
        
        query_elapsed = time_module.time() - query_start
        if query_elapsed > 0.1:
            logger.debug(f"Balance query took {query_elapsed:.3f}s")
        
        # OPTIMIZATION 2: Calculate total_usd from deduplicated balances_data
        # This ensures consistency with the balances list (same deduplication logic)
        # Only sum positive USD values (negative values would indicate debts/loans which are handled separately)
        total_assets_usd = sum(float(usd_value) for _, _, usd_value in balances_data 
                              if usd_value is not None and float(usd_value) > 0)
        
        # Calculate total_collateral_usd (after haircuts) for Margin Wallet Balance
        # Crypto.com Margin "Wallet Balance" = Σ(collateral_value) - borrowed
        # where collateral_value = raw_value * (1 - haircut)
        # We need fresh API data to get current haircuts
        total_collateral_usd = 0.0
        try:
            from app.services.brokers.crypto_com_trade import trade_client
            # Ensure credentials are updated before API call
            from app.utils.credential_resolver import resolve_crypto_credentials
            api_key, api_secret, _, _ = resolve_crypto_credentials()
            if api_key and api_secret:
                if trade_client.api_key != api_key or trade_client.api_secret != api_secret:
                    trade_client.api_key = api_key
                    trade_client.api_secret = api_secret
            
            balance_data = trade_client.get_account_summary()
            
            # Build a map of currency -> raw USD value from cached balances (balances_data from query)
            raw_values_by_currency = {_normalize_currency_name(currency): float(usd_value) 
                                     for currency, _, usd_value in balances_data 
                                     if usd_value is not None and float(usd_value) > 0}
            
            # Extract haircuts from fresh API data and calculate collateral
            for account in balance_data.get("accounts", []):
                currency = _normalize_currency_name(
                    account.get("currency") or account.get("instrument_name") or account.get("symbol")
                )
                if not currency or currency not in raw_values_by_currency:
                    continue
                
                raw_value = raw_values_by_currency[currency]
                
                # Extract haircut (same logic as update_portfolio_cache)
                haircut = 0.0
                haircut_raw = account.get("haircut") or account.get("collateral_ratio") or account.get("discount") or account.get("haircut_rate")
                if haircut_raw is not None:
                    try:
                        if isinstance(haircut_raw, str):
                            haircut_str = haircut_raw.strip().replace("--", "").strip()
                            if haircut_str and haircut_str.lower() not in ["0", "0.0", "0.00"]:
                                haircut = float(haircut_str)
                        else:
                            haircut = float(haircut_raw)
                    except (ValueError, TypeError):
                        haircut = 0.0
                
                # Stablecoins have 0 haircut
                if currency in ["USD", "USDT", "USDC"]:
                    haircut = 0.0
                
                # Calculate collateral value
                collateral_value = raw_value * (1 - haircut)
                total_collateral_usd += collateral_value
                
                if PORTFOLIO_DEBUG:
                    logger.debug(f"[PORTFOLIO_DEBUG] {currency}: raw=${raw_value:.2f}, haircut={haircut:.4f}, collateral=${collateral_value:.2f}")
        except Exception as e:
            logger.warning(f"Could not fetch haircuts from API for collateral calculation: {e}. Using raw assets as fallback.")
            # Fallback: use raw assets if API call fails
            total_collateral_usd = total_assets_usd
        
        # OPTIMIZATION 3: Use cached table existence check
        total_borrowed_usd = 0.0
        total_borrowed_usd_for_display = 0.0  # Include ALL loans for display and calculation
        loans = []
        if _table_exists(db, 'portfolio_loans'):
            try:
                # Get total borrowed amount (loans) using SQL aggregation
                # NOTE: We calculate both crypto-only and all-loans totals for reference
                # The net wallet balance calculation uses ALL loans (including USD) to match Crypto.com UI
                total_borrowed_result = db.query(func.sum(PortfolioLoan.borrowed_usd_value)).filter(
                    PortfolioLoan.is_active == True,
                    PortfolioLoan.currency != 'USD'  # Crypto loans only (kept for reference)
                ).scalar()
                total_borrowed_usd = float(total_borrowed_result) if total_borrowed_result else 0.0
                
                # Get total borrowed for DISPLAY and CALCULATION purposes (includes ALL loans, including USD)
                total_borrowed_display_result = db.query(func.sum(PortfolioLoan.borrowed_usd_value)).filter(
                    PortfolioLoan.is_active == True
                ).scalar()
                total_borrowed_usd_for_display = float(total_borrowed_display_result) if total_borrowed_display_result else 0.0
                
                # Get loan details for display
                loans_query = db.query(PortfolioLoan).filter(
                    PortfolioLoan.is_active == True
                ).all()
                loans = [{
                    "currency": loan.currency,
                    "borrowed_amount": float(loan.borrowed_amount),
                    "borrowed_usd_value": float(loan.borrowed_usd_value),
                    "interest_rate": float(loan.interest_rate) if loan.interest_rate else None,
                    "notes": loan.notes
                } for loan in loans_query]
            except Exception as loan_err:
                logger.debug(f"Could not get loans data: {loan_err}")
        
        # CRITICAL: Prefer exchange-reported equity over derived calculation.
        # Crypto.com margin wallet provides pre-computed NET balance that includes:
        # - haircuts
        # - borrowed amounts
        # - accrued interest
        # - unrealized PnL
        # - mark price adjustments
        # This is more accurate than our derived calculation.
        
        # Determine if reconcile debug should be enabled for this request
        reconcile_debug_enabled = _should_enable_reconcile_debug(request_context)
        
        # Initialize reconciliation data (only populated if reconcile_debug_enabled=1)
        # Always initialize to ensure structure exists even if debug is disabled (prevents KeyError)
        reconcile_data = {
            "raw_fields": {},
            "candidates": {},
            "chosen": {}
        }
        
        # Exhaustive equity field detection - scan all possible equity/balance fields
        # Priority order:
        # 1. Exchange-reported balance/equity that matches Crypto.com UI "Balance"
        # 2. Exchange-reported margin equity (if that matches UI)
        # 3. Fallback: derived calculation (collateral_after_haircut - borrowed)
        
        exchange_equity_value = None
        exchange_margin_equity_value = None
        portfolio_value_source = None
        balance_data_fresh = None
        
        def normalize_numeric_value(value):
            """Normalize any numeric value to float, handling strings, None, etc."""
            if value is None:
                return None
            try:
                if isinstance(value, str):
                    # Remove commas, whitespace, and handle "--" or empty strings
                    cleaned = value.strip().replace(",", "").replace(" ", "").replace("--", "").strip()
                    if not cleaned or cleaned.lower() in ["0", "0.0", "0.00", "null", "none"]:
                        return None
                    return float(cleaned)
                return float(value)
            except (ValueError, TypeError):
                return None
        
        def scan_for_equity_fields(data, prefix=""):
            """Recursively scan data structure for all equity/balance fields."""
            found_fields = {}
            if not isinstance(data, dict):
                return found_fields
            
            # Exhaustive list of all possible equity/balance field names
            # Priority 0: Fields that explicitly indicate "after haircut" (matches Crypto.com UI "Wallet Balance (after haircut)")
            after_haircut_patterns = [
                "wallet_balance_after_haircut",
                "wallet_balance_af_haircut",
                "balance_after_haircut",
                "total_balance_after_haircut",
                "account_balance_after_haircut",
                "equity_after_haircut",
                # camelCase variants
                "walletBalanceAfterHaircut",
                "walletBalanceAfHaircut",
                "balanceAfterHaircut",
                "totalBalanceAfterHaircut",
                "accountBalanceAfterHaircut",
                "equityAfterHaircut",
            ]
            
            # Priority 1: Standard wallet/balance fields
            wallet_balance_fields = [
                "wallet_balance",
                "account_balance",
                "total_balance",
                "net_balance",
                # camelCase variants
                "walletBalance",
                "accountBalance",
                "totalBalance",
                "netBalance",
            ]
            
            # Priority 2: Equity fields
            equity_fields = [
                "equity",
                "net_equity",
                "total_equity",
                # camelCase variants
                "netEquity",
                "totalEquity",
            ]
            
            # Priority 3: Margin-specific fields
            margin_fields = [
                "margin_equity",
                # camelCase variants
                "marginEquity",
            ]
            
            # Other equity-like fields
            other_equity_fields = [
                "account_equity",
                "available_equity",
                "balance_equity",
                # camelCase variants
                "accountEquity",
                "availableEquity",
                "balanceEquity",
            ]
            
            # Combine all candidates for scanning
            all_candidates = after_haircut_patterns + wallet_balance_fields + equity_fields + margin_fields + other_equity_fields
            
            # Check all candidate fields at this level (case-insensitive matching)
            data_keys_lower = {k.lower(): k for k in data.keys()}
            
            for candidate in all_candidates:
                # Try exact match first
                if candidate in data:
                    value = normalize_numeric_value(data[candidate])
                    if value is not None and value != 0:
                        field_path = f"{prefix}.{candidate}" if prefix else candidate
                        found_fields[field_path] = value
                        if reconcile_debug_enabled:
                            reconcile_data["raw_fields"][field_path] = value
                # Try case-insensitive match
                elif candidate.lower() in data_keys_lower:
                    actual_key = data_keys_lower[candidate.lower()]
                    value = normalize_numeric_value(data[actual_key])
                    if value is not None and value != 0:
                        field_path = f"{prefix}.{actual_key}" if prefix else actual_key
                        found_fields[field_path] = value
                        if reconcile_debug_enabled:
                            reconcile_data["raw_fields"][field_path] = value
            
            # Recursively check nested structures (defensive - handle all edge cases)
            try:
                for key, value in data.items():
                    if isinstance(value, dict):
                        nested_prefix = f"{prefix}.{key}" if prefix else key
                        found_fields.update(scan_for_equity_fields(value, nested_prefix))
                    elif isinstance(value, list) and len(value) > 0:
                        # Check first element of array (common pattern: result.data[0])
                        # Defensive: ensure first element is a dict before accessing
                        if isinstance(value[0], dict):
                            nested_prefix = f"{prefix}.{key}[0]" if prefix else f"{key}[0]"
                            found_fields.update(scan_for_equity_fields(value[0], nested_prefix))
            except (AttributeError, TypeError, IndexError, KeyError) as e:
                # Silently skip problematic structures - don't crash the endpoint
                logger.debug(f"Error scanning nested structure at prefix '{prefix}': {e}")
            
            return found_fields
        
        try:
            from app.services.brokers.crypto_com_trade import trade_client
            # Ensure credentials are updated before API call
            from app.utils.credential_resolver import resolve_crypto_credentials
            api_key, api_secret, _, _ = resolve_crypto_credentials()
            if api_key and api_secret:
                if trade_client.api_key != api_key or trade_client.api_secret != api_secret:
                    trade_client.api_key = api_key
                    trade_client.api_secret = api_secret
            
            balance_data_fresh = trade_client.get_account_summary()
            
            # Defensive: ensure balance_data_fresh is a dict before scanning
            if not isinstance(balance_data_fresh, dict):
                logger.warning(f"get_account_summary() returned non-dict type: {type(balance_data_fresh)}")
                balance_data_fresh = {}
            
            # Exhaustive scan of all equity fields in the response
            all_equity_fields = scan_for_equity_fields(balance_data_fresh)
            
            if reconcile_debug_enabled:
                logger.info(f"[RECONCILE] Found {len(all_equity_fields)} equity/balance fields in API response")
                for field_path, value in all_equity_fields.items():
                    logger.debug(f"[RECONCILE]   {field_path}: ${value:,.2f}")
            
            # Check for override field (if PORTFOLIO_EQUITY_FIELD_OVERRIDE is set)
            override_field = os.getenv("PORTFOLIO_EQUITY_FIELD_OVERRIDE", "").strip()
            if override_field:
                # Fuzzy match against discovered field paths
                matched_path = None
                matched_value = None
                override_lower = override_field.lower()
                for field_path, value in all_equity_fields.items():
                    field_path_lower = field_path.lower()
                    if override_lower in field_path_lower or field_path_lower in override_lower:
                        matched_path = field_path
                        matched_value = value
                        logger.info(f"✅ [OVERRIDE] Matched override '{override_field}' to field '{field_path}': ${value:,.2f}")
                        break
                
                if matched_path:
                    exchange_equity_value = matched_value
                    portfolio_value_source = f"exchange:{matched_path}"
                    chosen_field_path = matched_path
                else:
                    logger.warning(f"⚠️ [OVERRIDE] PORTFOLIO_EQUITY_FIELD_OVERRIDE='{override_field}' not found in API response. Available fields: {list(all_equity_fields.keys())[:10]}")
                    if reconcile_debug_enabled:
                        reconcile_data["chosen"] = {
                            "value": None,
                            "source_key": "override_not_found",
                            "field_path": None,
                            "error": f"Override field '{override_field}' not found in API response"
                        }
                    # Continue with normal priority selection
                    override_field = None
            
            # Priority-based selection (only if override not set or not found)
            if not override_field or exchange_equity_value is None:
                chosen_field_path = None
                
                # Priority 0: Fields that explicitly indicate "after haircut" (matches Crypto.com UI "Wallet Balance (after haircut)")
                # Support both snake_case and camelCase
                after_haircut_patterns = [
                    "wallet_balance_after_haircut", "wallet_balance_af_haircut",
                    "balance_after_haircut", "total_balance_after_haircut",
                    "account_balance_after_haircut", "equity_after_haircut",
                    "walletbalanceafterhaircut", "walletbalanceafhaircut",
                    "balanceafterhaircut", "totalbalanceafterhaircut",
                    "accountbalanceafterhaircut", "equityafterhaircut"
                ]
                
                # Find all after_haircut fields (case-insensitive, supports both snake_case and camelCase)
                after_haircut_candidates = {}
                for field_path, value in all_equity_fields.items():
                    field_name_lower = field_path.split(".")[-1].split("[")[0].lower().replace("_", "").replace("-", "")
                    # Check for after_haircut or afterHaircut patterns
                    if "afterhaircut" in field_name_lower or "afhaircut" in field_name_lower:
                        after_haircut_candidates[field_path] = value
                
                if after_haircut_candidates:
                    # Priority within after_haircut: wallet_balance* > account_balance* > equity*
                    priority_order = ["wallet_balance", "account_balance", "equity", "balance", "total"]
                    for priority_term in priority_order:
                        for field_path, value in after_haircut_candidates.items():
                            field_name_lower = field_path.split(".")[-1].split("[")[0].lower()
                            if priority_term in field_name_lower:
                                exchange_equity_value = value
                                portfolio_value_source = f"exchange:{field_path}"
                                chosen_field_path = field_path
                                logger.info(f"✅ [PRIORITY 0] Found after_haircut field '{field_path}': ${exchange_equity_value:,.2f}")
                                break
                        if exchange_equity_value is not None:
                            break
                    
                    # If no priority match, use first after_haircut field
                    if exchange_equity_value is None:
                        field_path, value = next(iter(after_haircut_candidates.items()))
                        exchange_equity_value = value
                        portfolio_value_source = f"exchange:{field_path}"
                        chosen_field_path = field_path
                        logger.info(f"✅ [PRIORITY 0] Using after_haircut field '{field_path}': ${exchange_equity_value:,.2f}")
                
                # Priority 1: wallet_balance / account_balance / total_balance (even if not labeled after haircut)
                # Support both snake_case and camelCase
                if exchange_equity_value is None:
                    priority_1_fields = ["wallet_balance", "account_balance", "total_balance", "net_balance",
                                         "walletbalance", "accountbalance", "totalbalance", "netbalance"]
                    for field_path, value in all_equity_fields.items():
                        field_name = field_path.split(".")[-1].split("[")[0].lower().replace("_", "").replace("-", "")
                        if field_name in [f.replace("_", "").replace("-", "") for f in priority_1_fields]:
                            exchange_equity_value = value
                            portfolio_value_source = f"exchange:{field_path}"
                            chosen_field_path = field_path
                            logger.info(f"✅ [PRIORITY 1] Found wallet/balance field '{field_path}': ${exchange_equity_value:,.2f}")
                            break
                
                # Priority 2: equity / net_equity / total_equity
                # Support both snake_case and camelCase
                if exchange_equity_value is None:
                    priority_2_fields = ["equity", "net_equity", "total_equity",
                                         "netequity", "totalequity"]
                    for field_path, value in all_equity_fields.items():
                        field_name = field_path.split(".")[-1].split("[")[0].lower().replace("_", "").replace("-", "")
                        if field_name in [f.replace("_", "").replace("-", "") for f in priority_2_fields]:
                            exchange_equity_value = value
                            portfolio_value_source = f"exchange:{field_path}"
                            chosen_field_path = field_path
                            logger.info(f"✅ [PRIORITY 2] Found equity field '{field_path}': ${exchange_equity_value:,.2f}")
                            break
                
                # Priority 3: margin_equity (supports both snake_case and camelCase)
                if exchange_equity_value is None:
                    for field_path, value in all_equity_fields.items():
                        field_name = field_path.split(".")[-1].split("[")[0].lower().replace("_", "").replace("-", "")
                        if field_name == "marginequity":
                            exchange_equity_value = value
                            portfolio_value_source = f"exchange:{field_path}"
                            chosen_field_path = field_path
                            logger.info(f"✅ [PRIORITY 3] Found margin equity field '{field_path}': ${exchange_equity_value:,.2f}")
                            break
                
                # If still not found, try any other equity field (but log as lower priority)
                if exchange_equity_value is None and all_equity_fields:
                    field_path, value = next(iter(all_equity_fields.items()))
                    exchange_equity_value = value
                    portfolio_value_source = f"exchange:{field_path}"
                    chosen_field_path = field_path
                    logger.info(f"✅ [FALLBACK] Using any exchange equity field '{field_path}': ${exchange_equity_value:,.2f}")
            
            # Store account type if present (safe identifier, no secrets)
            # Defensive: handle missing or malformed accounts data
            try:
                if reconcile_debug_enabled and balance_data_fresh and isinstance(balance_data_fresh, dict):
                    if "accounts" in balance_data_fresh:
                        accounts = balance_data_fresh["accounts"]
                        if isinstance(accounts, list) and len(accounts) > 0:
                            account_types = set()
                            for acc in accounts:
                                if isinstance(acc, dict):
                                    acc_type = acc.get("account_type")
                                    if acc_type:
                                        account_types.add(str(acc_type))
                            if account_types:
                                reconcile_data["raw_fields"]["account_types"] = list(account_types)
            except (AttributeError, TypeError, KeyError) as e:
                logger.debug(f"Error extracting account types: {e}")
                            
        except Exception as e:
            logger.warning(f"Could not fetch equity from API: {e}", exc_info=True)
            if PORTFOLIO_DEBUG:
                logger.warning(f"Error fetching account summary for equity: {e}")
            # Ensure all_equity_fields is initialized even on error
            all_equity_fields = {}
            balance_data_fresh = None
            chosen_field_path = None
        
        # Calculate derived value for comparison
        # Use total_borrowed_usd_for_display (ALL loans) to match what's shown in UI
        # This ensures: Total Value = Collateral - Borrowed (where Borrowed includes all loans)
        # Defensive: ensure values are numeric
        try:
            total_collateral_usd = float(total_collateral_usd) if total_collateral_usd is not None else 0.0
            total_borrowed_usd_for_display = float(total_borrowed_usd_for_display) if total_borrowed_usd_for_display is not None else 0.0
            derived_equity = total_collateral_usd - total_borrowed_usd_for_display
        except (TypeError, ValueError) as e:
            logger.warning(f"Error calculating derived equity: {e}, using 0.0")
            derived_equity = 0.0
        
        # Build candidate values for reconciliation (SAFE: only numeric values)
        if reconcile_debug_enabled:
            reconcile_data["candidates"] = {}
            
            # Add exchange candidates (if found)
            if exchange_equity_value is not None:
                # Determine candidate key based on field path
                field_name_lower = chosen_field_path.split(".")[-1].split("[")[0].lower() if chosen_field_path else ""
                if "after_haircut" in field_name_lower or "af_haircut" in field_name_lower:
                    if "wallet" in field_name_lower:
                        reconcile_data["candidates"]["exchange_wallet_balance_after_haircut"] = exchange_equity_value
                    else:
                        reconcile_data["candidates"]["exchange_wallet_balance_after_haircut"] = exchange_equity_value  # Default
                elif "wallet_balance" in field_name_lower:
                    reconcile_data["candidates"]["exchange_wallet_balance"] = exchange_equity_value
                elif "equity" in field_name_lower:
                    reconcile_data["candidates"]["exchange_equity"] = exchange_equity_value
                elif "margin" in field_name_lower:
                    reconcile_data["candidates"]["exchange_margin_equity"] = exchange_equity_value
                else:
                    reconcile_data["candidates"][f"exchange_{field_name_lower}"] = exchange_equity_value
            
            # Always include derived calculation for comparison
            reconcile_data["candidates"]["derived_collateral_minus_borrowed"] = derived_equity
        
        # IMPORTANT: Never pick derived if ANY wallet/balance/equity candidate exists
        if exchange_equity_value is not None:
            # Use exchange-reported value
            total_usd = exchange_equity_value
            # portfolio_value_source already set in priority selection (format: "exchange:{field_path}")
            logger.info(f"✅ Using exchange-reported equity as total_usd: ${total_usd:,.2f} (source: {portfolio_value_source})")
            
            if PORTFOLIO_DEBUG:
                delta = abs(exchange_equity_value - derived_equity) if derived_equity else None
                logger.info(f"[PORTFOLIO_DEBUG] total_value_source={portfolio_value_source} exchange_equity=${exchange_equity_value:,.2f} derived_equity=${derived_equity:,.2f} delta=${delta:,.2f if delta else 'N/A'}")
            
            if reconcile_debug_enabled:
                # Determine priority from portfolio_value_source
                priority = 0
                if "after_haircut" in portfolio_value_source.lower() or "af_haircut" in portfolio_value_source.lower():
                    priority = 0
                elif "wallet_balance" in portfolio_value_source.lower() or "account_balance" in portfolio_value_source.lower():
                    priority = 1
                elif "equity" in portfolio_value_source.lower() and "margin" not in portfolio_value_source.lower():
                    priority = 2
                elif "margin" in portfolio_value_source.lower():
                    priority = 3
                else:
                    priority = 4
                
                reconcile_data["chosen"] = {
                    "value": total_usd,
                    "source_key": portfolio_value_source.split(":")[-1] if ":" in portfolio_value_source else portfolio_value_source,
                    "field_path": chosen_field_path,
                    "priority": priority
                }
        else:
            # Fallback: Only use derived if NO exchange fields exist
            total_usd = derived_equity
            portfolio_value_source = "derived:collateral_minus_borrowed"
            logger.warning(f"⚠️ Exchange equity not found, using derived calculation: collateral ${total_collateral_usd:,.2f} - borrowed ${total_borrowed_usd_for_display:,.2f} (all loans) = ${total_usd:,.2f}")
            logger.warning(f"⚠️ This may not match Crypto.com Dashboard Balance. Check API response for equity fields.")
            
            if PORTFOLIO_DEBUG:
                logger.info(f"[PORTFOLIO_DEBUG] total_value_source=derived:collateral_minus_borrowed exchange_equity=None derived_equity=${derived_equity:,.2f} delta=N/A")
            
            if reconcile_debug_enabled:
                reconcile_data["chosen"] = {
                    "value": total_usd,
                    "source_key": "derived_collateral_minus_borrowed",
                    "field_path": None,
                    "priority": 5  # Fallback priority
                }
        
        # Computed fields:
        # - total_assets_usd: GROSS raw assets (sum of all asset USD values, before haircut and borrowed)
        # - total_collateral_usd: Collateral value after applying haircuts (Σ raw_value * (1 - haircut))
        # - total_borrowed_usd: Total borrowed/margin amounts (ALL loans including USD - for display and calculation)
        # - total_usd: NET Wallet Balance (prefer exchange-reported margin_equity, fallback to collateral - borrowed)
        #   Note: Net wallet balance = collateral - ALL loans (including USD) to match Crypto.com UI
        #
        # The frontend should use total_usd (NET Wallet Balance) as "Total Value" to match Crypto.com UI exactly.
        
        # OPTIMIZATION 4: Get last updated timestamp (single query, should be fast with index)
        snapshot = db.query(PortfolioSnapshot).order_by(
            PortfolioSnapshot.created_at.desc()
        ).first()
        last_updated = snapshot.created_at.timestamp() if snapshot else None
        
        # Build balances list from optimized query results
        balances = []
        for currency, balance_val, usd_value in balances_data:
            currency = _normalize_currency_name(currency)
            if not currency:
                continue
            usd_value = float(usd_value) if usd_value is not None else 0.0
            balances.append({
                "currency": currency,
                "balance": float(balance_val),
                "usd_value": usd_value
            })
        
        elapsed_time = time_module.time() - start_time
        
        # Log summary for debugging
        balances_with_usd = [b for b in balances if b["usd_value"] > 0]
        logger.info(f"Portfolio summary fetched in {elapsed_time:.3f}s: {len(balances)} balances, {len(balances_with_usd)} with USD values, total_assets=${total_assets_usd:,.2f}, total_borrowed=${total_borrowed_usd:,.2f}, net_value=${total_usd:,.2f}")
        
        if elapsed_time > 0.2:
            logger.warning(f"⚠️ Portfolio summary fetch took {elapsed_time:.3f}s - this is slow! Should be < 0.2 seconds.")
            # Log breakdown of time spent
            logger.debug(f"   - Query time: {query_elapsed:.3f}s")
        
        if balances_with_usd:
            logger.debug(f"Top 5 balances by USD value:")
            for b in sorted(balances_with_usd, key=lambda x: x["usd_value"], reverse=True)[:5]:
                logger.debug(f"  {b['currency']}: ${b['usd_value']:,.2f} (balance: {b['balance']:.8f})")
        
        if loans:
            logger.info(f"Active loans: {len(loans)}, total borrowed: ${total_borrowed_usd:,.2f}")
            for loan in loans:
                logger.debug(f"  {loan['currency']}: ${loan['borrowed_usd_value']:,.2f} borrowed")
        
        # Invariant: Total Value shown to users must equal Crypto.com Margin "Wallet Balance" (NET).
        # This contract must be maintained - frontend relies on total_usd for "Total Value" display.
        # All values are always returned:
        # - total_usd: NET Wallet Balance (collateral - ALL borrowed loans including USD) - matches Crypto.com "Wallet Balance"
        # - total_assets_usd: GROSS raw assets (before haircut and borrowed) - informational only
        # - total_collateral_usd: Collateral value after haircuts - informational only
        # - total_borrowed_usd: Borrowed amounts (ALL loans including USD, shown separately, NOT added to totals)
        
        if PORTFOLIO_DEBUG:
            logger.info(f"[PORTFOLIO_DEBUG] Portfolio summary: net=${total_usd:,.2f}, gross=${total_assets_usd:,.2f}, collateral=${total_collateral_usd:,.2f}, borrowed=${total_borrowed_usd:,.2f}, pricing_source=crypto_com_api, portfolio_value_source={portfolio_value_source}")
        
        result = {
            "balances": balances,
            "total_usd": total_usd,
            "total_assets_usd": total_assets_usd,
            "total_collateral_usd": total_collateral_usd,
            "total_borrowed_usd": total_borrowed_usd_for_display,  # Use display value (includes ALL loans)
            "portfolio_value_source": portfolio_value_source,  # Source of total_usd calculation
            "loans": loans,
            "last_updated": last_updated
        }
        
        # Add reconcile data if debug mode is enabled
        # Always include reconcile structure (even if empty) when debug is enabled to prevent KeyError in frontend
        if reconcile_debug_enabled:
            result["reconcile"] = reconcile_data
        
        return result
    except Exception as e:
        logger.error(f"Error getting portfolio summary: {e}", exc_info=True)
        return {
            "balances": [],
            "total_usd": 0.0,
            "total_assets_usd": 0.0,
            "total_borrowed_usd": 0.0,
            "loans": [],
            "last_updated": None
        }
