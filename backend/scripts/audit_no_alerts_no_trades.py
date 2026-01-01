#!/usr/bin/env python3
"""
Audit script to diagnose why NO Telegram alerts and NO buy/sell orders have been sent for days.

This script performs a comprehensive end-to-end audit of:
- Backend scheduler/monitor loop
- Dashboard config state (watchlist items)
- Throttle/cooldown state (alerts + price-move bucket)
- Trade guardrails (max open orders, cooldown, trade_enabled, trade_amount_usd, balance, mode)
- Telegram notifier health
- Market data freshness (price updates)
- Deployment/runtime config (env vars)

Usage:
    python backend/scripts/audit_no_alerts_no_trades.py [--since-hours 168] [--symbols ETH_USDT,BTC_USD] [--mode dry|live]
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add backend to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

import logging
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
from app.models.signal_throttle import SignalThrottleState
from app.models.market_price import MarketPrice, MarketData
from app.models.telegram_message import TelegramMessage
from app.services.signal_monitor import signal_monitor_service
from app.services.telegram_notifier import telegram_notifier
from app.services.scheduler import trading_scheduler
from app.services.signal_throttle import (
    fetch_signal_states,
    build_strategy_key,
    SignalThrottleConfig,
)
from app.services.strategy_profiles import resolve_strategy_profile
from app.api.routes_signals import get_signals
from app.services.order_position_service import count_total_open_positions
from app.core.runtime import get_runtime_origin

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Canonical reason codes
SKIP_NO_SIGNAL = "SKIP_NO_SIGNAL"
SKIP_ALERT_DISABLED = "SKIP_ALERT_DISABLED"
SKIP_TRADE_DISABLED = "SKIP_TRADE_DISABLED"
SKIP_INVALID_TRADE_AMOUNT = "SKIP_INVALID_TRADE_AMOUNT"
SKIP_COOLDOWN_ACTIVE = "SKIP_COOLDOWN_ACTIVE"
SKIP_MAX_OPEN_ORDERS = "SKIP_MAX_OPEN_ORDERS"
SKIP_RECENT_ORDER_COOLDOWN = "SKIP_RECENT_ORDER_COOLDOWN"
SKIP_TELEGRAM_FAILURE = "SKIP_TELEGRAM_FAILURE"
SKIP_MARKET_DATA_STALE = "SKIP_MARKET_DATA_STALE"
SKIP_SCHEDULER_NOT_RUNNING = "SKIP_SCHEDULER_NOT_RUNNING"
SKIP_CONFIG_NOT_APPLIED = "SKIP_CONFIG_NOT_APPLIED"
SKIP_NO_PRICE = "SKIP_NO_PRICE"
EXEC_ALERT_SENT = "EXEC_ALERT_SENT"
EXEC_ORDER_PLACED = "EXEC_ORDER_PLACED"

# Open order statuses that count toward open positions limit
# Only includes enum members that actually exist (PENDING does not exist)
OPEN_STATUSES = [OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED]


class AuditResult:
    """Container for audit results"""
    def __init__(self):
        self.global_status = "PASS"
        self.global_checks = {}
        self.symbol_results = []
        self.root_causes = []
        self.recommended_fixes = []


def check_scheduler_health(since_hours: int) -> Dict:
    """Check if scheduler is running and healthy"""
    result = {
        "status": "PASS",
        "is_running": False,
        "last_cycle": None,
        "stalled": False,
        "evidence": []
    }
    
    try:
        # Check signal monitor service
        is_running = signal_monitor_service.is_running
        result["is_running"] = is_running
        result["signal_monitor_running"] = is_running
        
        if not is_running:
            result["status"] = "FAIL"
            result["evidence"].append("SignalMonitorService.is_running = False")
        
        # Check last run timestamp
        last_run = signal_monitor_service.last_run_at
        if last_run:
            result["last_cycle"] = last_run.isoformat()
            now = datetime.now(timezone.utc)
            elapsed = (now - last_run).total_seconds() / 3600  # hours
            
            # Check if stalled (no cycle in 2x monitor_interval)
            monitor_interval = signal_monitor_service.monitor_interval
            stalled_threshold = (monitor_interval * 2) / 3600  # hours
            if elapsed > stalled_threshold:
                result["stalled"] = True
                result["status"] = "FAIL"
                result["evidence"].append(
                    f"Last cycle was {elapsed:.1f}h ago (threshold: {stalled_threshold:.1f}h)"
                )
        else:
            result["status"] = "FAIL"
            result["evidence"].append("No last_run_at timestamp found")
        
        # Check scheduler task
        if hasattr(trading_scheduler, 'running'):
            result["scheduler_running"] = trading_scheduler.running
            if not trading_scheduler.running:
                result["evidence"].append("TradingScheduler.running = False")
        
    except Exception as e:
        result["status"] = "FAIL"
        result["evidence"].append(f"Error checking scheduler: {e}")
    
    return result


def check_telegram_health(since_hours: int, db: Session) -> Dict:
    """Check Telegram notifier health"""
    result = {
        "status": "PASS",
        "bot_token_present": False,
        "chat_id_present": False,
        "enabled": False,
        "last_send": None,
        "recent_errors": [],
        "evidence": []
    }
    
    try:
        # Check credentials
        result["bot_token_present"] = bool(telegram_notifier.bot_token)
        result["chat_id_present"] = bool(telegram_notifier.chat_id)
        result["enabled"] = telegram_notifier.enabled
        
        if not telegram_notifier.bot_token:
            result["status"] = "FAIL"
            result["evidence"].append("TELEGRAM_BOT_TOKEN not set")
        
        if not telegram_notifier.chat_id:
            result["status"] = "FAIL"
            result["evidence"].append("TELEGRAM_CHAT_ID_AWS not set (or ENVIRONMENT != aws)")
        
        if not telegram_notifier.enabled:
            result["status"] = "FAIL"
            result["evidence"].append("Telegram notifier disabled (ENVIRONMENT != aws or missing credentials)")
        
        # Check environment
        environment = os.getenv("ENVIRONMENT", "").lower()
        if environment != "aws":
            result["status"] = "FAIL"
            result["evidence"].append(f"ENVIRONMENT={environment} (must be 'aws' for Telegram)")
        
        # Try to find last successful send from monitoring table
        try:
            since_time = datetime.now(timezone.utc) - timedelta(hours=since_hours)
            last_msg = db.query(TelegramMessage).filter(
                TelegramMessage.blocked == False,
                TelegramMessage.created_at >= since_time
            ).order_by(TelegramMessage.created_at.desc()).first()
            
            if last_msg:
                result["last_send"] = last_msg.created_at.isoformat()
            else:
                result["evidence"].append(f"No successful Telegram sends in last {since_hours}h")
        except Exception as e:
            logger.debug(f"Could not query TelegramMessage: {e}")
        
    except Exception as e:
        result["status"] = "FAIL"
        result["evidence"].append(f"Error checking Telegram: {e}")
    
    return result


def check_market_data_freshness(symbols: Optional[List[str]], since_hours: int, db: Session) -> Dict:
    """Check if market data is fresh"""
    result = {
        "status": "PASS",
        "stale_symbols": [],
        "missing_symbols": [],
        "evidence": []
    }
    
    try:
        stale_threshold = timedelta(minutes=30)  # 30 minutes
        now = datetime.now(timezone.utc)
        
        if symbols:
            query_symbols = symbols
        else:
            # Get all watchlist symbols
            watchlist_items = db.query(WatchlistItem).filter(
                WatchlistItem.is_deleted == False
            ).all()
            query_symbols = [item.symbol for item in watchlist_items]
        
        for symbol in query_symbols:
            market_price = db.query(MarketPrice).filter(
                MarketPrice.symbol == symbol
            ).first()
            
            if not market_price or not market_price.updated_at:
                result["missing_symbols"].append(symbol)
                continue
            
            # Check if stale
            updated_at = market_price.updated_at
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            
            age = now - updated_at
            if age > stale_threshold:
                result["stale_symbols"].append({
                    "symbol": symbol,
                    "last_update": updated_at.isoformat(),
                    "age_minutes": age.total_seconds() / 60
                })
        
        if result["stale_symbols"]:
            result["status"] = "FAIL"
            result["evidence"].append(
                f"{len(result['stale_symbols'])} symbols with stale prices (>30min old)"
            )
        
        if result["missing_symbols"]:
            result["status"] = "FAIL"
            result["evidence"].append(
                f"{len(result['missing_symbols'])} symbols missing price data"
            )
        
    except Exception as e:
        result["status"] = "FAIL"
        result["evidence"].append(f"Error checking market data: {e}")
    
    return result


def check_throttle_sanity(since_hours: int, db: Session) -> Dict:
    """Check throttle system for stuck entries"""
    result = {
        "status": "PASS",
        "throttled_count": 0,
        "stuck_entries": [],
        "evidence": []
    }
    
    try:
        now = datetime.now(timezone.utc)
        # Throttle entries older than cooldown*2 but still blocking
        stuck_threshold = timedelta(seconds=120)  # 2x the 60s cooldown
        
        all_throttles = db.query(SignalThrottleState).all()
        result["throttled_count"] = len(all_throttles)
        
        for throttle in all_throttles:
            if throttle.last_time:
                last_time = throttle.last_time
                if last_time.tzinfo is None:
                    last_time = last_time.replace(tzinfo=timezone.utc)
                
                age = now - last_time
                # If last_time is older than 2 minutes but we're still throttling, it's stuck
                if age > stuck_threshold:
                    result["stuck_entries"].append({
                        "symbol": throttle.symbol,
                        "side": throttle.side,
                        "strategy_key": throttle.strategy_key,
                        "last_time": last_time.isoformat(),
                        "age_seconds": age.total_seconds(),
                        "force_next_signal": getattr(throttle, 'force_next_signal', False)
                    })
        
        if result["stuck_entries"]:
            result["status"] = "WARN"
            result["evidence"].append(
                f"{len(result['stuck_entries'])} throttle entries older than 2min (may be normal if no signals)"
            )
        
    except Exception as e:
        result["status"] = "FAIL"
        result["evidence"].append(f"Error checking throttles: {e}")
    
    return result


def check_trade_system_sanity(db: Session) -> Dict:
    """Check trade system guardrails"""
    result = {
        "status": "PASS",
        "max_open_orders": signal_monitor_service.MAX_OPEN_ORDERS_PER_SYMBOL,
        "total_open_orders": 0,
        "symbols_at_limit": [],
        "evidence": []
    }
    
    try:
        # Count total open positions
        total_open = count_total_open_positions(db)
        result["total_open_orders"] = total_open
        
        # Check per-symbol limits
        watchlist_items = db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == False
        ).all()
        
        for item in watchlist_items:
            symbol = item.symbol
            # Count open orders for this symbol
            open_orders = db.query(ExchangeOrder).filter(
                ExchangeOrder.symbol == symbol,
                ExchangeOrder.status.in_(OPEN_STATUSES)
            ).count()
            
            if open_orders >= result["max_open_orders"]:
                result["symbols_at_limit"].append({
                    "symbol": symbol,
                    "open_orders": open_orders,
                    "limit": result["max_open_orders"]
                })
        
        if result["symbols_at_limit"]:
            result["status"] = "WARN"
            result["evidence"].append(
                f"{len(result['symbols_at_limit'])} symbols at open orders limit"
            )
        
    except Exception as e:
        result["status"] = "FAIL"
        result["evidence"].append(f"Error checking trade system: {e}")
    
    return result


def analyze_symbol(
    symbol: str,
    watchlist_item: WatchlistItem,
    db: Session,
    now_utc: datetime
) -> Dict:
    """Analyze a single symbol and determine why alerts/trades are blocked"""
    result = {
        "symbol": symbol,
        "alert_enabled": getattr(watchlist_item, "alert_enabled", False),
        "trade_enabled": getattr(watchlist_item, "trade_enabled", False),
        "buy_alert_enabled": getattr(watchlist_item, "buy_alert_enabled", False),
        "sell_alert_enabled": getattr(watchlist_item, "sell_alert_enabled", False),
        "trade_amount_usd": getattr(watchlist_item, "trade_amount_usd", None),
        "current_price": None,
        "last_price_update": None,
        "signal_buy": False,
        "signal_sell": False,
        "strategy_id": None,
        "strategy_key": None,
        "alert_decision": "SKIP",
        "alert_reason": SKIP_NO_SIGNAL,
        "alert_blocked_by": None,
        "price_move_decision": "SKIP",
        "price_move_reason": SKIP_NO_SIGNAL,
        "trade_decision": "SKIP",
        "trade_reason": SKIP_NO_SIGNAL,
        "trade_blocked_by": None,
        "evidence": {}
    }
    
    try:
        # Get current price
        market_price = db.query(MarketPrice).filter(
            MarketPrice.symbol == symbol
        ).first()
        
        if market_price:
            result["current_price"] = float(market_price.price) if market_price.price else None
            result["last_price_update"] = market_price.updated_at.isoformat() if market_price.updated_at else None
            
            # Check if stale
            if market_price.updated_at:
                updated_at = market_price.updated_at
                if updated_at.tzinfo is None:
                    updated_at = updated_at.replace(tzinfo=timezone.utc)
                age_minutes = (now_utc - updated_at).total_seconds() / 60
                if age_minutes > 30:
                    result["alert_reason"] = SKIP_MARKET_DATA_STALE
                    result["alert_blocked_by"] = SKIP_MARKET_DATA_STALE
                    result["evidence"]["price_age_minutes"] = age_minutes
                    return result
        
        if not result["current_price"] or result["current_price"] <= 0:
            result["alert_reason"] = SKIP_NO_PRICE
            result["alert_blocked_by"] = SKIP_NO_PRICE
            result["evidence"]["no_price"] = True
            return result
        
        # Get strategy
        strategy_type, risk_approach = resolve_strategy_profile(symbol, db, watchlist_item)
        strategy_key = build_strategy_key(strategy_type, risk_approach)
        result["strategy_key"] = strategy_key
        result["strategy_id"] = getattr(watchlist_item, "strategy_id", None)
        
        # Get signals
        try:
            signals = get_signals(symbol, db)
            result["signal_buy"] = signals.get("buy", False)
            result["signal_sell"] = signals.get("sell", False)
        except Exception as e:
            logger.debug(f"Error getting signals for {symbol}: {e}")
        
        # Check alert decision
        if not result["alert_enabled"]:
            result["alert_reason"] = SKIP_ALERT_DISABLED
            result["alert_blocked_by"] = SKIP_ALERT_DISABLED
        elif not result["signal_buy"] and not result["signal_sell"]:
            result["alert_reason"] = SKIP_NO_SIGNAL
            result["alert_blocked_by"] = SKIP_NO_SIGNAL
        else:
            # Check throttle for BUY
            if result["signal_buy"] and result["buy_alert_enabled"]:
                throttle_states = fetch_signal_states(db, symbol=symbol, strategy_key=strategy_key)
                buy_snapshot = throttle_states.get("BUY")
                
                if buy_snapshot and buy_snapshot.timestamp:
                    last_time = buy_snapshot.timestamp
                    if last_time.tzinfo is None:
                        last_time = last_time.replace(tzinfo=timezone.utc)
                    elapsed_seconds = (now_utc - last_time).total_seconds()
                    
                    if elapsed_seconds < 60.0:
                        result["alert_reason"] = SKIP_COOLDOWN_ACTIVE
                        result["alert_blocked_by"] = f"{SKIP_COOLDOWN_ACTIVE} ({60.0 - elapsed_seconds:.1f}s remaining)"
                        result["evidence"]["cooldown_remaining"] = 60.0 - elapsed_seconds
                    else:
                        # Check price change
                        min_pct = getattr(watchlist_item, "min_price_change_pct", 1.0) or 1.0
                        if buy_snapshot.price and buy_snapshot.price > 0:
                            price_change_pct = abs((result["current_price"] - buy_snapshot.price) / buy_snapshot.price * 100)
                            if price_change_pct < min_pct:
                                result["alert_reason"] = SKIP_COOLDOWN_ACTIVE
                                result["alert_blocked_by"] = f"PRICE_GATE ({price_change_pct:.2f}% < {min_pct}%)"
                                result["evidence"]["price_change_pct"] = price_change_pct
                                result["evidence"]["min_price_change_pct"] = min_pct
                            else:
                                result["alert_decision"] = "EXEC"
                                result["alert_reason"] = EXEC_ALERT_SENT
                        else:
                            result["alert_decision"] = "EXEC"
                            result["alert_reason"] = EXEC_ALERT_SENT
                else:
                    result["alert_decision"] = "EXEC"
                    result["alert_reason"] = EXEC_ALERT_SENT
            
            # Check throttle for SELL
            if result["signal_sell"] and result["sell_alert_enabled"]:
                throttle_states = fetch_signal_states(db, symbol=symbol, strategy_key=strategy_key)
                sell_snapshot = throttle_states.get("SELL")
                
                if sell_snapshot and sell_snapshot.timestamp:
                    last_time = sell_snapshot.timestamp
                    if last_time.tzinfo is None:
                        last_time = last_time.replace(tzinfo=timezone.utc)
                    elapsed_seconds = (now_utc - last_time).total_seconds()
                    
                    if elapsed_seconds < 60.0:
                        if result["alert_reason"] == SKIP_NO_SIGNAL:
                            result["alert_reason"] = SKIP_COOLDOWN_ACTIVE
                            result["alert_blocked_by"] = f"{SKIP_COOLDOWN_ACTIVE} ({60.0 - elapsed_seconds:.1f}s remaining)"
                            result["evidence"]["cooldown_remaining"] = 60.0 - elapsed_seconds
                    else:
                        # Check price change
                        min_pct = getattr(watchlist_item, "min_price_change_pct", 1.0) or 1.0
                        if sell_snapshot.price and sell_snapshot.price > 0:
                            price_change_pct = abs((result["current_price"] - sell_snapshot.price) / sell_snapshot.price * 100)
                            if price_change_pct < min_pct:
                                if result["alert_reason"] == SKIP_NO_SIGNAL:
                                    result["alert_reason"] = SKIP_COOLDOWN_ACTIVE
                                    result["alert_blocked_by"] = f"PRICE_GATE ({price_change_pct:.2f}% < {min_pct}%)"
                                    result["evidence"]["price_change_pct"] = price_change_pct
                                    result["evidence"]["min_price_change_pct"] = min_pct
                            else:
                                if result["alert_decision"] != "EXEC":
                                    result["alert_decision"] = "EXEC"
                                    result["alert_reason"] = EXEC_ALERT_SENT
                        else:
                            if result["alert_decision"] != "EXEC":
                                result["alert_decision"] = "EXEC"
                                result["alert_reason"] = EXEC_ALERT_SENT
        
        # Check trade decision
        if not result["trade_enabled"]:
            result["trade_reason"] = SKIP_TRADE_DISABLED
            result["trade_blocked_by"] = SKIP_TRADE_DISABLED
        elif not result["trade_amount_usd"] or result["trade_amount_usd"] <= 0:
            result["trade_reason"] = SKIP_INVALID_TRADE_AMOUNT
            result["trade_blocked_by"] = SKIP_INVALID_TRADE_AMOUNT
        elif not result["signal_buy"]:
            result["trade_reason"] = SKIP_NO_SIGNAL
            result["trade_blocked_by"] = SKIP_NO_SIGNAL
        else:
            # Check open orders limit
            open_orders = db.query(ExchangeOrder).filter(
                ExchangeOrder.symbol == symbol,
                ExchangeOrder.status.in_(OPEN_STATUSES)
            ).count()
            
            if open_orders >= signal_monitor_service.MAX_OPEN_ORDERS_PER_SYMBOL:
                result["trade_reason"] = SKIP_MAX_OPEN_ORDERS
                result["trade_blocked_by"] = f"{SKIP_MAX_OPEN_ORDERS} ({open_orders}/{signal_monitor_service.MAX_OPEN_ORDERS_PER_SYMBOL})"
                result["evidence"]["open_orders"] = open_orders
                result["evidence"]["max_open_orders"] = signal_monitor_service.MAX_OPEN_ORDERS_PER_SYMBOL
            else:
                # Check if alert would be sent (trade follows alert logic)
                if result["alert_decision"] == "EXEC":
                    result["trade_decision"] = "EXEC"
                    result["trade_reason"] = EXEC_ORDER_PLACED
                else:
                    result["trade_reason"] = result["alert_reason"]
                    result["trade_blocked_by"] = result["alert_blocked_by"]
        
        # Price move decision (simplified - same as alert for now)
        result["price_move_decision"] = result["alert_decision"]
        result["price_move_reason"] = result["alert_reason"]
        
    except Exception as e:
        logger.error(f"Error analyzing {symbol}: {e}", exc_info=True)
        result["error"] = str(e)
    
    return result


def run_audit(since_hours: int = 168, symbols: Optional[List[str]] = None, mode: str = "dry") -> AuditResult:
    """Run the complete audit"""
    result = AuditResult()
    
    # Try to get database connection, but continue even if it fails
    db = None
    try:
        db = SessionLocal()
    except Exception as db_err:
        logger.warning(f"Could not connect to database: {db_err}")
        logger.info("Continuing with global checks only (no database-dependent checks)")
    
    try:
        now_utc = datetime.now(timezone.utc)
        
        # Global checks
        logger.info("Running global health checks...")
        result.global_checks["scheduler"] = check_scheduler_health(since_hours)
        
        if db:
            result.global_checks["telegram"] = check_telegram_health(since_hours, db)
            result.global_checks["market_data"] = check_market_data_freshness(symbols, since_hours, db)
            result.global_checks["throttle"] = check_throttle_sanity(since_hours, db)
            result.global_checks["trade_system"] = check_trade_system_sanity(db)
        else:
            result.global_checks["telegram"] = {
                "status": "WARN",
                "evidence": ["Database not available - cannot check Telegram message history"]
            }
            result.global_checks["market_data"] = {
                "status": "WARN",
                "evidence": ["Database not available - cannot check market data freshness"]
            }
            result.global_checks["throttle"] = {
                "status": "WARN",
                "evidence": ["Database not available - cannot check throttle state"]
            }
            result.global_checks["trade_system"] = {
                "status": "WARN",
                "evidence": ["Database not available - cannot check trade system"]
            }
        
        # Determine global status
        has_fail = any(c.get("status") == "FAIL" for c in result.global_checks.values())
        if has_fail:
            result.global_status = "FAIL"
        
        # Per-symbol analysis
        if db:
            logger.info("Running per-symbol analysis...")
            try:
                if symbols:
                    watchlist_items = db.query(WatchlistItem).filter(
                        WatchlistItem.symbol.in_(symbols),
                        WatchlistItem.is_deleted == False
                    ).all()
                else:
                    watchlist_items = db.query(WatchlistItem).filter(
                        WatchlistItem.is_deleted == False
                    ).all()
                
                for item in watchlist_items:
                    try:
                        symbol_result = analyze_symbol(item.symbol, item, db, now_utc)
                        result.symbol_results.append(symbol_result)
                    except Exception as symbol_err:
                        logger.error(f"Error analyzing {item.symbol}: {symbol_err}")
                        result.symbol_results.append({
                            "symbol": item.symbol,
                            "error": str(symbol_err),
                            "alert_reason": "ERROR",
                            "trade_reason": "ERROR"
                        })
            except Exception as query_err:
                logger.error(f"Error querying watchlist items: {query_err}")
                result.symbol_results.append({
                    "symbol": "ERROR",
                    "error": f"Could not query watchlist: {query_err}",
                    "alert_reason": "ERROR",
                    "trade_reason": "ERROR"
                })
        else:
            logger.warning("Skipping per-symbol analysis (database not available)")
            result.symbol_results.append({
                "symbol": "N/A",
                "error": "Database not available",
                "alert_reason": "SKIP_DATABASE_UNAVAILABLE",
                "trade_reason": "SKIP_DATABASE_UNAVAILABLE"
            })
        
        # Identify root causes
        logger.info("Identifying root causes...")
        reason_counts = {}
        for symbol_result in result.symbol_results:
            alert_reason = symbol_result.get("alert_reason", SKIP_NO_SIGNAL)
            trade_reason = symbol_result.get("trade_reason", SKIP_NO_SIGNAL)
            
            if alert_reason not in [EXEC_ALERT_SENT]:
                reason_counts[alert_reason] = reason_counts.get(alert_reason, 0) + 1
            if trade_reason not in [EXEC_ORDER_PLACED]:
                reason_counts[trade_reason] = reason_counts.get(trade_reason, 0) + 1
        
        # Sort by frequency
        sorted_reasons = sorted(reason_counts.items(), key=lambda x: x[1], reverse=True)
        result.root_causes = [{"reason": r, "count": c} for r, c in sorted_reasons[:10]]
        
        # Generate recommended fixes
        logger.info("Generating recommended fixes...")
        if result.global_checks["scheduler"]["status"] == "FAIL":
            result.recommended_fixes.append({
                "issue": "Scheduler not running",
                "fix": "Start SignalMonitorService via API endpoint or restart backend service",
                "file": "backend/app/main.py",
                "line": "277"
            })
        
        if result.global_checks["telegram"]["status"] == "FAIL":
            result.recommended_fixes.append({
                "issue": "Telegram notifier disabled",
                "fix": "Set ENVIRONMENT=aws and ensure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID_AWS are set",
                "file": "docker-compose.yml or environment variables",
                "line": "N/A"
            })
        
        if result.global_checks["market_data"]["status"] == "FAIL":
            result.recommended_fixes.append({
                "issue": "Market data stale",
                "fix": "Check market_updater.py is running and can reach external APIs",
                "file": "backend/market_updater.py",
                "line": "328"
            })
        
        # Check for common per-symbol issues
        disabled_alerts = sum(1 for r in result.symbol_results if not r.get("alert_enabled"))
        if disabled_alerts > 0:
            result.recommended_fixes.append({
                "issue": f"{disabled_alerts} symbols have alert_enabled=False",
                "fix": "Enable alerts in dashboard for symbols that should receive alerts",
                "file": "Dashboard UI",
                "line": "N/A"
            })
        
        no_signals = sum(1 for r in result.symbol_results if not r.get("signal_buy") and not r.get("signal_sell"))
        if no_signals > 0:
            result.recommended_fixes.append({
                "issue": f"{no_signals} symbols have no buy/sell signals",
                "fix": "Check signal calculation logic and market conditions",
                "file": "backend/app/api/routes_signals.py",
                "line": "N/A"
            })
        
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass
    
    return result


def generate_markdown_report(result: AuditResult, since_hours: int) -> str:
    """Generate markdown report"""
    lines = []
    lines.append("# No Alerts / No Trades Audit Report")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"**Since Hours:** {since_hours}")
    lines.append("")
    
    # Global status
    lines.append("## GLOBAL STATUS")
    lines.append("")
    status_emoji = "❌" if result.global_status == "FAIL" else "✅"
    lines.append(f"**{status_emoji} {result.global_status}**")
    lines.append("")
    
    # Global checks
    lines.append("### Global Health Checks")
    lines.append("")
    
    for check_name, check_result in result.global_checks.items():
        status = check_result.get("status", "UNKNOWN")
        status_emoji = "❌" if status == "FAIL" else "⚠️" if status == "WARN" else "✅"
        lines.append(f"#### {status_emoji} {check_name.upper()}")
        lines.append("")
        
        if check_name == "scheduler":
            lines.append(f"- **Running:** {check_result.get('is_running', False)}")
            lines.append(f"- **Last Cycle:** {check_result.get('last_cycle', 'N/A')}")
            lines.append(f"- **Stalled:** {check_result.get('stalled', False)}")
        elif check_name == "telegram":
            lines.append(f"- **Enabled:** {check_result.get('enabled', False)}")
            lines.append(f"- **Bot Token:** {'✅' if check_result.get('bot_token_present') else '❌'}")
            lines.append(f"- **Chat ID:** {'✅' if check_result.get('chat_id_present') else '❌'}")
            lines.append(f"- **Last Send:** {check_result.get('last_send', 'N/A')}")
        elif check_name == "market_data":
            lines.append(f"- **Stale Symbols:** {len(check_result.get('stale_symbols', []))}")
            lines.append(f"- **Missing Symbols:** {len(check_result.get('missing_symbols', []))}")
        elif check_name == "throttle":
            lines.append(f"- **Throttled Count:** {check_result.get('throttled_count', 0)}")
            lines.append(f"- **Stuck Entries:** {len(check_result.get('stuck_entries', []))}")
        elif check_name == "trade_system":
            lines.append(f"- **Total Open Orders:** {check_result.get('total_open_orders', 0)}")
            lines.append(f"- **Max Per Symbol:** {check_result.get('max_open_orders', 3)}")
            lines.append(f"- **Symbols At Limit:** {len(check_result.get('symbols_at_limit', []))}")
        
        if check_result.get("evidence"):
            lines.append("")
            lines.append("**Evidence:**")
            for evidence in check_result["evidence"]:
                lines.append(f"- {evidence}")
        
        lines.append("")
    
    # Per-symbol table
    lines.append("## PER-SYMBOL ANALYSIS")
    lines.append("")
    lines.append("| Symbol | Alert Enabled | Trade Enabled | Price | Signal | Alert Decision | Alert Reason | Trade Decision | Trade Reason |")
    lines.append("|--------|--------------|---------------|-------|--------|----------------|--------------|----------------|--------------|")
    
    for symbol_result in result.symbol_results:
        symbol = symbol_result["symbol"]
        alert_enabled = "✅" if symbol_result.get("alert_enabled") else "❌"
        trade_enabled = "✅" if symbol_result.get("trade_enabled") else "❌"
        price = f"${symbol_result.get('current_price', 0):.4f}" if symbol_result.get("current_price") else "N/A"
        signal = "BUY" if symbol_result.get("signal_buy") else "SELL" if symbol_result.get("signal_sell") else "NONE"
        alert_decision = symbol_result.get("alert_decision", "SKIP")
        alert_reason = symbol_result.get("alert_reason", SKIP_NO_SIGNAL)
        trade_decision = symbol_result.get("trade_decision", "SKIP")
        trade_reason = symbol_result.get("trade_reason", SKIP_NO_SIGNAL)
        
        lines.append(
            f"| {symbol} | {alert_enabled} | {trade_enabled} | {price} | {signal} | "
            f"{alert_decision} | {alert_reason} | {trade_decision} | {trade_reason} |"
        )
    
    lines.append("")
    
    # Root causes
    lines.append("## ROOT CAUSES")
    lines.append("")
    lines.append("Ranked by frequency:")
    lines.append("")
    for i, cause in enumerate(result.root_causes, 1):
        lines.append(f"{i}. **{cause['reason']}** - {cause['count']} occurrences")
    lines.append("")
    
    # Recommended fixes
    lines.append("## RECOMMENDED FIXES")
    lines.append("")
    for fix in result.recommended_fixes:
        lines.append(f"### {fix['issue']}")
        lines.append("")
        lines.append(f"- **Fix:** {fix['fix']}")
        lines.append(f"- **File:** {fix['file']}")
        lines.append(f"- **Line:** {fix['line']}")
        lines.append("")
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Audit why no alerts/trades are being sent")
    parser.add_argument("--since-hours", type=int, default=168, help="Hours to look back (default: 168)")
    parser.add_argument("--symbols", type=str, help="Comma-separated list of symbols to check")
    parser.add_argument("--mode", choices=["dry", "live"], default="dry", help="Mode (default: dry)")
    parser.add_argument("--output", type=str, help="Output markdown file path")
    
    args = parser.parse_args()
    
    symbols = None
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
    
    logger.info(f"Running audit (since_hours={args.since_hours}, symbols={symbols}, mode={args.mode})")
    
    result = run_audit(since_hours=args.since_hours, symbols=symbols, mode=args.mode)
    
    # Print summary
    print("\n" + "=" * 80)
    print(f"GLOBAL STATUS: {result.global_status}")
    print("=" * 80)
    
    for check_name, check_result in result.global_checks.items():
        status = check_result.get("status", "UNKNOWN")
        print(f"{check_name.upper()}: {status}")
    
    print(f"\nAnalyzed {len(result.symbol_results)} symbols")
    print(f"Top root causes: {', '.join([c['reason'] for c in result.root_causes[:3]])}")
    
    # Generate markdown
    markdown = generate_markdown_report(result, args.since_hours)
    
    # Save to file
    output_path = args.output or "docs/reports/no-alerts-no-trades-audit.md"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(markdown)
    
    print(f"\nReport saved to: {output_path}")
    
    return 0 if result.global_status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())

