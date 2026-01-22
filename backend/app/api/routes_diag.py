"""Diagnostic endpoints for Crypto.com authentication troubleshooting"""
from fastapi import APIRouter, Depends, HTTPException, Header, Query
from sqlalchemy.orm import Session
from app.database import get_db
import logging
from datetime import datetime, timezone
import time
import os
from typing import Optional, Dict, Any, List
from collections import defaultdict

logger = logging.getLogger(__name__)
router = APIRouter()


def _diagnostics_enabled():
    """Check if diagnostics endpoints are enabled."""
    env = os.getenv("ENVIRONMENT", "")
    debug = os.getenv("PORTFOLIO_DEBUG", "0")
    return env == "local" or debug == "1"

@router.get("/diag/crypto-auth")
def crypto_auth_diagnostic():
    """Public diagnostic endpoint to test Crypto.com authentication"""
    import os
    from app.services.brokers.crypto_com_trade import CryptoComTradeClient
    from app.utils.http_client import http_get, http_post
    
    results = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "server_time_epoch": time.time(),
        "outbound_ip": None,
        "credentials_status": {},
        "test_result": {}
    }
    
    # Get outbound IP
    try:
        results["outbound_ip"] = http_get("https://api.ipify.org", timeout=5, calling_module="routes_diag").text.strip()
        logger.info(f"[CRYPTO_AUTH_DIAG] CRYPTO_COM_OUTBOUND_IP: {results['outbound_ip']}")
    except Exception as e:
        logger.error(f"[CRYPTO_AUTH_DIAG] Failed to get outbound IP: {e}")
        results["outbound_ip"] = None
    
    # Check credentials
    api_key = os.getenv("EXCHANGE_CUSTOM_API_KEY", "").strip()
    api_secret = os.getenv("EXCHANGE_CUSTOM_API_SECRET", "").strip()
    
    results["credentials_status"] = {
        "api_key_set": bool(api_key),
        "api_key_length": len(api_key),
        "api_key_preview": f"{api_key[:4]}....{api_key[-4:]}" if len(api_key) >= 4 else "NOT_SET",
        "secret_set": bool(api_secret),
        "secret_length": len(api_secret),
        "secret_starts_with": api_secret[:6] if len(api_secret) >= 6 else "N/A",
        "secret_has_whitespace": any(c.isspace() for c in api_secret) if api_secret else False
    }
    
    # Try to make a test request
    if api_key and api_secret:
        try:
            client = CryptoComTradeClient()
            result = client.get_account_summary()
            
            if result and "accounts" in result:
                results["test_result"] = {
                    "success": True,
                    "accounts_count": len(result.get("accounts", [])),
                    "message": "Authentication successful"
                }
            else:
                results["test_result"] = {
                    "success": False,
                    "error": "No accounts in response",
                    "response": str(result)[:200]
                }
        except Exception as e:
            results["test_result"] = {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }
    else:
        results["test_result"] = {
            "success": False,
            "error": "Credentials not configured"
        }
    
    return results


@router.get("/diagnostics/whoami")
def whoami_diagnostic():
    """
    Safe diagnostic endpoint to identify which backend service is running.
    Gated by ENVIRONMENT=local or PORTFOLIO_DEBUG=1.
    Returns service info without exposing secrets.
    """
    # Gate by environment or debug flag
    if not _diagnostics_enabled():
        raise HTTPException(
            status_code=404,
            detail="Not found"
        )
    
    import platform
    import sys
    
    return {
        "service": "automated-trading-platform-backend",
        "environment": os.getenv("ENVIRONMENT", "unknown"),
        "python_version": sys.version,
        "platform": platform.platform(),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "server_time_epoch": time.time()
    }


@router.get("/diagnostics/watchlist-drift")
def watchlist_drift_diagnostic(db: Session = Depends(get_db)):
    """
    Diagnostic endpoint to detect drift between:
    - Watchlist state used by signal monitor (alert_enabled filtering)
    - Watchlist state returned by dashboard API
    - UI display assumptions
    
    This endpoint helps identify discrepancies that cause alerts to be blocked
    even though the UI shows alerts as enabled.
    
    Returns:
    {
        "timestamp": str,
        "summary": {
            "total_active_rows": int,
            "alert_enabled_true_count": int,
            "alert_enabled_false_count": int,
            "alert_enabled_null_count": int,
            "buy_alert_enabled_true_count": int,
            "sell_alert_enabled_true_count": int
        },
        "drift_issues": [
            {
                "symbol": str,
                "issue_type": str,
                "description": str,
                "details": dict
            }
        ],
        "sample_rows": [
            {
                "symbol": str,
                "alert_enabled": bool,
                "buy_alert_enabled": bool,
                "sell_alert_enabled": bool,
                "trade_enabled": bool,
                "is_deleted": bool
            }
        ]
    }
    """
    try:
        from app.models.watchlist import WatchlistItem
        
        # Get all active watchlist items
        items = db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == False
        ).all()
        
        # Calculate summary statistics
        total_active = len(items)
        alert_enabled_true = sum(1 for item in items if item.alert_enabled is True)
        alert_enabled_false = sum(1 for item in items if item.alert_enabled is False)
        alert_enabled_null = sum(1 for item in items if item.alert_enabled is None)
        
        buy_alert_enabled_true = sum(1 for item in items if getattr(item, 'buy_alert_enabled', None) is True)
        sell_alert_enabled_true = sum(1 for item in items if getattr(item, 'sell_alert_enabled', None) is True)
        
        # Detect drift issues
        drift_issues = []
        
        # Issue 1: alert_enabled=False but buy_alert_enabled or sell_alert_enabled is True
        for item in items:
            if item.alert_enabled is False:
                buy_enabled = getattr(item, 'buy_alert_enabled', False)
                sell_enabled = getattr(item, 'sell_alert_enabled', False)
                if buy_enabled or sell_enabled:
                    drift_issues.append({
                        "symbol": item.symbol,
                        "issue_type": "MASTER_DISABLED_BUT_SIDE_ENABLED",
                        "description": f"{item.symbol}: Master alert_enabled=False but side-specific alerts are enabled",
                        "details": {
                            "alert_enabled": False,
                            "buy_alert_enabled": buy_enabled,
                            "sell_alert_enabled": sell_enabled
                        }
                    })
        
        # Issue 2: alert_enabled is NULL (should be boolean)
        for item in items:
            if item.alert_enabled is None:
                drift_issues.append({
                    "symbol": item.symbol,
                    "issue_type": "ALERT_ENABLED_NULL",
                    "description": f"{item.symbol}: alert_enabled is NULL (should be True or False)",
                    "details": {
                        "alert_enabled": None
                    }
                })
        
        # Issue 3: Multiple active rows for same symbol (should be deduplicated)
        symbol_counts = defaultdict(list)
        for item in items:
            symbol_counts[item.symbol].append(item.id)
        
        for symbol, ids in symbol_counts.items():
            if len(ids) > 1:
                drift_issues.append({
                    "symbol": symbol,
                    "issue_type": "MULTIPLE_ACTIVE_ROWS",
                    "description": f"{symbol}: Multiple active rows found (IDs: {ids})",
                    "details": {
                        "row_ids": ids,
                        "row_count": len(ids)
                    }
                })
        
        # Sample rows (first 20)
        sample_rows = []
        for item in items[:20]:
            sample_rows.append({
                "symbol": item.symbol,
                "alert_enabled": item.alert_enabled,
                "buy_alert_enabled": getattr(item, 'buy_alert_enabled', None),
                "sell_alert_enabled": getattr(item, 'sell_alert_enabled', None),
                "trade_enabled": item.trade_enabled,
                "is_deleted": item.is_deleted
            })
        
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total_active_rows": total_active,
                "alert_enabled_true_count": alert_enabled_true,
                "alert_enabled_false_count": alert_enabled_false,
                "alert_enabled_null_count": alert_enabled_null,
                "buy_alert_enabled_true_count": buy_alert_enabled_true,
                "sell_alert_enabled_true_count": sell_alert_enabled_true
            },
            "drift_issues": drift_issues,
            "drift_issues_count": len(drift_issues),
            "sample_rows": sample_rows
        }
        
    except Exception as e:
        logger.error(f"Error in watchlist drift diagnostic: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Diagnostic error: {str(e)}"
        )


@router.get("/api/diagnostics/alerts_audit")
def alerts_audit_endpoint(
    db: Session = Depends(get_db),
    api_key: Optional[str] = Header(None, alias="X-API-Key")
):
    """
    Audit endpoint for alert configuration per symbol.
    
    Returns per-symbol alert configuration with source information.
    Protected by API key (DIAGNOSTICS_API_KEY env var).
    
    Returns:
    {
        "timestamp": str,
        "symbols": [
            {
                "symbol": str,
                "alert_enabled": bool,
                "alert_enabled_source": str,  # "db" | "not_found" | "error"
                "buy_alert_enabled": bool,
                "sell_alert_enabled": bool,
                "trade_enabled": bool,
                "min_trade_usd": float,
                "min_qty": Optional[float],
                "step_size": Optional[float],
                "cooldown_seconds": Optional[float],
                "last_alert_at": Optional[str],
                "symbol_normalized": str
            }
        ]
    }
    """
    # Check API key
    required_key = os.getenv("DIAGNOSTICS_API_KEY", "")
    if required_key and api_key != required_key:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key"
        )
    
    try:
        from app.models.watchlist import WatchlistItem
        from app.services.signal_monitor import SignalMonitorService
        from app.services.brokers.crypto_com_trade import trade_client
        from app.models.watchlist_signal_state import WatchlistSignalState
        
        # Get all active watchlist items
        items = db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == False
        ).all()
        
        signal_monitor = SignalMonitorService()
        results = []
        
        for item in items:
            symbol = item.symbol
            
            # Use centralized resolver
            alert_config = signal_monitor._resolve_alert_config(db, symbol)
            
            # Get instrument metadata for min_qty and step_size
            inst_meta = trade_client._get_instrument_metadata(symbol)
            min_qty = inst_meta.get("min_quantity") if inst_meta else None
            step_size = inst_meta.get("qty_tick_size") if inst_meta else None
            
            # Get last alert time from signal state
            signal_state = db.query(WatchlistSignalState).filter(
                WatchlistSignalState.symbol == symbol
            ).order_by(WatchlistSignalState.last_alert_at_utc.desc()).first()
            
            last_alert_at = None
            if signal_state and signal_state.last_alert_at_utc:
                last_alert_at = signal_state.last_alert_at_utc.isoformat()
            
            # Get cooldown from watchlist item
            cooldown_minutes = getattr(item, 'alert_cooldown_minutes', None)
            cooldown_seconds = cooldown_minutes * 60 if cooldown_minutes else None
            
            results.append({
                "symbol": symbol,
                "alert_enabled": alert_config["alert_enabled"],
                "alert_enabled_source": alert_config["source"],
                "buy_alert_enabled": alert_config["buy_alert_enabled"],
                "sell_alert_enabled": alert_config["sell_alert_enabled"],
                "trade_enabled": alert_config["trade_enabled"],
                "min_trade_usd": getattr(item, 'trade_amount_usd', None),
                "min_qty": min_qty,
                "step_size": step_size,
                "cooldown_seconds": cooldown_seconds,
                "last_alert_at": last_alert_at,
                "symbol_normalized": alert_config["symbol_normalized"]
            })
        
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbols": results
        }
        
    except Exception as e:
        logger.error(f"Error in alerts audit: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Audit error: {str(e)}"
        )
