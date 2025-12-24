# Quick Deploy - Telegram /start Fix

## ✅ Changes Committed
Commit: `85ea816` - "Fix Telegram /start not responding: diagnostics, webhook cleanup, single poller lock, menu restore"

## 🚀 Quick Deploy Commands

### Option 1: Automated Script
```bash
./deploy_telegram_fix_aws.sh
```

### Option 2: Manual Deploy
```bash
# Rebuild and restart
docker compose --profile aws up -d --build backend-aws

# Wait a few seconds, then verify
docker compose --profile aws exec backend-aws python -m tools.telegram_diag

# Monitor logs
docker compose --profile aws logs -f backend-aws | grep -i "TG\|webhook\|poller"
```

### Option 3: Just Restart (if code already on server)
```bash
docker compose --profile aws restart backend-aws
```

## ✅ Verification Checklist

After deployment, verify:

- [ ] Container is running: `docker compose --profile aws ps`
- [ ] Diagnostics run successfully: `python -m tools.telegram_diag`
- [ ] Webhook is deleted: Look for "No webhook configured" in logs
- [ ] Poller lock acquired: Look for "Poller lock acquired" in logs
- [ ] /start works: Send `/start` in Telegram and verify response

## 📋 Expected Log Output

### On Startup:
```
[TG] Running startup diagnostics...
[TG] Bot identity: username=..., id=...
[TG] Webhook info: url=None, pending_updates=0
[TG] No webhook configured (polling mode)
```

### When /start is sent:
```
[TG] ⚡ Processing command: '/start' from chat_id=..., update_id=...
[TG][CMD] Processing /start command from chat_id=...
[TG] Welcome message with custom keyboard sent to chat_id=...
[TG][CMD] /start command processed successfully for chat_id=...
```

## 🐛 Troubleshooting

### Bot still not responding?
1. Check webhook: `python -m tools.telegram_diag`
2. Check logs: `docker compose --profile aws logs backend-aws | grep -i "error\|409\|poller"`
3. Enable diagnostics: Set `TELEGRAM_DIAGNOSTICS=1` and restart

### Container won't start?
```bash
# Check logs
docker compose --profile aws logs backend-aws

# Check syntax
docker compose --profile aws exec backend-aws python3 -m py_compile app/services/telegram_commands.py
```

## 📞 Support

See full report: `docs/telegram/telegram_start_not_responding_report.md`
