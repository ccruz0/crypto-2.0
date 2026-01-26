"""
Portfolio snapshot endpoints
"""

import logging
import os
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from app.database import get_db
from app.services.portfolio_snapshot import (
    fetch_live_portfolio_snapshot,
    store_portfolio_snapshot,
    get_latest_portfolio_snapshot
)
from app.core.environment import is_local

log = logging.getLogger(__name__)
router = APIRouter()


@router.post("/portfolio/refresh")
async def refresh_portfolio_snapshot(
    db: Session = Depends(get_db),
    admin_key: Optional[str] = Body(None, embed=True, alias="admin_key")
):
    """
    Refresh portfolio snapshot from Crypto.com Exchange (live fetch).
    
    This endpoint:
    - Fetches live balances from Crypto.com Exchange
    - Gets current prices from market cache
    - Computes USD values per asset
    - Stores snapshot in database
    
    For local development, this can be called without authentication.
    For production, set ADMIN_ACTIONS_KEY in environment and pass it as admin_key.
    
    Returns:
        {
            "success": true,
            "snapshot": { ... portfolio snapshot ... },
            "message": "Portfolio snapshot refreshed successfully"
        }
    """
    import os
    
    # Check admin key if configured
    admin_actions_key = os.getenv("ADMIN_ACTIONS_KEY")
    if admin_actions_key:
        if not admin_key or admin_key != admin_actions_key:
            raise HTTPException(status_code=403, detail="Invalid admin key")
    
    try:
        # Fetch live snapshot
        snapshot = fetch_live_portfolio_snapshot(db)
        
        # Store in database
        store_portfolio_snapshot(db, snapshot)
        
        return {
            "success": True,
            "snapshot": snapshot,
            "message": f"Portfolio snapshot refreshed: {len(snapshot.get('assets', []))} assets, "
                      f"total=${snapshot.get('total_value_usd', 0):,.2f}"
        }
    
    except ValueError as e:
        # Credentials not configured
        raise HTTPException(
            status_code=400,
            detail={
                "error": "API credentials not configured",
                "message": str(e),
                "hint": "Set EXCHANGE_CUSTOM_API_KEY and EXCHANGE_CUSTOM_API_SECRET in environment"
            }
        )
    except RuntimeError as e:
        # API call failed
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Failed to fetch portfolio from Crypto.com",
                "message": str(e)
            }
        )
    except Exception as e:
        log.error(f"Error refreshing portfolio snapshot: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Internal server error",
                "message": str(e)
            }
        )


@router.get("/portfolio/latest")
async def get_latest_portfolio(
    db: Session = Depends(get_db),
    max_age_minutes: int = 5
):
    """
    Get latest portfolio snapshot from database.
    
    Args:
        max_age_minutes: Maximum age of snapshot in minutes (default: 5)
    
    Returns:
        Portfolio snapshot if fresh, or null if no fresh snapshot available
    """
    try:
        snapshot = get_latest_portfolio_snapshot(db, max_age_minutes=max_age_minutes)
        
        if snapshot:
            return snapshot
        else:
            return {
                "error": "No fresh snapshot available",
                "message": f"No snapshot found or snapshot is older than {max_age_minutes} minutes. "
                          "Call POST /api/portfolio/refresh to fetch a new snapshot."
            }
    
    except Exception as e:
        log.error(f"Error getting latest portfolio snapshot: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Internal server error",
                "message": str(e)
            }
        )


@router.get("/portfolio/snapshot")
async def get_portfolio_snapshot(
    exchange: str = "CRYPTO_COM",
    db: Session = Depends(get_db)
):
    """
    Get real portfolio snapshot with positions and totals.
    
    This endpoint fetches live portfolio data from Crypto.com Exchange
    and returns it in a simplified format for the UI.
    
    Args:
        exchange: Exchange name (default: CRYPTO_COM)
    
    Returns:
        {
            "ok": true/false,
            "as_of": "2026-01-04T01:00:00Z",
            "exchange": "CRYPTO_COM",
            "message": "...",
            "missing_env": ["EXCHANGE_CUSTOM_API_KEY", "EXCHANGE_CUSTOM_API_SECRET"],
            "positions": [
                {
                    "asset": "BTC",
                    "free": 0.5,
                    "locked": 0.0,
                    "total": 0.5,
                    "price_usd": 65000.12,
                    "value_usd": 32500.06,
                    "source": "crypto_com|coingecko|yahoo"
                }
            ],
            "totals": {
                "total_value_usd": 1234.56,
                "total_assets_usd": 1500.00,
                "total_borrowed_usd": 265.44,
                "total_collateral_usd": 0
            },
            "errors": []
        }
    """
    errors = []
    
    # Generate request ID for tracing
    import uuid
    request_id = str(uuid.uuid4())[:8]
    
    # Get runtime origin and service info (safe, no secrets)
    runtime_origin = os.getenv("RUNTIME_ORIGIN", "UNKNOWN")
    environment = os.getenv("ENVIRONMENT", "UNKNOWN")
    container_name = os.getenv("HOSTNAME", os.getenv("CONTAINER_NAME", "UNKNOWN"))
    
    # Resolve credentials using multi-pair resolver
    from app.utils.credential_resolver import resolve_crypto_credentials, get_missing_env_vars
    api_key, api_secret, used_pair_name, credential_diagnostics = resolve_crypto_credentials()
    
    # Safe logging: only env var names, not values
    log.info(f"[PORTFOLIO_SNAPSHOT] request_id={request_id} exchange={exchange} runtime_origin={runtime_origin} "
             f"environment={environment} container={container_name} "
             f"credential_pair={used_pair_name if used_pair_name else 'NONE'}")
    
    # Log which credential pair was selected (names only)
    if used_pair_name:
        log.info(f"[PORTFOLIO_SNAPSHOT] request_id={request_id} selected_credential_pair={used_pair_name}")
    else:
        # Log which pairs were checked (diagnostic keys only)
        checked_pairs = [k.replace("_PRESENT", "") for k in credential_diagnostics.keys() if k.endswith("_PRESENT")]
        log.info(f"[PORTFOLIO_SNAPSHOT] request_id={request_id} checked_credential_pairs={','.join(checked_pairs)}")
    
    # Diagnostics only when explicitly enabled
    portfolio_debug = os.getenv("PORTFOLIO_DEBUG", "0") == "1"
    
    if portfolio_debug:
        log.info("[PORTFOLIO_SNAPSHOT] === CREDENTIAL DIAGNOSTICS (DEBUG MODE) ===")
        for key, value in credential_diagnostics.items():
            log.info(f"[PORTFOLIO_SNAPSHOT] {key}={value}")
        if api_key:
            # Log last 4 chars only
            key_suffix = api_key[-4:] if len(api_key) >= 4 else "<SHORT>"
            log.info(f"[PORTFOLIO_SNAPSHOT] API_KEY_SUFFIX={key_suffix}")
        if used_pair_name:
            log.info(f"[PORTFOLIO_SNAPSHOT] Using non-canonical pair: {used_pair_name}")
        log.info("[PORTFOLIO_SNAPSHOT] =====================================")
    
    # Check if credentials are missing
    missing_env = get_missing_env_vars()
    
    if missing_env:
        log.warning(f"[PORTFOLIO_SNAPSHOT] Missing credentials: {missing_env}")
        message = "Missing API credentials"
        if portfolio_debug:
            message += f" (checked: {', '.join(credential_diagnostics.keys())})"
        return {
            "ok": False,
            "as_of": datetime.now(timezone.utc).isoformat(),
            "exchange": exchange,
            "message": message,
            "missing_env": missing_env,
            "positions": [],
            "totals": {
                "total_value_usd": 0.0,
                "total_assets_usd": 0.0,
                "total_borrowed_usd": 0.0,
                "total_collateral_usd": 0.0
            },
            "errors": []
        }
    
    # Build message with credential source info (only in debug mode)
    message_parts = []
    if portfolio_debug and used_pair_name:
        message_parts.append(f"Using {used_pair_name}")
    
    try:
        # Log which client path will be used (safe, no secrets)
        from app.services.brokers.crypto_com_trade import trade_client
        use_proxy = os.getenv("USE_CRYPTO_PROXY", "false").lower() == "true"
        client_path = "crypto_com_proxy" if use_proxy else "crypto_com_direct"
        log.info(f"[PORTFOLIO_SNAPSHOT] request_id={request_id} client_path={client_path} "
                 f"USE_CRYPTO_PROXY={use_proxy}")
        
        # Try to get fresh snapshot first (from cache)
        snapshot = get_latest_portfolio_snapshot(db, max_age_minutes=5)
        
        # If no fresh snapshot, fetch live data
        if not snapshot:
            if portfolio_debug:
                log.info(f"[PORTFOLIO_SNAPSHOT] request_id={request_id} No fresh snapshot available, fetching live data...")
            snapshot = fetch_live_portfolio_snapshot(db)
            # Store it for next time
            try:
                store_portfolio_snapshot(db, snapshot)
            except Exception as store_err:
                log.warning(f"Could not store snapshot: {store_err}")
        
        # Transform snapshot to the requested format
        positions = []
        for asset in snapshot.get("assets", []):
            symbol = asset.get("symbol") or asset.get("coin") or asset.get("currency", "")
            free = float(asset.get("free", 0) or 0)
            locked = float(asset.get("locked", 0) or 0)
            total = float(asset.get("total") or asset.get("balance") or 0)
            price_usd = asset.get("price_usd") or asset.get("price") or 0.0
            value_usd = asset.get("value_usd") or asset.get("usd_value") or 0.0
            source = asset.get("source", "crypto_com")
            
            # Only include positions with quantity > 0
            if total > 0:
                positions.append({
                    "asset": symbol,
                    "free": free,
                    "locked": locked,
                    "total": total,
                    "price_usd": price_usd if price_usd > 0 else 0.0,
                    "value_usd": value_usd,
                    "source": source,  # Legacy field
                    "price_source": source  # Preferred field name
                })
        
        # Build message
        if len(positions) == 0:
            message = "No balances found"
        else:
            message = f"Portfolio snapshot: {len(positions)} positions"
        if used_pair_name:
            message += f" (Using {used_pair_name})"
        
        # Always set portfolio_source to crypto_com for real API data
        portfolio_source = "crypto_com"
        
        # Build response
        response = {
            "ok": True,
            "as_of": snapshot.get("as_of", datetime.now(timezone.utc).isoformat()),
            "exchange": exchange,
            "message": message,
            "portfolio_source": portfolio_source,
            "missing_env": [],
            "positions": positions,
            "totals": {
                "total_value_usd": float(snapshot.get("total_value_usd", 0.0)),
                "total_assets_usd": float(snapshot.get("total_assets_usd", 0.0)),
                "total_borrowed_usd": float(snapshot.get("total_borrowed_usd", 0.0)),
                "total_collateral_usd": float(snapshot.get("total_collateral_usd", 0.0))
            },
            "errors": errors
        }
        
        # Debug logging only when explicitly enabled
        if portfolio_debug:
            log.info(f"[PORTFOLIO_SNAPSHOT] Snapshot: {len(positions)} positions, "
                    f"total_value=${response['totals']['total_value_usd']:,.2f}")
            if positions:
                log.info(f"[PORTFOLIO_SNAPSHOT] Top 3 positions: {positions[:3]}")
        
        return response
    
    except ValueError as e:
        # Credentials not configured - already handled above, but catch for safety
        error_msg = str(e)
        if "40101" in error_msg:
            message = "Crypto.com auth failed (40101). Check API key/secret and IP allowlist."
        else:
            message = error_msg
        
        log.warning(f"[PORTFOLIO_SNAPSHOT] Cannot fetch portfolio snapshot: {error_msg}")
        return {
            "ok": False,
            "as_of": datetime.now(timezone.utc).isoformat(),
            "exchange": exchange,
            "message": message,
            "missing_env": missing_env if missing_env else [],
            "positions": [],
            "totals": {
                "total_value_usd": 0.0,
                "total_assets_usd": 0.0,
                "total_borrowed_usd": 0.0,
                "total_collateral_usd": 0.0
            },
            "errors": [error_msg]
        }
    except RuntimeError as e:
        # API call failed - check for specific error types
        error_msg = str(e)
        errors_list = [error_msg]
        
        # Log the error with request context (safe, no secrets)
        log.warning(f"[PORTFOLIO_SNAPSHOT] request_id={request_id} API call failed: {error_msg[:200]}")
        
        # Check if this is an auth error (40101/40103) - try fallback only if explicitly enabled
        is_auth_error = "40101" in error_msg or "40103" in error_msg
        allow_fallback = os.getenv("ALLOW_PORTFOLIO_FALLBACK", "false").lower() == "true"
        is_local_env = is_local()
        
        # Try fallback ONLY if auth failed AND fallback is explicitly enabled AND we're in local environment
        if is_auth_error and allow_fallback and is_local_env:
            from app.services.portfolio_fallback import get_fallback_holdings, build_fallback_positions
            
            fallback_holdings, fallback_source = get_fallback_holdings(db)
            
            if fallback_holdings:
                log.info(f"[PORTFOLIO_SNAPSHOT] Auth failed, using fallback source: {fallback_source}")
                
                # Build positions from fallback holdings
                positions = build_fallback_positions(db, fallback_holdings, fallback_source)
                
                # Calculate totals
                total_value_usd = sum(p["value_usd"] for p in positions)
                total_assets_usd = total_value_usd
                
                # Build message
                if fallback_source == "derived_trades":
                    message = f"Crypto.com auth failed (40101). Using derived_trades balances"
                elif fallback_source == "local_file":
                    message = f"Crypto.com auth failed (40101). Using local_file balances"
                else:
                    message = f"Crypto.com auth failed (40101). Using {fallback_source} balances"
                
                # Short error message (not blocking)
                short_error = "40101" if "40101" in error_msg else "40103" if "40103" in error_msg else "auth_failed"
                errors_list = [f"auth_error: {short_error}"]
                
                response = {
                    "ok": True,  # Still return ok=true when fallback works
                    "as_of": datetime.now(timezone.utc).isoformat(),
                    "exchange": exchange,
                    "message": message,
                    "portfolio_source": fallback_source,  # Add source field
                    "missing_env": [],
                    "positions": positions,
                    "totals": {
                        "total_value_usd": total_value_usd,
                        "total_assets_usd": total_assets_usd,
                        "total_borrowed_usd": 0.0,
                        "total_collateral_usd": 0.0
                    },
                    "errors": errors_list
                }
                
                # Add price errors if any
                price_errors = [p.get("price_source") == "none" for p in positions if p.get("price_source") == "none"]
                if any(price_errors):
                    errors_list.append("Some assets missing prices")
                
                return response
        
        # No fallback available or not local - return error
        if "40101" in error_msg:
            message = "Crypto.com auth failed (40101). Check API key/secret and IP allowlist in AWS Secrets/ENV."
            if is_local_env and not allow_fallback:
                message += " If you intended local fallback, set ALLOW_PORTFOLIO_FALLBACK=true locally."
        elif "40103" in error_msg:
            message = "Crypto.com IP not whitelisted (40103). Add server IP to API key allowlist in AWS."
        elif "network_error:" in error_msg or "Networking issue" in error_msg:
            message = f"Networking issue: {error_msg}. Try USE_CRYPTO_PROXY=true or check VPN."
            # Extract network error for errors array
            if "network_error:" in error_msg:
                errors_list = [error_msg.split("network_error:")[-1].strip()]
        else:
            message = f"Failed to fetch portfolio from Crypto.com: {error_msg}"
        
        log.error(f"[PORTFOLIO_SNAPSHOT] Error getting portfolio snapshot: {error_msg}", exc_info=True)
        return {
            "ok": False,
            "as_of": datetime.now(timezone.utc).isoformat(),
            "exchange": exchange,
            "message": message,
            "missing_env": [],
            "positions": [],
            "totals": {
                "total_value_usd": 0.0,
                "total_assets_usd": 0.0,
                "total_borrowed_usd": 0.0,
                "total_collateral_usd": 0.0
            },
            "errors": errors_list
        }
    except Exception as e:
        log.error(f"[PORTFOLIO_SNAPSHOT] Error getting portfolio snapshot: {e}", exc_info=True)
        return {
            "ok": False,
            "as_of": datetime.now(timezone.utc).isoformat(),
            "exchange": exchange,
            "message": f"Failed to fetch portfolio snapshot: {str(e)}",
            "missing_env": [],
            "positions": [],
            "totals": {
                "total_value_usd": 0.0,
                "total_assets_usd": 0.0,
                "total_borrowed_usd": 0.0,
                "total_collateral_usd": 0.0
            },
            "errors": [str(e)]
        }

