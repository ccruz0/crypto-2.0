#!/usr/bin/env python3
"""
Forensic Audit Script - Signal/Order/TP/SL Reconciliation

This script performs a comprehensive audit of the last 12 hours to identify
inconsistencies between Telegram signals, orders, and TP/SL orders.

Business Rules (Source of Truth):
BR-1: SIGNAL → ORDER (MANDATORY)
BR-2: ORDER UNIQUENESS  
BR-3: ORDER → TP/SL (MANDATORY IF STRATEGY REQUIRES IT)
BR-4: FAILURES MUST BE EXPLICIT
BR-5: NO GHOST ENTITIES
"""
import sys
import os
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
from app.database import SessionLocal
from app.models.telegram_message import TelegramMessage
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
from app.models.watchlist import WatchlistItem
import json
import re

# Classification categories
CATEGORY_OK = "C1: OK"
CATEGORY_SIGNAL_WITHOUT_ORDER = "C2: SIGNAL_WITHOUT_ORDER"
CATEGORY_ORDER_WITHOUT_SIGNAL = "C3: ORDER_WITHOUT_SIGNAL"
CATEGORY_ORDER_WITHOUT_TP_SL = "C4: ORDER_WITHOUT_TP_SL"
CATEGORY_PARTIAL_TP_SL = "C5: PARTIAL_TP_SL"
CATEGORY_SILENT_FAILURE = "C6: SILENT_FAILURE"
CATEGORY_DUPLICATE_ORDER = "C7: DUPLICATE_ORDER"
CATEGORY_UNKNOWN_STATE = "C8: UNKNOWN_STATE"

def extract_side_from_message(message: str) -> Optional[str]:
    """Extract BUY/SELL from Telegram message"""
    if not message:
        return None
    upper = message.upper()
    if "BUY SIGNAL" in upper or "🟢" in message or "ORDER_CREATED" in upper and "BUY" in upper:
        return "BUY"
    if "SELL SIGNAL" in upper or "🔴" in message or "🔻" in message or "SELL" in upper and "SIGNAL" in upper:
        return "SELL"
    return None

def extract_order_id_from_message(message: str) -> Optional[str]:
    """Extract order_id from Telegram message"""
    if not message:
        return None
    # Pattern: order_id=12345 or order_id=...
    match = re.search(r'order_id[=:]?\s*([A-Z0-9_-]+)', message, re.IGNORECASE)
    if match:
        return match.group(1)
    return None

def is_signal_message(message: str) -> bool:
    """Check if message is a BUY/SELL signal"""
    if not message:
        return False
    upper = message.upper()
    return "BUY SIGNAL" in upper or "SELL SIGNAL" in upper

def is_order_created_message(message: str) -> bool:
    """Check if message is ORDER_CREATED"""
    if not message:
        return False
    return "ORDER_CREATED" in message.upper()

def is_order_failed_message(message: str) -> bool:
    """Check if message is ORDER_FAILED"""
    if not message:
        return False
    return "ORDER_FAILED" in message.upper()

def is_sltp_failed_message(message: str) -> bool:
    """Check if message is SLTP_FAILED"""
    if not message:
        return False
    return "SLTP_FAILED" in message.upper() or "SL/TP FAILED" in message.upper()

def requires_sl_tp(symbol: str, db: Session) -> bool:
    """Check if strategy requires SL/TP for this symbol"""
    try:
        item = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == symbol.upper()
        ).first()
        if not item:
            return True  # Default: assume required
        # If trade_enabled, assume SL/TP required (conservative)
        return getattr(item, 'trade_enabled', False)
    except Exception:
        return True  # Default: assume required

def get_timeline_signals(db: Session, hours: int = 12) -> List[Dict[str, Any]]:
    """Get all Telegram signals from last N hours"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    
    signals = db.query(TelegramMessage).filter(
        and_(
            TelegramMessage.timestamp >= cutoff,
            or_(
                TelegramMessage.message.contains("BUY SIGNAL"),
                TelegramMessage.message.contains("SELL SIGNAL"),
            )
        )
    ).order_by(TelegramMessage.timestamp).all()
    
    result = []
    for sig in signals:
        side = extract_side_from_message(sig.message)
        if not side:
            continue
        
        result.append({
            'id': sig.id,
            'timestamp': sig.timestamp,
            'symbol': sig.symbol or 'UNKNOWN',
            'side': side,
            'message': sig.message,
            'blocked': sig.blocked,
            'order_skipped': sig.order_skipped,
            'decision_type': sig.decision_type,
            'reason_code': sig.reason_code,
            'reason_message': sig.reason_message,
            'exchange_error_snippet': sig.exchange_error_snippet,
            'context_json': sig.context_json,
        })
    
    return result

def get_timeline_orders(db: Session, hours: int = 12) -> List[Dict[str, Any]]:
    """Get all orders from last N hours"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    
    orders = db.query(ExchangeOrder).filter(
        ExchangeOrder.created_at >= cutoff
    ).order_by(ExchangeOrder.created_at).all()
    
    result = []
    for order in orders:
        result.append({
            'id': order.id,
            'exchange_order_id': order.exchange_order_id,
            'symbol': order.symbol,
            'side': order.side.value if hasattr(order.side, 'value') else str(order.side),
            'status': order.status.value if hasattr(order.status, 'value') else str(order.status),
            'order_role': order.order_role,
            'parent_order_id': order.parent_order_id,
            'created_at': order.created_at,
            'price': float(order.price) if order.price else None,
            'quantity': float(order.quantity) if order.quantity else None,
        })
    
    return result

def match_signal_to_order(signal: Dict, orders: List[Dict], time_window_minutes: int = 5) -> Optional[Dict]:
    """Match a signal to an order based on symbol, side, and timestamp"""
    signal_time = signal['timestamp']
    if not signal_time:
        return None
    
    signal_side = signal['side']
    signal_symbol = signal['symbol'].upper()
    
    # Try to extract order_id from message first
    order_id_from_msg = extract_order_id_from_message(signal['message'])
    if order_id_from_msg:
        for order in orders:
            if order['exchange_order_id'] == order_id_from_msg:
                return order
    
    # Match by symbol, side, and time window
    best_match = None
    min_time_diff = timedelta(minutes=time_window_minutes)
    
    for order in orders:
        if order['order_role'] in ['STOP_LOSS', 'TAKE_PROFIT']:
            continue  # Skip TP/SL orders
        
        if order['symbol'].upper() != signal_symbol:
            continue
        
        if order['side'].upper() != signal_side:
            continue
        
        order_time = order['created_at']
        if not order_time:
            continue
        
        time_diff = abs(order_time - signal_time)
        if time_diff < min_time_diff:
            min_time_diff = time_diff
            best_match = order
    
    return best_match

def get_tp_sl_for_order(order_id: str, orders: List[Dict]) -> Tuple[Optional[Dict], Optional[Dict]]:
    """Get TP and SL orders for a given parent order"""
    tp_order = None
    sl_order = None
    
    for order in orders:
        if order['parent_order_id'] == order_id:
            if order['order_role'] == 'TAKE_PROFIT':
                tp_order = order
            elif order['order_role'] == 'STOP_LOSS':
                sl_order = order
    
    return tp_order, sl_order

def classify_signal(
    signal: Dict,
    matched_order: Optional[Dict],
    all_orders: List[Dict],
    db: Session
) -> Tuple[str, List[str]]:
    """Classify a signal into inconsistency categories"""
    inconsistencies = []
    symbol = signal['symbol']
    side = signal['side']
    
    # C6: SILENT_FAILURE - Check if failure occurred without explicit reason
    if signal.get('decision_type') == 'FAILED':
        if not signal.get('reason_code') or not signal.get('reason_message'):
            return CATEGORY_SILENT_FAILURE, ["FAILED signal missing reason_code or reason_message"]
    elif signal.get('decision_type') == 'SKIPPED':
        # Check if skipped but no explicit reason
        if not signal.get('reason_code'):
            # DEDUP is allowed, but check if it's explicitly marked
            if 'DEDUP' not in (signal.get('reason_message') or '').upper():
                inconsistencies.append("SKIPPED signal missing reason_code")
    
    # C2: SIGNAL_WITHOUT_ORDER
    if not matched_order:
        # Check if it was explicitly skipped with a valid reason
        if signal.get('decision_type') == 'SKIPPED' and signal.get('reason_code'):
            reason = signal.get('reason_code', '').upper()
            # These are valid skip reasons (not violations)
            valid_skips = ['DEDUP', 'MAX_OPEN', 'COOLDOWN', 'TRADE_DISABLED', 'ALERT_DISABLED']
            if any(valid in reason for valid in valid_skips):
                # This is OK - explicitly skipped
                pass
            else:
                return CATEGORY_SIGNAL_WITHOUT_ORDER, ["Signal has no matching order and no valid skip reason"]
        else:
            return CATEGORY_SIGNAL_WITHOUT_ORDER, ["Signal has no matching order"]
    
    # Check order status
    order_status = matched_order.get('status', '').upper()
    if order_status in ['REJECTED', 'CANCELLED']:
        # Order was created but rejected/cancelled - check if failure was recorded
        if signal.get('decision_type') != 'FAILED':
            return CATEGORY_SILENT_FAILURE, [f"Order {order_status} but signal not marked as FAILED"]
    
    # C4 and C5: TP/SL checks (only for BUY orders that were FILLED)
    if side == 'BUY' and order_status == 'FILLED':
        if requires_sl_tp(symbol, db):
            tp_order, sl_order = get_tp_sl_for_order(matched_order['exchange_order_id'], all_orders)
            
            if not tp_order and not sl_order:
                return CATEGORY_ORDER_WITHOUT_TP_SL, ["FILLED BUY order missing both TP and SL"]
            elif not tp_order or not sl_order:
                missing = []
                if not tp_order:
                    missing.append("TP")
                if not sl_order:
                    missing.append("SL")
                return CATEGORY_PARTIAL_TP_SL, [f"FILLED BUY order missing {', '.join(missing)}"]
    
    # C1: OK
    return CATEGORY_OK, []

def classify_orphan_order(order: Dict, signals: List[Dict], time_window_minutes: int = 5) -> Tuple[str, List[str]]:
    """Classify an order that has no matching signal"""
    # C3: ORDER_WITHOUT_SIGNAL
    order_time = order['created_at']
    order_symbol = order['symbol'].upper()
    order_side = order['side'].upper()
    
    # Skip TP/SL orders (they have parent_order_id)
    if order.get('order_role') in ['STOP_LOSS', 'TAKE_PROFIT']:
        return CATEGORY_OK, []  # TP/SL orders don't need signals
    
    # Check if there's a matching signal
    for signal in signals:
        if signal['symbol'].upper() != order_symbol:
            continue
        if signal['side'].upper() != order_side:
            continue
        
        signal_time = signal['timestamp']
        if not signal_time:
            continue
        
        time_diff = abs(order_time - signal_time)
        if time_diff <= timedelta(minutes=time_window_minutes):
            return CATEGORY_OK, []  # Has matching signal
    
    return CATEGORY_ORDER_WITHOUT_SIGNAL, ["Order has no matching signal within time window"]

def check_duplicate_orders(orders: List[Dict], time_window_minutes: int = 1) -> List[Dict]:
    """Check for duplicate orders (same symbol, side, within time window)"""
    duplicates = []
    
    # Group orders by symbol and side
    orders_by_key = {}
    for order in orders:
        if order.get('order_role') in ['STOP_LOSS', 'TAKE_PROFIT']:
            continue  # Skip TP/SL
        
        key = (order['symbol'].upper(), order['side'].upper())
        if key not in orders_by_key:
            orders_by_key[key] = []
        orders_by_key[key].append(order)
    
    # Check for duplicates within time window
    for key, order_list in orders_by_key.items():
        if len(order_list) < 2:
            continue
        
        # Sort by time
        order_list.sort(key=lambda x: x['created_at'] or datetime.min.replace(tzinfo=timezone.utc))
        
        for i in range(len(order_list)):
            for j in range(i + 1, len(order_list)):
                order1 = order_list[i]
                order2 = order_list[j]
                
                time_diff = abs(order2['created_at'] - order1['created_at'])
                if time_diff <= timedelta(minutes=time_window_minutes):
                    duplicates.append({
                        'order1': order1,
                        'order2': order2,
                        'time_diff_seconds': time_diff.total_seconds(),
                        'category': CATEGORY_DUPLICATE_ORDER,
                        'inconsistencies': [f"Duplicate orders created within {time_diff.total_seconds():.0f} seconds"]
                    })
    
    return duplicates

def run_forensic_audit(db: Session, hours: int = 12) -> Dict[str, Any]:
    """Run the complete forensic audit"""
    print(f"🔍 Starting forensic audit for last {hours} hours...")
    
    # Get data
    signals = get_timeline_signals(db, hours)
    orders = get_timeline_orders(db, hours)
    
    print(f"   Found {len(signals)} signals and {len(orders)} orders")
    
    # Classify signals
    signal_classifications = []
    for signal in signals:
        matched_order = match_signal_to_order(signal, orders)
        category, inconsistencies = classify_signal(signal, matched_order, orders, db)
        signal_classifications.append({
            'signal': signal,
            'order': matched_order,
            'category': category,
            'inconsistencies': inconsistencies,
        })
    
    # Classify orphan orders
    orphan_orders = []
    for order in orders:
        if order.get('order_role') in ['STOP_LOSS', 'TAKE_PROFIT']:
            continue  # Skip TP/SL
        category, inconsistencies = classify_orphan_order(order, signals)
        if category != CATEGORY_OK:
            orphan_orders.append({
                'order': order,
                'category': category,
                'inconsistencies': inconsistencies,
            })
    
    # Check for duplicates
    duplicate_orders = check_duplicate_orders(orders)
    
    # Summary statistics
    category_counts = {}
    for item in signal_classifications:
        cat = item['category']
        category_counts[cat] = category_counts.get(cat, 0) + 1
    
    for item in orphan_orders:
        cat = item['category']
        category_counts[cat] = category_counts.get(cat, 0) + 1
    
    for item in duplicate_orders:
        cat = item['category']
        category_counts[cat] = category_counts.get(cat, 0) + 1
    
    return {
        'audit_window_hours': hours,
        'audit_timestamp': datetime.now(timezone.utc).isoformat(),
        'summary': {
            'total_signals': len(signals),
            'total_orders': len(orders),
            'category_counts': category_counts,
        },
        'signal_classifications': signal_classifications,
        'orphan_orders': orphan_orders,
        'duplicate_orders': duplicate_orders,
    }

def print_audit_report(audit_result: Dict[str, Any]):
    """Print a human-readable audit report"""
    print("\n" + "=" * 80)
    print("FORENSIC AUDIT REPORT")
    print("=" * 80)
    print(f"Audit Window: Last {audit_result['audit_window_hours']} hours")
    print(f"Audit Timestamp: {audit_result['audit_timestamp']}")
    print()
    
    summary = audit_result['summary']
    print("SUMMARY:")
    print(f"  Total Signals: {summary['total_signals']}")
    print(f"  Total Orders: {summary['total_orders']}")
    print()
    print("CATEGORY COUNTS:")
    for category, count in sorted(summary['category_counts'].items()):
        print(f"  {category}: {count}")
    print()
    
    # Show inconsistencies
    all_inconsistencies = []
    all_inconsistencies.extend(audit_result['signal_classifications'])
    all_inconsistencies.extend(audit_result['orphan_orders'])
    all_inconsistencies.extend(audit_result['duplicate_orders'])
    
    non_ok_items = [item for item in all_inconsistencies if item.get('category') != CATEGORY_OK]
    
    if non_ok_items:
        print(f"\nINCONSISTENCIES FOUND: {len(non_ok_items)}")
        print("-" * 80)
        
        for idx, item in enumerate(non_ok_items, 1):
            print(f"\n{idx}. {item['category']}")
            if 'signal' in item:
                sig = item['signal']
                print(f"   Signal ID: {sig['id']}")
                print(f"   Timestamp: {sig['timestamp']}")
                print(f"   Symbol: {sig['symbol']} | Side: {sig['side']}")
                print(f"   Message: {sig['message'][:100]}...")
            if 'order' in item:
                order = item['order']
                print(f"   Order ID: {order.get('exchange_order_id')}")
                print(f"   Timestamp: {order.get('created_at')}")
                print(f"   Symbol: {order.get('symbol')} | Side: {order.get('side')}")
            if 'order1' in item:
                print(f"   Order 1: {item['order1'].get('exchange_order_id')}")
                print(f"   Order 2: {item['order2'].get('exchange_order_id')}")
            print(f"   Inconsistencies: {', '.join(item['inconsistencies'])}")
    else:
        print("\n✅ NO INCONSISTENCIES FOUND - All signals and orders are consistent!")

def main():
    """Main entry point"""
    db = SessionLocal()
    try:
        audit_result = run_forensic_audit(db, hours=12)
        print_audit_report(audit_result)
        
        # Save to JSON file
        output_file = Path(__file__).parent / f"forensic_audit_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
        with open(output_file, 'w') as f:
            json.dump(audit_result, f, indent=2, default=str)
        print(f"\n📄 Full audit data saved to: {output_file}")
        
        return audit_result
    finally:
        db.close()

if __name__ == "__main__":
    main()
