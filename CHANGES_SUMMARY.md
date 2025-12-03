# Key Code Changes Summary

## 1. Decision Logic Alignment

### Location: `backend/app/services/signal_monitor.py` (lines ~1012-1019)

**Before**: Used `strategy_state.get("decision", "WAIT")` which could be incorrect

**After**: Uses `buy_signal` and `sell_signal` directly, matching debug script:

```python
# CRITICAL: Determine decision matching debug script logic (BUY if buy_signal, SELL if sell_signal, else WAIT)
# Do NOT use strategy_state.decision as it may not match the actual signals
if buy_signal:
    decision = "BUY"
elif sell_signal:
    decision = "SELL"
else:
    decision = "WAIT"
```

## 2. Comprehensive Decision Logging

### Location: `backend/app/services/signal_monitor.py` (lines ~1245-1291)

**New**: Added `[LIVE_ALERT_DECISION]` log AFTER throttle checks, including all flags:

```python
logger.info(
    f"[LIVE_ALERT_DECISION] symbol={symbol} | preset={preset_name}-{risk_mode} | decision={decision} | "
    f"buy_signal={buy_signal} | sell_signal={sell_signal} | alert_enabled={alert_enabled} | "
    f"buy_alert_enabled={buy_alert_enabled_raw} | sell_alert_enabled={sell_alert_enabled_raw} | "
    f"trade_enabled={trade_enabled} | can_emit_buy={can_emit_buy} | can_emit_sell={can_emit_sell} | "
    f"buy_throttle_status={buy_throttle_status} | sell_throttle_status={sell_throttle_status} | "
    f"volume_ratio={volume_ratio_str} | min_volume_ratio={min_volume_ratio:.4f} | origin={origin}"
)
```

**Key**: This log is ALWAYS emitted (even for WAIT), and includes `can_emit_buy`/`can_emit_sell` which match the debug script's logic.

## 3. Throttle Check for BUY

### Location: `backend/app/services/signal_monitor.py` (lines ~1303-1305)

**Before**: BUY emission only checked `buy_flag_allowed`

**After**: BUY emission checks BOTH `buy_allowed` (throttle) AND `buy_flag_allowed` (flags):

```python
# CRITICAL: Check BOTH throttle (buy_allowed) AND alert flags (buy_flag_allowed)
# This matches the debug script logic: can_emit_buy_alert = buy_allowed and buy_alert_enabled
if buy_signal and buy_allowed and buy_flag_allowed:
```

## 4. Enhanced Gatekeeper Logging

### Location: `backend/app/services/telegram_notifier.py` (lines ~184-195)

**Enhanced**: Added symbol and side to gatekeeper log:

```python
if "LIVE ALERT" in message or "BUY SIGNAL" in message or "SELL SIGNAL" in message:
    allowed = origin_upper in ("AWS", "TEST") and self.enabled
    side = "BUY" if "BUY SIGNAL" in message else ("SELL" if "SELL SIGNAL" in message else "UNKNOWN")
    logger.info(
        f"[LIVE_ALERT_GATEKEEPER] symbol={symbol or 'UNKNOWN'} side={side} origin={origin_upper} "
        f"enabled={self.enabled} bot_token_present={bool(self.bot_token)} "
        f"chat_id_present={bool(self.chat_id)} allowed={allowed}"
    )
```

## 5. Monitoring Registration on Telegram Failure

### Location: `backend/app/services/signal_monitor.py` (lines ~1650-1680, ~2650-2680)

**New**: Ensures monitoring entry is created even if Telegram send fails:

```python
# Ensure monitoring registration even if Telegram fails
monitoring_saved = False
if result:
    # Monitoring already registered in send_buy_signal
    monitoring_saved = True
else:
    # Telegram failed, but we should still register in monitoring
    try:
        from app.api.routes_monitoring import add_telegram_message
        add_telegram_message(
            f"✅ BUY SIGNAL: {symbol} - {reason_text} (Telegram send failed)",
            symbol=symbol,
            blocked=False,
            throttle_status="SENT",
            throttle_reason=buy_reason,
        )
        monitoring_saved = True
    except Exception as mon_err:
        logger.warning(f"Failed to register BUY alert in Monitoring after Telegram failure: {mon_err}")
```

## 6. Enhanced ALERT_EMIT_FINAL Logging

### Location: `backend/app/services/signal_monitor.py` (multiple locations)

**Enhanced**: Added `monitoring_saved` status to final log:

```python
logger.info(
    f"[ALERT_EMIT_FINAL] side=BUY symbol={symbol} origin={origin} "
    f"sent=True blocked=False throttle_status=SENT throttle_reason={buy_reason} "
    f"monitoring_saved={monitoring_saved}"
)
```

