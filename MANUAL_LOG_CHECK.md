# Manual Log Check Commands

Since SSH connection is timing out, run these commands directly on the AWS server:

## Quick Check (Copy & Paste)

```bash
# SSH to AWS first
ssh ubuntu@175.41.189.249

# Then run these commands:
cd ~/automated-trading-platform

# Check recent /start activity
docker-compose --profile aws logs --tail=200 backend-aws | grep -i "TG.*START" | tail -30

# Check main menu attempts
docker-compose --profile aws logs --tail=200 backend-aws | grep -i "TG.*MENU" | tail -20

# Check for errors
docker-compose --profile aws logs --tail=200 backend-aws | grep -i "TG.*ERROR" | tail -15

# Check Telegram API responses
docker-compose --profile aws logs --tail=200 backend-aws | grep -i "Menu message sent\|Menu message API returned\|Welcome message" | tail -15
```

## One-Liner for Full Analysis

```bash
docker-compose --profile aws logs --tail=500 backend-aws | grep -i "TG.*START\|TG.*MENU\|TG.*ERROR" | tail -50
```

## Real-Time Monitoring

While monitoring, send `/start` in Telegram, then check:

```bash
docker-compose --profile aws logs -f backend-aws | grep -i "TG.*START\|TG.*MENU"
```

## What You Should See

If everything is working, you should see this sequence when `/start` is sent:

```
[TG][CMD] Processing /start command from chat_id=...
[TG][CMD][START] Sending welcome message with persistent keyboard to chat_id=...
[TG] Welcome message with custom keyboard sent to chat_id=...
[TG][CMD][START] Welcome message result: True
[TG][CMD][START] Showing main menu to chat_id=...
[TG][MENU] Building main menu for chat_id=...
[TG] Menu message sent successfully to chat_id=..., message_id=...
[TG][CMD][START] ✅ /start command processed successfully (both messages sent)
```

## If Main Menu Isn't Appearing

Look for these patterns:

1. **No menu logs after "Showing main menu":**
   - Check for exceptions: `grep -i "exception\|traceback" | grep -i "TG\|menu"`

2. **Menu send failed:**
   - Look for: `[TG][ERROR] Failed to send menu message`

3. **Telegram API error:**
   - Look for: `Menu message API returned not OK`

## Export Full Logs for Analysis

```bash
docker-compose --profile aws logs --tail=1000 backend-aws > /tmp/full_logs.txt
grep -i "TG.*START\|TG.*MENU\|TG.*ERROR" /tmp/full_logs.txt > /tmp/telegram_analysis.txt
cat /tmp/telegram_analysis.txt
```











