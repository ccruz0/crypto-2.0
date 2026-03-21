# ATP Control Alerts Channel ID — Final Setup

To route ATP Control messages to the **ATP Control Alerts channel** (not the operator private chat), you need the channel's real chat ID (negative, e.g. `-1001234567890`).

## Get the Channel ID via @getidsbot (≈1 minute)

1. Open Telegram and go to [@getidsbot](https://t.me/getidsbot)
2. In the **ATP Control Alerts** channel, send any message (e.g. "test") or use an existing one
3. **Forward** that message to @getidsbot
4. @getidsbot replies with the channel's **chat ID** (e.g. `-1001234567890`)
5. Copy that number

## Apply the Channel ID

```bash
# From repo root
./scripts/add_atp_control_chat_id.sh -1001234567890   # use your actual ID
```

Then restart and validate:

```bash
docker compose --profile aws restart backend-aws
python scripts/validate_telegram_routing.py
```

## For EC2 Production

If the backend runs on EC2, also add to `.env.aws` on the instance:

```bash
# On EC2 (or via SSM)
echo "TELEGRAM_ATP_CONTROL_CHAT_ID=-1001234567890" >> .env.aws   # use your actual ID
docker compose --profile aws restart backend-aws
```
