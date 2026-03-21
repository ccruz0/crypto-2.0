# Telegram Destination Verification

**Goal:** Each logical channel (ATP Control, AWS Alerts, Claw, HiloVivo 3.0) must resolve to its own distinct `chat_id`. Separate sends are not enough if they all target the same chat.

## Resolved Routing Table (Expected)

| Channel      | Token var                      | Chat var                      | Expected destination |
|--------------|---------------------------------|-------------------------------|----------------------|
| ATP Control  | TELEGRAM_ATP_CONTROL_BOT_TOKEN | TELEGRAM_ATP_CONTROL_CHAT_ID  | ATP Control Alerts channel |
| AWS Alerts   | TELEGRAM_ALERT_BOT_TOKEN        | TELEGRAM_ALERT_CHAT_ID        | AWS_alerts channel   |
| Claw         | TELEGRAM_CLAW_BOT_TOKEN         | TELEGRAM_CLAW_CHAT_ID         | Claw channel         |
| ATP Alerts | TELEGRAM_BOT_TOKEN              | TELEGRAM_CHAT_ID_TRADING      | ATP Alerts channel  |

## Verification

```bash
python scripts/verify_telegram_destinations.py
```

- **Exit 0:** All channels have distinct destinations.
- **Exit 1:** Multiple channels share the same `chat_id` → routing misconfiguration.

## Fixing Duplicate Destinations

If AWS Alerts, Claw, and HiloVivo 3.0 all resolve to the same `chat_id` (e.g. 839853931):

1. **Create or identify separate Telegram channels** for each:
   - AWS_alerts
   - Claw
   - HILOVIVO3.0

2. **Add each bot to its channel** and send a message in each.

3. **Capture channel IDs:**
   ```bash
   ./scripts/capture_all_telegram_channel_ids.sh
   ```
   During the 45-second window, send a message in each of the 4 channels. The script prints `TELEGRAM_*_CHAT_ID` lines.

4. **Add to `secrets/runtime.env`** (or `.env.aws` on EC2):
   ```bash
   TELEGRAM_ALERT_CHAT_ID=<AWS_alerts_channel_id>
   TELEGRAM_CLAW_CHAT_ID=<Claw_channel_id>
   TELEGRAM_CHAT_ID_TRADING=<ATP_ALERTS_channel_id>
   ```

5. **Re-run verification:**
   ```bash
   python scripts/verify_telegram_destinations.py
   python scripts/validate_telegram_routing.py
   ```

## Env Sources (Load Order)

Scripts load env from (first wins, later overrides):

- `.env`
- `.env.aws`
- `secrets/runtime.env`
- `backend/.env`

Ensure channel-specific vars are set in the appropriate file for your environment.
