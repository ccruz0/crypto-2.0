# Fix: Use ATP Control Bot Token (not AWS_alerts)

## Problem

The backend uses the token for **AWS_alerts_hilovivo_bot** (id 8690957210), but ATP Control commands go to **@ATP_control_bot**. Different bots → commands never reach the backend.

## Solution

Update the Telegram bot token to the **ATP Control** bot token (@ATP_control_bot).

---

## Option A: Update SSM Parameter (recommended)

The token is stored in AWS SSM: `/automated-trading-platform/prod/telegram/bot_token`

1. Get the ATP Control bot token from [@BotFather](https://t.me/BotFather):
   - Send `/mybots` → select @ATP_control_bot → API Token

2. Update SSM:
   ```bash
   aws ssm put-parameter \
     --name "/automated-trading-platform/prod/telegram/bot_token" \
     --value "YOUR_ATP_CONTROL_BOT_TOKEN" \
     --type SecureString \
     --overwrite \
     --region ap-southeast-1
   ```

3. Re-render and restart:
   ```bash
   # From your Mac (with AWS CLI)
   cd /path/to/automated-trading-platform
   bash scripts/aws/render_runtime_env.sh
   # Then deploy or restart backend on EC2
   ./deploy_via_ssm.sh full
   ```

   Or via SSM on EC2:
   ```bash
   sudo -u ubuntu bash -c 'cd /home/ubuntu/crypto-2.0 && bash scripts/aws/render_runtime_env.sh && docker compose --profile aws restart backend-aws backend-aws-canary'
   ```

---

## Option B: Update secrets/runtime.env on EC2

If SSM is not the source, the token may be in `secrets/runtime.env`:

1. SSM into EC2:
   ```bash
   aws ssm start-session --target i-087953603011543c5 --region ap-southeast-1
   ```

2. Edit (as ubuntu):
   ```bash
   sudo -u ubuntu nano /home/ubuntu/crypto-2.0/secrets/runtime.env
   ```
   Set `TELEGRAM_BOT_TOKEN=<ATP_control_bot_token>`

3. Restart:
   ```bash
   sudo -u ubuntu bash -c 'cd /home/ubuntu/crypto-2.0 && docker compose --profile aws restart backend-aws backend-aws-canary'
   ```

---

## Verify

After restart, run:

```bash
sudo -u ubuntu bash -c 'cd /home/ubuntu/crypto-2.0 && docker compose --profile aws exec -T backend-aws python -c "
import requests
from app.utils.telegram_token_loader import get_telegram_token, mask_token
t = get_telegram_token()
print(\"Token:\", mask_token(t))
if t:
    r = requests.get(f\"https://api.telegram.org/bot{t}/getMe\", timeout=5)
    print(\"Bot:\", r.json().get(\"result\", {}).get(\"username\", \"?\"))
"'
```

Expected: `Bot: ATP_control_bot`

Then send `/start` in ATP Control — should reply.
