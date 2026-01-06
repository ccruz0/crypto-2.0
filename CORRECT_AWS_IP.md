# Correct AWS Server IP Address

## ✅ Correct IP: `47.130.143.159`

The correct AWS server IP address is **`47.130.143.159`**, not `175.41.189.249`.

## SSH Command

```bash
ssh ubuntu@47.130.143.159
```

## Check Telegram Logs

Once connected, run:

```bash
cd ~/automated-trading-platform

# Check recent /start activity
docker-compose --profile aws logs --tail=500 backend-aws | grep -i "TG.*START\|TG.*MENU\|TG.*ERROR" | tail -50

# Or check all Telegram activity
docker-compose --profile aws logs --tail=200 backend-aws | grep -i "telegram\|TG" | tail -40

# Real-time monitoring (send /start while this runs)
docker-compose --profile aws logs -f backend-aws | grep -i "TG.*START\|TG.*MENU"
```

## What You Should See

When `/start` is sent successfully, you should see:

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

## Quick One-Liner

```bash
ssh ubuntu@47.130.143.159 "cd ~/automated-trading-platform && docker-compose --profile aws logs --tail=500 backend-aws | grep -i 'TG.*START\|TG.*MENU' | tail -30"
```















