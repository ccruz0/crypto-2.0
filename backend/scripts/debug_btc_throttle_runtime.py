#!/usr/bin/env python3
"""
BTC Throttle Runtime Stress Test

This script simulates the EXACT production code path to verify that BTC alerts
cannot bypass throttle. It uses the same evaluator, gatekeeper, and emit_alert
functions that AWS production uses.

Usage:
    python3 backend/scripts/debug_btc_throttle_runtime.py
"""
import sys
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.services.signal_evaluator import evaluate_signal_for_symbol
from app.services.throttle_gatekeeper import enforce_throttle
from app.services.alert_emitter import emit_alert
from app.services.signal_throttle import record_signal_event
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Mock Telegram sending for local testing
original_send_buy_signal = None
original_send_sell_signal = None


def mock_telegram_send():
    """Mock Telegram sending to avoid actual API calls during testing."""
    global original_send_buy_signal, original_send_sell_signal
    
    from app.services import telegram_notifier
    
    def mock_send_buy_signal(*args, **kwargs):
        logger.info("[MOCK_TELEGRAM] BUY alert would be sent (dry-run mode)")
        return True
    
    def mock_send_sell_signal(*args, **kwargs):
        logger.info("[MOCK_TELEGRAM] SELL alert would be sent (dry-run mode)")
        return True
    
    original_send_buy_signal = telegram_notifier.send_buy_signal
    original_send_sell_signal = telegram_notifier.send_sell_signal
    
    telegram_notifier.send_buy_signal = mock_send_buy_signal
    telegram_notifier.send_sell_signal = mock_send_sell_signal
    
    logger.info("✅ Telegram sending mocked for dry-run testing")


def restore_telegram_send():
    """Restore original Telegram sending functions."""
    global original_send_buy_signal, original_send_sell_signal
    
    if original_send_buy_signal and original_send_sell_signal:
        from app.services import telegram_notifier
        telegram_notifier.send_buy_signal = original_send_buy_signal
        telegram_notifier.send_sell_signal = original_send_sell_signal
        logger.info("✅ Telegram sending restored")


class TickResult:
    """Result of a single tick evaluation."""
    def __init__(
        self,
        tick_num: int,
        price: float,
        elapsed_seconds: float,
        price_delta_pct: float,
        decision: str,
        reason: str,
        throttle_allowed: bool,
        gatekeeper_allowed: bool,
        alert_emitted: bool,
    ):
        self.tick_num = tick_num
        self.price = price
        self.elapsed_seconds = elapsed_seconds
        self.price_delta_pct = price_delta_pct
        self.decision = decision
        self.reason = reason
        self.throttle_allowed = throttle_allowed
        self.gatekeeper_allowed = gatekeeper_allowed
        self.alert_emitted = alert_emitted
    
    def to_line(self) -> str:
        """Format as compact line for console output."""
        status = "✅ ALLOWED" if self.alert_emitted else "❌ BLOCKED"
        return (
            f"TICK {self.tick_num:2d} | {status:12s} | "
            f"price=${self.price:,.2f} | "
            f"elapsed={self.elapsed_seconds:5.1f}s | "
            f"delta%={self.price_delta_pct:6.2f}% | "
            f"reason={self.reason[:50]}"
        )


def simulate_btc_tick(
    db,
    tick_num: int,
    price: float,
    base_time: datetime,
    current_time: datetime,
    watchlist_item: WatchlistItem,
) -> TickResult:
    """
    Simulate a single BTC price tick through the production code path.
    
    Returns:
        TickResult with decision and reason
    """
    symbol = "BTC_USDT"
    
    # Fixed indicators for consistent testing
    rsi = 45.0  # Below buy threshold
    ma50 = price * 0.99  # Price above MA50
    ema10 = price * 0.98  # Price above EMA10
    ma200 = price * 0.95  # Price above MA200
    volume_ratio = 1.5  # Above threshold
    
    # Calculate elapsed time and price delta
    elapsed_seconds = (current_time - base_time).total_seconds()
    
    # Get last signal state to calculate price delta
    from app.services.signal_throttle import fetch_signal_states, build_strategy_key
    strategy_key = build_strategy_key(
        strategy_type="swing",
        risk_approach="conservative",
    )
    signal_states = fetch_signal_states(db, symbol=symbol, strategy_key=strategy_key)
    last_buy = signal_states.get("BUY")
    
    price_delta_pct = 0.0
    if last_buy and last_buy.price:
        price_delta_pct = abs((price - last_buy.price) / last_buy.price) * 100.0
    
    # Step 1: Evaluate signal using production evaluator
    # The evaluator gets price/indicators from DB, but we can inject them via MarketPrice/MarketData
    # For this test, we'll create MarketPrice and MarketData records in the DB
    from app.models.market_price import MarketPrice, MarketData
    
    # Create/update MarketPrice
    mp = db.query(MarketPrice).filter(MarketPrice.symbol == symbol).first()
    if not mp:
        mp = MarketPrice(symbol=symbol, price=price, volume_24h=0.0)
        db.add(mp)
    else:
        mp.price = price
        mp.volume_24h = 0.0
    
    # Create/update MarketData
    md = db.query(MarketData).filter(MarketData.symbol == symbol).first()
    if not md:
        md = MarketData(
            symbol=symbol,
            rsi=rsi,
            ma50=ma50,
            ema10=ema10,
            ma200=ma200,
        )
        db.add(md)
    else:
        md.rsi = rsi
        md.ma50 = ma50
        md.ema10 = ema10
        md.ma200 = ma200
    
    db.commit()
    
    # Evaluate using production evaluator (it will use our injected values)
    eval_result = evaluate_signal_for_symbol(
        db=db,
        watchlist_item=watchlist_item,
        symbol=symbol,
    )
    
    buy_allowed = eval_result.get("buy_allowed", False)
    throttle_reason = eval_result.get("throttle_reason_buy", "")
    throttle_metadata = eval_result.get("throttle_metadata_buy")
    can_emit_buy = eval_result.get("can_emit_buy_alert", False)
    
    # Step 2: Gatekeeper check (same as production)
    gatekeeper_allowed, gatekeeper_reason = enforce_throttle(
        symbol=symbol,
        side="BUY",
        current_price=price,
        throttle_allowed=buy_allowed,
        throttle_reason=throttle_reason or "No throttle check performed",
        throttle_metadata=throttle_metadata,
    )
    
    # Step 3: Emit alert if gatekeeper allows (same as production)
    alert_emitted = False
    if gatekeeper_allowed and can_emit_buy:
        try:
            reason_text = f"Test tick {tick_num} | RSI={rsi:.1f}, Price={price:.4f}"
            result = emit_alert(
                symbol=symbol,
                side="BUY",
                reason=reason_text,
                price=price,
                throttle_status="SENT" if buy_allowed else "BLOCKED",
                throttle_reason=throttle_reason,
                throttle_metadata=throttle_metadata,
            )
            alert_emitted = result
            
            # Record signal event (same as production)
            if alert_emitted:
                record_signal_event(
                    db,
                    symbol=symbol,
                    strategy_key=strategy_key,
                    side="BUY",
                    price=price,
                    source="alert",
                )
        except Exception as e:
            logger.error(f"Error emitting alert: {e}", exc_info=True)
    
    # Determine final decision
    if alert_emitted:
        decision = "ALERT"
        reason = gatekeeper_reason if gatekeeper_allowed else "Gatekeeper blocked"
    else:
        decision = "NO_ALERT"
        if not buy_allowed:
            reason = throttle_reason
        elif not gatekeeper_allowed:
            reason = gatekeeper_reason
        else:
            reason = "Other condition not met"
    
    return TickResult(
        tick_num=tick_num,
        price=price,
        elapsed_seconds=elapsed_seconds,
        price_delta_pct=price_delta_pct,
        decision=decision,
        reason=reason,
        throttle_allowed=buy_allowed,
        gatekeeper_allowed=gatekeeper_allowed,
        alert_emitted=alert_emitted,
    )


def run_stress_test() -> List[TickResult]:
    """
    Run the 4-tick stress test scenario.
    
    Returns:
        List of TickResult objects
    """
    logger.info("=" * 80)
    logger.info("BTC THROTTLE RUNTIME STRESS TEST")
    logger.info("=" * 80)
    logger.info("")
    logger.info("Scenario:")
    logger.info("  Tick 1: First BUY conditions met → must be ALLOWED")
    logger.info("  Tick 2: 10 seconds later, 0% price change → must be BLOCKED")
    logger.info("  Tick 3: 30 seconds later, still < min % → must be BLOCKED")
    logger.info("  Tick 4: Enough time + enough % move → must be ALLOWED")
    logger.info("")
    
    # Initialize database
    db = SessionLocal()
    try:
        
        # Get or create BTC watchlist item
        watchlist_item = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == "BTC_USDT"
        ).first()
        
        if not watchlist_item:
            logger.warning("BTC_USDT not in watchlist, creating test entry...")
            watchlist_item = WatchlistItem(
                symbol="BTC_USDT",
                exchange="crypto_com",
                alert_enabled=True,
                buy_alert_enabled=True,
                sell_alert_enabled=True,
                min_price_change_pct=1.0,  # 1% minimum
                alert_cooldown_minutes=5.0,  # 5 minutes cooldown
            )
            db.add(watchlist_item)
            db.commit()
        
        # Ensure alert is enabled
        watchlist_item.alert_enabled = True
        watchlist_item.buy_alert_enabled = True
        watchlist_item.min_price_change_pct = 1.0
        watchlist_item.alert_cooldown_minutes = 5.0
        db.commit()
        
        # Mock Telegram sending
        mock_telegram_send()
        
        # Base time for elapsed calculations
        base_time = datetime.now(timezone.utc)
        
        # Clear any existing throttle state for clean test
        from app.models.signal_throttle import SignalThrottleState
        from app.services.signal_throttle import build_strategy_key
        strategy_key = build_strategy_key(
            strategy_type="swing",
            risk_approach="conservative",
        )
        db.query(SignalThrottleState).filter(
            SignalThrottleState.symbol == "BTC_USDT",
            SignalThrottleState.strategy_key == strategy_key,
            SignalThrottleState.side == "BUY",
        ).delete()
        db.commit()
        
        results: List[TickResult] = []
        
        # Tick 1: First alert (should be allowed)
        logger.info("🔄 Running Tick 1...")
        tick1_time = base_time
        tick1_price = 50000.0
        result1 = simulate_btc_tick(db, 1, tick1_price, base_time, tick1_time, watchlist_item)
        results.append(result1)
        logger.info(result1.to_line())
        logger.info("")
        
        # Tick 2: 10 seconds later, same price (should be blocked)
        logger.info("🔄 Running Tick 2...")
        tick2_time = base_time + timedelta(seconds=10)
        tick2_price = 50000.0  # Same price, 0% change
        result2 = simulate_btc_tick(db, 2, tick2_price, base_time, tick2_time, watchlist_item)
        results.append(result2)
        logger.info(result2.to_line())
        logger.info("")
        
        # Tick 3: 30 seconds later (40 total), still same price (should be blocked)
        logger.info("🔄 Running Tick 3...")
        tick3_time = base_time + timedelta(seconds=40)
        tick3_price = 50010.0  # 0.02% change, still < 1%
        result3 = simulate_btc_tick(db, 3, tick3_price, base_time, tick3_time, watchlist_item)
        results.append(result3)
        logger.info(result3.to_line())
        logger.info("")
        
        # Tick 4: 6 minutes later (enough time), 2% price change (should be allowed)
        logger.info("🔄 Running Tick 4...")
        tick4_time = base_time + timedelta(minutes=6)
        tick4_price = 51000.0  # 2% change from tick1
        result4 = simulate_btc_tick(db, 4, tick4_price, base_time, tick4_time, watchlist_item)
        results.append(result4)
        logger.info(result4.to_line())
        logger.info("")
        
        # Restore Telegram sending
        restore_telegram_send()
        
        return results
        
    finally:
        db.close()


def generate_report(results: List[TickResult]) -> str:
    """Generate Markdown report from test results."""
    report_lines = [
        "# BTC Throttle Stress Test Report",
        "",
        f"**Date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        "## Scenario",
        "",
        "This test simulates the EXACT production code path to verify that BTC alerts",
        "cannot bypass throttle. It uses the same evaluator, gatekeeper, and emit_alert",
        "functions that AWS production uses.",
        "",
        "### Test Sequence",
        "",
        "1. **Tick 1:** First BUY conditions met → must be **ALLOWED**",
        "2. **Tick 2:** 10 seconds later, 0% price change → must be **BLOCKED**",
        "3. **Tick 3:** 40 seconds later, 0.02% price change → must be **BLOCKED**",
        "4. **Tick 4:** 6 minutes later, 2% price change → must be **ALLOWED**",
        "",
        "## Results",
        "",
        "| Tick | Decision | Price | Elapsed | Price Δ% | Throttle | Gatekeeper | Alert Emitted | Reason |",
        "|------|----------|-------|---------|----------|----------|------------|---------------|--------|",
    ]
    
    for result in results:
        throttle_status = "✅" if result.throttle_allowed else "❌"
        gatekeeper_status = "✅" if result.gatekeeper_allowed else "❌"
        alert_status = "✅" if result.alert_emitted else "❌"
        
        report_lines.append(
            f"| {result.tick_num} | {result.decision} | ${result.price:,.2f} | "
            f"{result.elapsed_seconds:.1f}s | {result.price_delta_pct:.2f}% | "
            f"{throttle_status} | {gatekeeper_status} | {alert_status} | "
            f"{result.reason[:60]} |"
        )
    
    report_lines.extend([
        "",
        "## Expected vs Actual",
        "",
    ])
    
    # Verify expectations
    expected = [
        (1, True, "First alert should be allowed"),
        (2, False, "Second alert within 10s with 0% change should be blocked"),
        (3, False, "Third alert with insufficient time/price should be blocked"),
        (4, True, "Fourth alert with sufficient time and price should be allowed"),
    ]
    
    all_passed = True
    for tick_num, should_allow, description in expected:
        result = results[tick_num - 1]
        passed = result.alert_emitted == should_allow
        status = "✅ PASS" if passed else "❌ FAIL"
        report_lines.append(f"- **Tick {tick_num}:** {status} - {description}")
        if not passed:
            all_passed = False
            report_lines.append(
                f"  - Expected: {'ALLOWED' if should_allow else 'BLOCKED'}, "
                f"Got: {'ALLOWED' if result.alert_emitted else 'BLOCKED'}"
            )
    
    report_lines.extend([
        "",
        "## Final Verdict",
        "",
        f"**{'✅ PASS' if all_passed else '❌ FAIL'}**",
        "",
        "The throttle system " + ("correctly" if all_passed else "incorrectly") + " enforced throttle rules.",
    ])
    
    return "\n".join(report_lines)


def main():
    """Main entry point."""
    try:
        results = run_stress_test()
        
        # Generate report
        report = generate_report(results)
        
        # Write report
        report_path = Path(__file__).parent.parent / "docs" / "monitoring" / "BTC_THROTTLE_STRESS_LOG.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report)
        
        logger.info("")
        logger.info("=" * 80)
        logger.info("STRESS TEST COMPLETE")
        logger.info("=" * 80)
        logger.info(f"Report written to: {report_path}")
        logger.info("")
        
        # Print summary
        all_passed = all(
            (r.tick_num == 1 and r.alert_emitted) or
            (r.tick_num == 4 and r.alert_emitted) or
            (r.tick_num in (2, 3) and not r.alert_emitted)
            for r in results
        )
        
        if all_passed:
            logger.info("✅ ALL TESTS PASSED - Throttle is working correctly!")
        else:
            logger.error("❌ SOME TESTS FAILED - Throttle may have issues!")
            sys.exit(1)
        
    except Exception as e:
        logger.error(f"Stress test failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

