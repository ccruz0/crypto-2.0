# Telegram Safety Configuration

## Overview

The Telegram notification system is designed with strict environment isolation to ensure:
- **LOCAL** environment can send Telegram messages to the real chat
- **AWS** environment cannot send to the real chat under any circumstance

## Environment Variables

### LOCAL Environment

**Required:**
- `ENVIRONMENT=local`
- `TELEGRAM_BOT_TOKEN_LOCAL=<your_bot_token>` (or `TELEGRAM_BOT_TOKEN` for backward compatibility)
- `TELEGRAM_CHAT_ID_LOCAL=<your_chat_id>` (or `TELEGRAM_CHAT_ID` for backward compatibility)

**Location:** Set in `.env.local` file

### AWS Environment

**Required:**
- `ENVIRONMENT=aws`

**Recommended (for safety):**
- `TELEGRAM_BOT_TOKEN_AWS` - **NOT SET** (default: blocked)
- `TELEGRAM_CHAT_ID_AWS` - **NOT SET** (default: blocked)

**CRITICAL:** AWS must **NEVER** have:
- `TELEGRAM_BOT_TOKEN_LOCAL`
- `TELEGRAM_CHAT_ID_LOCAL`
- Generic `TELEGRAM_BOT_TOKEN` or `TELEGRAM_CHAT_ID`

**Location:** Set in `.env.aws` file (or AWS deployment environment)

## Kill Switches

Kill switches are stored in the `trading_settings` table:

- `tg_enabled_local` - Controls LOCAL environment (default: `true`)
- `tg_enabled_aws` - Controls AWS environment (default: `false`)

**Defaults:**
- LOCAL: Enabled by default (can send)
- AWS: Disabled by default (blocked)

## Verification

### 1. Run Verification Script

```bash
# From backend directory
python scripts/verify_telegram_safety.py

# From project root
python backend/scripts/verify_telegram_safety.py
```

**Expected output for LOCAL:**
```
✓ Runtime Environment: LOCAL
✓ ENVIRONMENT=local (matches runtime)
✓ LOCAL: Credentials present
✓ Kill switch tg_enabled_local: ENABLED
✓ SENDING ALLOWED
RESULT: PASS
```

**Expected output for AWS:**
```
✓ Runtime Environment: AWS
✓ ENVIRONMENT=aws (matches runtime)
✓ AWS: No LOCAL credentials (safe)
⚠️  AWS: AWS credentials missing (sending will be blocked)
⚠️  Kill switch tg_enabled_aws: NOT SET (defaults to DISABLED)
✗ SENDING BLOCKED
  Reason: missing_aws_credentials
RESULT: FAIL - Telegram sending is BLOCKED
```

**Exit codes:**
- `0` = PASS (sending allowed)
- `1` = FAIL (sending blocked or misconfigured)

### 2. Test Endpoint (Optional)

**Endpoint:** `POST /api/control/telegram/test`

**Security:** Requires `ENABLE_TG_TEST_ENDPOINT=true` OR request from localhost

**Example:**
```bash
# Enable test endpoint
export ENABLE_TG_TEST_ENDPOINT=true

# Send test message
curl -X POST http://localhost:8002/api/control/telegram/test \
  -H "Content-Type: application/json"
```

**Response:**
```json
{
  "ok": true,
  "blocked": false,
  "message": "Test message sent successfully",
  "env": "local"
}
```

Or if blocked:
```json
{
  "ok": false,
  "blocked": true,
  "reason": "kill_switch_disabled",
  "message": "Test message blocked: kill_switch_disabled",
  "env": "aws"
}
```

### 3. Dashboard Verification

Navigate to: **Dashboard → System Health → Details → Telegram Alerts**

**Check:**
- Environment badge shows correct environment (LOCAL/AWS)
- Kill switch toggle reflects current setting
- Credentials status shows "Present" or "Missing"
- Effective Status shows "SENDING ALLOWED" or "BLOCKED: <reason>"

## Message Source Tagging

All Telegram messages include a source footer:

```
— source=LOCAL host=macbook-pro
```

or

```
— source=AWS host=container-id
```

This allows you to verify which environment sent each message.

## Safety Guarantees

1. **AWS cannot send to real chat:**
   - No LOCAL credentials loaded (`.env.local` excluded from AWS backend)
   - Kill switch defaults to OFF
   - Hard guard blocks if AWS credentials missing

2. **LOCAL can send:**
   - Uses LOCAL credentials from `.env.local`
   - Kill switch defaults to ON
   - Source tagged in all messages

3. **Environment isolation:**
   - Each environment uses its own credentials
   - No cross-environment credential access
   - Backend enforcement (not just UI)

## Troubleshooting

### LOCAL cannot send

1. Check credentials:
   ```bash
   python backend/scripts/verify_telegram_safety.py
   ```

2. Check kill switch in dashboard (System Health → Telegram Alerts)

3. Check logs for `[TG BLOCKED]` messages

### AWS is sending (should not happen)

1. Verify AWS has no LOCAL credentials:
   ```bash
   # In AWS backend container
   env | grep TELEGRAM | grep LOCAL
   # Should return nothing
   ```

2. Verify kill switch is OFF:
   ```bash
   # Check database
   SELECT * FROM trading_settings WHERE setting_key = 'tg_enabled_aws';
   # Should be 'false' or not exist
   ```

3. Check docker-compose.yml: AWS backend should NOT load `.env.local`

## Related Files

- `backend/scripts/verify_telegram_safety.py` - Verification script
- `backend/app/services/telegram_notifier.py` - Hard guard implementation
- `backend/app/api/routes_control.py` - Settings API endpoints
- `frontend/src/components/SystemHealth.tsx` - Dashboard UI
- `docker-compose.yml` - Environment configuration

