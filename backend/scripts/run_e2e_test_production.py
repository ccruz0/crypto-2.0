#!/usr/bin/env python3
"""
Production E2E Test Script

Exercises the real signal → order_intent → decision tracing pipeline
without requiring HTTP endpoint authentication.

This script:
1. Creates synthetic BUY and SELL signals (telegram_messages rows)
2. Calls the real orchestrator (create_order_intent)
3. Updates order_intent statuses
4. Updates decision tracing

Safe: dry_run mode only, never places real orders.
"""
import sys
import os
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.services.signal_order_orchestrator import create_order_intent, update_order_intent_status
from app.api.routes_monitoring import add_telegram_message, update_telegram_message_decision_trace
from app.utils.decision_reason import ReasonCode, make_execute, make_fail
import uuid
import json
from datetime import datetime, timezone


def run_e2e_test(symbol: str = None, dry_run: bool = True):
    """Run E2E test: create signals, order_intents, and decision traces."""
    db: Session = SessionLocal()
    try:
        # Select a test symbol
        test_item = None
        if symbol:
            test_item = db.query(WatchlistItem).filter(WatchlistItem.symbol == symbol).first()
        if not test_item:
            test_item = db.query(WatchlistItem).filter(WatchlistItem.trade_enabled.is_(True)).first()
        if not test_item:
            test_item = db.query(WatchlistItem).first()
        if not test_item:
            raise ValueError("No watchlist items available for diagnostics test.")
        
        symbol = test_item.symbol
        current_price = test_item.price or 1.0
        
        report = {
            "dry_run": dry_run,
            "symbol": symbol,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stages": [],
            "results": {},
        }
        
        for side in ("BUY", "SELL"):
            signal_text = f"[TEST] {side} SIGNAL: {symbol} @ ${current_price:.6f}"
            
            # Step 1: Create synthetic signal (telegram_messages row)
            signal_id = add_telegram_message(
                signal_text,
                symbol=symbol,
                blocked=False,
                throttle_status="SENT",
                throttle_reason="TEST_SIGNAL",
                db=db,
            )
            report["stages"].append({
                "stage": "signal_created",
                "side": side,
                "signal_id": signal_id,
                "message": signal_text
            })
            print(f"✅ Created {side} signal: signal_id={signal_id}")
            
            # Step 2: Create order intent (real orchestrator function)
            order_intent, intent_status = create_order_intent(
                db=db,
                signal_id=signal_id,
                symbol=symbol,
                side=side,
                message_content=signal_text,
            )
            report["stages"].append({
                "stage": "order_intent_created",
                "side": side,
                "intent_status": intent_status,
                "order_intent_id": order_intent.id if order_intent else None,
            })
            print(f"✅ Created order_intent: status={intent_status}, id={order_intent.id if order_intent else None}")
            
            # Step 3: Simulate outcome (dry_run mode)
            if order_intent:
                if side == "BUY":
                    # BUY: simulate success
                    outcome_status = "ORDER_PLACED"
                    order_id = f"dry_test_{uuid.uuid4().hex[:12]}"
                    update_order_intent_status(
                        db=db,
                        order_intent_id=order_intent.id,
                        status=outcome_status,
                        order_id=order_id,
                    )
                    decision_reason = make_execute(
                        reason_code=ReasonCode.EXEC_ORDER_PLACED.value,
                        message=f"Simulated {side} success (dry_run)",
                        context={"symbol": symbol, "side": side, "dry_run": True, "order_id": order_id},
                        source="diagnostics",
                    )
                else:  # SELL
                    # SELL: simulate failure
                    outcome_status = "ORDER_FAILED"
                    error_msg = f"Simulated {side} failure (dry_run)"
                    update_order_intent_status(
                        db=db,
                        order_intent_id=order_intent.id,
                        status=outcome_status,
                        error_message=error_msg,
                    )
                    decision_reason = make_fail(
                        reason_code=ReasonCode.EXCHANGE_ERROR_UNKNOWN.value,
                        message=error_msg,
                        context={"symbol": symbol, "side": side, "dry_run": True},
                        source="diagnostics",
                    )
                    # Create failure Telegram message
                    add_telegram_message(
                        f"❌ ORDER FAILED | {symbol} {side} | {error_msg}",
                        symbol=symbol,
                        blocked=False,
                        decision_type="FAILED",
                        reason_code=decision_reason.reason_code,
                        reason_message=decision_reason.reason_message,
                        db=db,
                    )
                
                # Update decision trace
                update_telegram_message_decision_trace(
                    db=db,
                    symbol=symbol,
                    message_pattern=f"{side} SIGNAL",
                    decision_type="EXECUTED" if outcome_status == "ORDER_PLACED" else "FAILED",
                    reason_code=decision_reason.reason_code,
                    reason_message=decision_reason.reason_message,
                    context_json=decision_reason.context,
                    correlation_id=str(uuid.uuid4()),
                )
                outcome = outcome_status
                print(f"✅ Updated order_intent: status={outcome_status}")
            else:
                outcome = intent_status or "NO_INTENT"
                print(f"⚠️ No order_intent created: status={intent_status}")
            
            report["results"][side] = {
                "signal_id": signal_id,
                "order_intent_id": order_intent.id if order_intent else None,
                "intent_status": intent_status,
                "outcome": outcome,
            }
        
        report["pass"] = all(
            result["outcome"] in ("ORDER_PLACED", "ORDER_FAILED")
            for result in report["results"].values()
        )
        
        return report
    finally:
        db.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run E2E test in production")
    parser.add_argument("--symbol", type=str, help="Symbol to test (optional)")
    args = parser.parse_args()
    
    try:
        report = run_e2e_test(symbol=args.symbol, dry_run=True)
        print("\n" + "="*60)
        print("E2E TEST REPORT")
        print("="*60)
        print(json.dumps(report, indent=2))
        print("="*60)
        sys.exit(0 if report["pass"] else 1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
