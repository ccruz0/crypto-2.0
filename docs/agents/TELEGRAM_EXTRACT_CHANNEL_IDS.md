# Extract Telegram Channel IDs from Update Payloads

**Script:** `scripts/extract_channel_ids_from_updates.py`

Automatically extracts valid channel IDs from Telegram update JSON (forwarded messages) and persists them to `secrets/runtime.env` and `.env.aws`.

## Requirements

- Update payloads must contain **forwarded messages** from channels
- `forward_origin.type == "channel"` or `forward_from_chat.type == "channel"`
- Channel IDs must start with `-100` (e.g. `-1003597744579`)

## Title → Env Var Mapping

| Title contains | Env var |
|----------------|---------|
| ATP Control | TELEGRAM_ATP_CONTROL_CHAT_ID |
| AWS | TELEGRAM_ALERT_CHAT_ID |
| Claw | TELEGRAM_CLAW_CHAT_ID |
| Hilo, Trading, HILOVIVO, ATP Alerts | TELEGRAM_CHAT_ID_TRADING |

## Usage

### From JSON file(s)

```bash
python scripts/extract_channel_ids_from_updates.py tmp/telegram_updates.json
python scripts/extract_channel_ids_from_updates.py --restart-verify tmp/telegram_updates.json
```

### Capture and extract (one-shot)

Stops backend, waits for you to forward messages, then fetches, extracts, persists, and restarts:

```bash
./scripts/capture_and_extract_telegram_channel_ids.sh
```

During the 45-second window, forward one message from each channel (ATP Control, AWS_alerts, Claw, HILOVIVO3.0) into a chat with the bot.

### Fetch from Telegram API (backend must not be consuming updates)

1. Stop backend or use a bot that isn't being polled
2. Forward one message from each channel into a chat with the bot
3. Run:

```bash
python scripts/extract_channel_ids_from_updates.py --fetch --restart-verify
```

### Dry run (no writes)

```bash
python scripts/extract_channel_ids_from_updates.py --dry-run tmp/telegram_updates.json
```

## Verification

After extraction:

```bash
python scripts/verify_telegram_destinations.py
python scripts/validate_telegram_routing.py
```

Expected: 4 logical channels, 4 distinct chat_ids, no fallback to 839853931.
