# Task: Investigate why Telegram alerts are not sent when buy or sell conditions trigger

Notion: `4d7d1312-8ece-4fcb-b092-ef437c09ee2c`

## Summary

BUY/SELL signal alerts are emitted by SignalMonitorService (backend-aws). Alerts flow: signal_monitor → send_buy_signal/send_sell_signal → telegram_notifier.send_message() → refresh_config() guard → Telegram API.

## Root cause (from investigation)

Blocking can occur at: (1) watchlist alert_enabled/buy_alert_enabled/sell_alert_enabled, (2) SignalThrottle cooldown, (3) refresh_config block reasons: run_telegram_disabled, kill_switch_disabled, token_missing, chat_id_missing, aws_using_local_credentials.

## Affected files

- `backend/app/services/telegram_notifier.py`
- `backend/app/services/signal_monitor.py`
- `docs/runbooks/TELEGRAM_ALERTS_NOT_SENT.md`

## Recommended fix

1. Run diagnostic: `docker compose --profile aws exec backend-aws python scripts/diagnose_telegram_alerts.py`
2. Check logs for `[TG BLOCKED]` and `reasons=` to identify exact block reason
3. If config issue: fix RUN_TELEGRAM, tg_enabled_aws, token/chat_id per TELEGRAM_ALERTS_NOT_SENT.md
4. If alert_enabled/throttle: verify watchlist_items have alert_enabled=true for monitored symbols
5. Add or improve runbook section for "Signal Monitor → Telegram" flow and common block reasons

## Constraints

- Build on the current implementation
- Change only the parts needed
- Keep the rest untouched
- Do not refactor unrelated code
- Preserve existing architecture unless explicitly required
