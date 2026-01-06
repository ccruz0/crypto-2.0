# Check Telegram /start Command Logs

## Quick Commands

Once you can SSH to AWS, run these commands to check the logs:

### 1. Check Recent /start Command Activity

```bash
ssh ubuntu@175.41.189.249
cd ~/automated-trading-platform
docker-compose --profile aws logs --tail=200 backend-aws | grep -i "TG.*START" | tail -30
```

### 2. Check Main Menu Sending

```bash
docker-compose --profile aws logs --tail=200 backend-aws | grep -i "TG.*MENU" | tail -30
```

### 3. Check for Errors

```bash
docker-compose --profile aws logs --tail=200 backend-aws | grep -i "TG.*ERROR" | tail -20
```

### 4. Check All Telegram Activity

```bash
docker-compose --profile aws logs --tail=200 backend-aws | grep -i "TG" | tail -50
```

### 5. Real-time Monitoring

```bash
docker-compose --profile aws logs -f backend-aws | grep -i "TG.*START\|TG.*MENU\|TG.*ERROR"
```

## What to Look For

### ✅ Success Indicators

When `/start` works correctly, you should see:

```
[TG][CMD] Processing /start command from chat_id=<chat_id>
[TG][CMD][START] Sending welcome message with persistent keyboard to chat_id=<chat_id>
[TG] Welcome message with custom keyboard sent to chat_id=<chat_id>
[TG][CMD][START] Welcome message result: True
[TG][CMD][START] Showing main menu to chat_id=<chat_id>
[TG][MENU] Building main menu for chat_id=<chat_id>
[TG] Menu message sent successfully to chat_id=<chat_id>, message_id=<id>
[TG][CMD][START] ✅ /start command processed successfully for chat_id=<chat_id> (both messages sent)
```

### ❌ Problem Indicators

If the main menu isn't appearing, look for:

1. **Main menu not being called:**
   ```
   [TG][CMD][START] Welcome message result: True
   [TG][CMD][START] Showing main menu to chat_id=<chat_id>
   ```
   But no `[TG][MENU]` logs after this

2. **Main menu failing to send:**
   ```
   [TG][MENU] Building main menu for chat_id=<chat_id>
   [TG][ERROR] Failed to send menu message to chat_id=<chat_id>: <error>
   ```

3. **Telegram API errors:**
   ```
   [TG] Menu message API returned not OK: <error description>
   ```

4. **HTTP errors:**
   ```
   [TG][ERROR] HTTP error sending menu message: <error>
   ```

## Detailed Diagnostic Commands

### Check if /start is being processed

```bash
docker-compose --profile aws logs --tail=500 backend-aws | grep -A 10 "Processing /start command"
```

### Check main menu function calls

```bash
docker-compose --profile aws logs --tail=500 backend-aws | grep -A 5 "Showing main menu"
```

### Check Telegram API responses

```bash
docker-compose --profile aws logs --tail=500 backend-aws | grep -i "Menu message sent\|Menu message API returned"
```

### Check for exceptions

```bash
docker-compose --profile aws logs --tail=500 backend-aws | grep -i "exception\|traceback" | grep -i "TG\|telegram\|start\|menu"
```

## Common Issues and Solutions

### Issue 1: Main menu function not being called

**Symptoms:** No `[TG][MENU]` logs after `[TG][CMD][START] Showing main menu`

**Possible causes:**
- Exception in `show_main_menu()` that's being caught
- Database connection issue
- Function returning early

**Check:**
```bash
docker-compose --profile aws logs --tail=500 backend-aws | grep -B 5 -A 10 "Showing main menu"
```

### Issue 2: Main menu message failing to send

**Symptoms:** `[TG][ERROR] Failed to send menu message` in logs

**Possible causes:**
- Telegram API rate limiting
- Invalid keyboard structure
- Network connectivity issues
- Bot token issues

**Check:**
```bash
docker-compose --profile aws logs --tail=500 backend-aws | grep -A 5 "Failed to send menu message"
```

### Issue 3: Telegram API returning errors

**Symptoms:** `Menu message API returned not OK` in logs

**Possible causes:**
- Invalid chat_id
- Bot blocked by user
- Message too long
- Invalid HTML formatting

**Check:**
```bash
docker-compose --profile aws logs --tail=500 backend-aws | grep "Menu message API returned not OK"
```

## Full Log Export

To export all relevant logs for analysis:

```bash
ssh ubuntu@175.41.189.249
cd ~/automated-trading-platform
docker-compose --profile aws logs --tail=1000 backend-aws > /tmp/telegram_logs.txt
grep -i "TG.*START\|TG.*MENU\|TG.*ERROR" /tmp/telegram_logs.txt > /tmp/telegram_start_analysis.txt
cat /tmp/telegram_start_analysis.txt
```

## Test After Checking Logs

After reviewing the logs:

1. Send `/start` command in Telegram
2. Immediately check logs:
   ```bash
   docker-compose --profile aws logs --tail=50 backend-aws | grep -i "TG"
   ```
3. Look for the sequence of log messages listed in "Success Indicators" above















