"""Service for caching portfolio data in the database"""
import logging
from sqlalchemy.orm import Session
from app.models.portfolio import PortfolioBalance, PortfolioSnapshot
from app.services.brokers.crypto_com_trade import trade_client
import time
from typing import List, Dict, Optional
import threading
from functools import lru_cache

logger = logging.getLogger(__name__)

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
        
        # Get current prices for ALL coins (not just USDT pairs)
        prices = get_crypto_prices()
        
        # Also get prices from multiple sources for better coverage
        additional_prices = {}
        
        # Map common currency names to CoinGecko IDs (defined outside try block for later use)
        gecko_ids = {
                "BTC": "bitcoin",
                "ETH": "ethereum",
                "BNB": "binancecoin",
                "SOL": "solana",
                "XRP": "ripple",
                "ADA": "cardano",
                "DOT": "polkadot",
                "MATIC": "matic-network",
                "LINK": "chainlink",
                "UNI": "uniswap",
                "AVAX": "avalanche-2",
                "ATOM": "cosmos",
                "ALGO": "algorand",
                "NEAR": "near",
                "AAVE": "aave",
                "CRO": "crypto-com-chain",
                "USDT": "tether",
                "USDC": "usd-coin",
                "BONK": "bonk",
                "AKT": "akash-network",
                "TON": "the-open-network",
        }
        
        # Try CoinGecko API for coins not found in Crypto.com
        try:
            gecko_url = "https://api.coingecko.com/api/v3/simple/price"
            # Get list of currencies we have balances for
            currencies = [acc.get("currency", "").upper() for acc in balance_data.get("accounts", [])]
            
            # Build list of CoinGecko IDs for currencies we need
            gecko_id_list = [gecko_ids.get(c) for c in currencies if c in gecko_ids and c not in prices]
            
            if gecko_id_list:
                gecko_params = {
                    "ids": ",".join([id for id in gecko_id_list if id]),
                    "vs_currencies": "usd"
                }
                gecko_response = http_get(gecko_url, params=gecko_params, timeout=10, calling_module="portfolio_cache")
                if gecko_response.status_code == 200:
                    gecko_data = gecko_response.json()
                    for gecko_id, gecko_info in gecko_data.items():
                        if "usd" in gecko_info:
                            # Find currency name for this gecko_id
                            for currency, cid in gecko_ids.items():
                                if cid == gecko_id:
                                    additional_prices[currency] = float(gecko_info["usd"])
                                    break
        except Exception as e:
            logger.debug(f"Could not fetch additional prices from CoinGecko: {e}")
        
        # Merge prices
        all_prices = {**prices, **additional_prices}
        
        # Clear old balances
        db.query(PortfolioBalance).delete()
        
        # Calculate total portfolio value
        total_usd = 0.0
        balances_to_insert = []
        
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
            
            # Use market_value from Crypto.com if available (most accurate)
            # market_value comes as string from get_account_summary
            market_value_from_api = account.get("market_value")
            logger.debug(f"Processing {currency}: balance={balance:.8f}, market_value_from_api={market_value_from_api} (type: {type(market_value_from_api).__name__})")
            usd_value = 0.0
            
            # Try to use market_value from API first (most accurate)
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
                            logger.info(f"✅ Using market_value from Crypto.com API for {currency}: ${usd_value:.2f} (from numeric {market_value_from_api})")
                        else:
                            logger.debug(f"market_value is 0 for {currency}, will calculate from prices")
                            usd_value = 0.0
                except (ValueError, TypeError) as e:
                    logger.warning(f"⚠️ Could not parse market_value '{market_value_from_api}' for {currency}: {e}, will calculate from prices")
                    usd_value = 0.0
            else:
                logger.debug(f"No market_value from API for {currency}, will calculate from prices")
            
            # If no valid market_value from API, calculate it ourselves using prices
            if usd_value == 0 or usd_value is None:
                logger.debug(f"Calculating USD value for {currency} from prices (balance: {balance:.8f})")
                if currency == "USDT" or currency == "USD" or currency == "USDC":
                    usd_value = balance
                    logger.info(f"✅ {currency}: stablecoin, calculated USD value: ${usd_value:.2f}")
                elif currency in all_prices:
                    price = all_prices[currency]
                    usd_value = balance * price
                    logger.info(f"✅ {currency}: calculated USD value from cached price ${price:.8f} × {balance:.8f} = ${usd_value:.2f}")
                else:
                    # Try multiple sources to find price
                    logger.debug(f"Price not found for {currency} in cache, attempting to fetch from multiple sources...")
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
                                        usd_value = balance * price
                                        logger.info(f"✅ Found price for {currency}: ${price:.8f} via Crypto.com API (USD pair) → USD value: ${usd_value:.2f} (balance: {balance:.8f})")
                                        price_found = True
                                    else:
                                        logger.debug(f"Price from Crypto.com API is 0 for {currency}_USD")
                        except Exception as e:
                            logger.debug(f"Could not fetch price for {currency}_USD from Crypto.com: {e}")
                    
                    # If still not found, try CoinGecko search API
                    if not price_found and currency in gecko_ids:
                        try:
                            gecko_id = gecko_ids[currency]
                            gecko_url_single = f"https://api.coingecko.com/api/v3/simple/price?ids={gecko_id}&vs_currencies=usd"
                            gecko_response = http_get(gecko_url_single, timeout=5, calling_module="portfolio_cache")
                            if gecko_response.status_code == 200:
                                gecko_data = gecko_response.json()
                                if gecko_id in gecko_data and "usd" in gecko_data[gecko_id]:
                                    price = float(gecko_data[gecko_id]["usd"])
                                    if price > 0:
                                        all_prices[currency] = price
                                        usd_value = balance * price
                                        logger.info(f"✅ Found price for {currency}: ${price:.8f} via CoinGecko → USD value: ${usd_value:.2f} (balance: {balance:.8f})")
                                        price_found = True
                                    else:
                                        logger.debug(f"Price from CoinGecko is 0 for {currency}")
                        except Exception as e:
                            logger.debug(f"Could not fetch price for {currency} from CoinGecko: {e}")
                    
                    if not price_found:
                        logger.warning(f"⚠️ Could not find price for {currency} from any source")
            
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
            
            # Always save the balance to database, even if usd_value is 0 (might be updated later or price data missing)
            # This ensures we have a record of all balances
            if usd_value > 0:
                total_usd += usd_value
                logger.info(f"✅ {currency}: balance={balance:.8f}, usd_value=${usd_value:.2f} → added to total (total now: ${total_usd:.2f})")
            else:
                # Warn for non-stablecoins with balance > 0 but no USD value
                if currency not in ["USD", "USDT", "USDC"]:
                    logger.warning(f"⚠️ Could not calculate USD value for {currency} (balance: {balance:.8f}) - price data may be missing or balance is 0")
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
        snapshot = PortfolioSnapshot(total_usd=total_usd)
        db.add(snapshot)
        
        db.commit()
        
        last_updated = time.time()
        
        logger.info(f"Portfolio cache updated successfully. Total USD: ${total_usd:,.2f}")
        
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


def get_portfolio_summary(db: Session) -> Dict:
    """
    Get summary of cached portfolio data with last updated timestamp
    OPTIMIZED: Uses efficient SQL queries and caching to minimize database calls
    Includes borrowed amounts (loans) subtracted from total value
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
        
        # OPTIMIZATION 3: Use cached table existence check
        total_borrowed_usd = 0.0
        loans = []
        if _table_exists(db, 'portfolio_loans'):
            try:
                # Get total borrowed amount (loans) using SQL aggregation
                # IMPORTANT: Only subtract crypto loans, NOT USD loans
                total_borrowed_result = db.query(func.sum(PortfolioLoan.borrowed_usd_value)).filter(
                    PortfolioLoan.is_active == True,
                    PortfolioLoan.currency != 'USD'  # Exclude USD loans from subtraction
                ).scalar()
                total_borrowed_usd = float(total_borrowed_result) if total_borrowed_result else 0.0
                
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
        
        # Calculate net portfolio value (assets - crypto loans only, USD loans are capital)
        total_usd = total_assets_usd - total_borrowed_usd
        
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
        
        return {
            "balances": balances,
            "total_usd": total_usd,
            "total_assets_usd": total_assets_usd,
            "total_borrowed_usd": total_borrowed_usd,
            "loans": loans,
            "last_updated": last_updated
        }
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
