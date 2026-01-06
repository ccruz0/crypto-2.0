# Deploy Telegram /start Fix

## Option 1: Deploy via Git (Recommended)

If your code is committed and pushed to git:

```bash
# On AWS server
ssh ubuntu@175.41.189.249
cd ~/automated-trading-platform
git pull
docker-compose --profile aws restart backend-aws
```

## Option 2: Manual File Copy

1. **Copy the file to AWS:**
   ```bash
   scp -i ~/.ssh/id_rsa backend/app/services/telegram_commands.py ubuntu@175.41.189.249:~/automated-trading-platform/backend/app/services/telegram_commands.py
   ```

2. **SSH to AWS and restart:**
   ```bash
   ssh -i ~/.ssh/id_rsa ubuntu@175.41.189.249
   cd ~/automated-trading-platform
   docker-compose --profile aws restart backend-aws
   ```

## Option 3: Direct Docker Compose (if on AWS)

If you're already on the AWS server:

```bash
cd ~/automated-trading-platform
docker-compose --profile aws restart backend-aws
```

## Option 4: Rebuild Container (if code is already there)

If the code is already on the server but you want to rebuild:

```bash
ssh ubuntu@175.41.189.249
cd ~/automated-trading-platform
docker-compose --profile aws up -d --build backend-aws
```

## Verification

After deployment, verify the fix:

1. **Check logs:**
   ```bash
   docker-compose --profile aws logs -f backend-aws | grep -i "TG.*START"
   ```

2. **Test in Telegram:**
   - Send `/start` to your bot
   - You should receive:
     - Welcome message with persistent keyboard buttons
     - Main menu message with inline buttons

3. **Check for errors:**
   ```bash
   docker-compose --profile aws logs backend-aws | grep -i "error\|exception" | tail -20
   ```

## Expected Behavior

When `/start` is called, you should see in logs:
```
[TG][CMD] Processing /start command from chat_id=<chat_id>
[TG][CMD][START] Sending welcome message with persistent keyboard to chat_id=<chat_id>
[TG] Welcome message with custom keyboard sent to chat_id=<chat_id>
[TG][CMD][START] Welcome message result: True
[TG][CMD][START] Showing main menu to chat_id=<chat_id>
[TG][MENU] Building main menu for chat_id=<chat_id>
[TG][MENU] Main menu send result: True
[TG][CMD][START] ✅ /start command processed successfully for chat_id=<chat_id> (both messages sent)
```

## Troubleshooting

If `/start` still doesn't work:

1. **Check if file was updated:**
   ```bash
   ssh ubuntu@175.41.189.249
   cd ~/automated-trading-platform
   grep -A 5 "Send welcome message with persistent keyboard" backend/app/services/telegram_commands.py
   ```

2. **Check container is running:**
   ```bash
   docker-compose --profile aws ps
   ```

3. **Check Telegram is enabled:**
   ```bash
   docker-compose --profile aws exec backend-aws env | grep TELEGRAM
   ```

4. **Restart if needed:**
   ```bash
   docker-compose --profile aws restart backend-aws
   ```















