# Telegram AWS Runbook - Make Telegram GREEN

**Purpose:** Step-by-step guide to make Telegram show GREEN in AWS dashboard  
**Last Updated:** January 27, 2026

---

## Prerequisites

### Required Access
- **SSH access** to AWS EC2 instance (`ubuntu@47.130.143.159`)
- **Docker** installed and running on AWS
- **curl** installed (usually pre-installed)

### Verify Prerequisites

```bash
# Test SSH access (from your local machine)
ssh ubuntu@47.130.143.159 "echo 'SSH OK'"

# On AWS, verify Docker
docker --version
docker compose version

# Verify curl
curl --version
```

---

## SSH Access Setup

### If You Get "Permission denied (publickey)"

**Step 1: Locate Your SSH Key**

```bash
# Check common locations
ls -la ~/.ssh/
ls -la ~/.ssh/*.pem
ls -la ~/.ssh/id_rsa
ls -la ~/.ssh/id_ed25519
```

**Step 2: Verify Key Permissions**

```bash
chmod 600 ~/.ssh/your-key.pem
```

**Step 3: Test Connection with Explicit Key**

```bash
# If key is .pem file
ssh -i ~/.ssh/your-key.pem ubuntu@47.130.143.159

# If key is id_rsa
ssh -i ~/.ssh/id_rsa ubuntu@47.130.143.159
```

**Step 4: Verify Username**

The username might be:
- `ubuntu` (most common on Ubuntu EC2)
- `ec2-user` (Amazon Linux)
- `admin` (some custom AMIs)

**To verify:**
- Check AWS Console → EC2 → Instances → Connect → SSH client
- Or try: `ssh -i ~/.ssh/your-key.pem ec2-user@47.130.143.159`

**Step 5: Test Connectivity**

```bash
# Test basic connectivity
ping -c 3 47.130.143.159

# Test SSH port
nc -zv 47.130.143.159 22
```

**If still failing:**
- Check AWS Security Group allows inbound SSH (port 22) from your IP
- Verify instance is running in AWS Console
- Check if you need VPN access

---

## Step-by-Step Execution

### Step 1: SSH to AWS

```bash
ssh -i ~/.ssh/your-key.pem ubuntu@47.130.143.159
cd /home/ubuntu/automated-trading-platform
```

### Step 2: Run Diagnostic

```bash
bash scripts/check_telegram_gates_aws.sh
```

**Expected Output:**
```
==========================================
Telegram Health Gates Diagnostic
==========================================

=== Gate 0: Container/Service Discovery ===
  Backend service: backend-aws (docker compose)
  Database service: db (docker compose)

=== Gate 1: RUN_TELEGRAM ===
  ❌ FAIL: RUN_TELEGRAM not set

=== Gate 2: Kill Switch (tg_enabled_aws) ===
  ❌ FAIL: tg_enabled_aws not set in database (defaults to false)

=== Gate 3: Bot Token ===
  ✅ PASS: Bot token set (123456...7890)

=== Gate 4: Chat ID ===
  ✅ PASS: Chat ID set (839853931)

==========================================
Summary
==========================================
Gate 0 (Containers): ✅ PASS
Gate 1 (RUN_TELEGRAM): ❌ FAIL
Gate 2 (Kill Switch):   ❌ FAIL
Gate 3 (Bot Token):    ✅ PASS
Gate 4 (Chat ID):      ✅ PASS
```

### Step 3: Apply Fixes

```bash
bash scripts/fix_telegram_gates_aws.sh
```

**What the script does:**
- ✅ Fixes Gate 1: Adds/updates `RUN_TELEGRAM=true` in `.env.aws`
- ✅ Fixes Gate 2: Sets `tg_enabled_aws=true` in database
- ⚠️ Checks Gate 3 & 4: Reports if credentials are missing (manual fix required)
- ✅ Restarts backend automatically if fixes were applied

**Expected Output:**
```
==========================================
Telegram Health Gates Fix
==========================================

=== Fixing Gate 1: RUN_TELEGRAM ===
  Adding RUN_TELEGRAM=true to .env.aws...
  ✅ Added RUN_TELEGRAM=true to .env.aws

=== Fixing Gate 2: Kill Switch (tg_enabled_aws) ===
  ✅ Created kill switch and set to true

=== Checking Gate 3: Bot Token ===
  ✅ Bot token already set (123456...7890)

=== Checking Gate 4: Chat ID ===
  ✅ Chat ID already set (839853931)

==========================================
Summary
==========================================
Fixes applied: 2

⚠️  Restarting backend to apply changes...
  ✅ Backend restarted

Waiting for backend to be healthy (up to 2 minutes)...
✅ Backend is healthy
```

### Step 4: Verify GREEN Status

```bash
bash scripts/verify_telegram_green_aws.sh
```

**Expected Output:**
```
==========================================
Telegram GREEN Verification
==========================================

=== Health Endpoint Check ===
Telegram health section:
"telegram":{"status":"PASS","enabled":true,"chat_id_set":true,"bot_token_set":true,"run_telegram_env":true,"kill_switch_enabled":true,"last_send_ok":null}

Status: PASS
Enabled: true

=== Recent Telegram Logs ===
[TELEGRAM_STARTUP] ENVIRONMENT=aws hostname=... pid=... telegram_enabled=True bot_token_present=True chat_id_present=True
[TELEGRAM_HEALTH] origin=startup enabled=True token_present=True chat_id_present=True

=== Container Status ===
NAME                    STATUS
backend-aws             Up 2 minutes (healthy)

✅ SUCCESS: Telegram is GREEN
```

---

## What "PASS" Looks Like

### Health Endpoint Response

```json
{
  "telegram": {
    "status": "PASS",
    "enabled": true,
    "chat_id_set": true,
    "bot_token_set": true,
    "run_telegram_env": true,
    "kill_switch_enabled": true,
    "last_send_ok": null
  }
}
```

### Key Indicators

- ✅ `"status": "PASS"` - All gates passing
- ✅ `"enabled": true` - Telegram is enabled
- ✅ `"run_telegram_env": true` - Gate 1 passing
- ✅ `"kill_switch_enabled": true` - Gate 2 passing
- ✅ `"bot_token_set": true` - Gate 3 passing
- ✅ `"chat_id_set": true` - Gate 4 passing

---

## Troubleshooting Each Gate

### Gate 1: RUN_TELEGRAM

**Symptom:** `"run_telegram_env": false`

**Check:**
```bash
docker compose --profile aws exec backend-aws env | grep RUN_TELEGRAM
```

**Fix:**
```bash
# Edit .env.aws
nano .env.aws

# Add or update:
RUN_TELEGRAM=true

# Restart
docker compose --profile aws restart backend-aws
```

**Verify:**
```bash
docker compose --profile aws exec backend-aws env | grep RUN_TELEGRAM
# Should show: RUN_TELEGRAM=true
```

---

### Gate 2: Kill Switch

**Symptom:** `"kill_switch_enabled": false`

**Check:**
```bash
docker compose --profile aws exec backend-aws python3 << 'PYEOF'
from app.database import SessionLocal
from app.models.trading_settings import TradingSettings
db = SessionLocal()
setting = db.query(TradingSettings).filter(TradingSettings.setting_key == 'tg_enabled_aws').first()
print(f"Value: {setting.setting_value if setting else 'not_set'}")
db.close()
PYEOF
```

**Fix:**
```bash
docker compose --profile aws exec backend-aws python3 << 'PYEOF'
from app.database import SessionLocal
from app.models.trading_settings import TradingSettings
db = SessionLocal()
try:
    setting = db.query(TradingSettings).filter(TradingSettings.setting_key == 'tg_enabled_aws').first()
    if setting:
        setting.setting_value = 'true'
    else:
        db.add(TradingSettings(setting_key='tg_enabled_aws', setting_value='true'))
    db.commit()
    print("✅ Enabled")
except Exception as e:
    print(f"❌ Error: {e}")
    db.rollback()
finally:
    db.close()
PYEOF
```

**Or use direct SQL:**
```bash
docker compose --profile aws exec db psql -U trader -d atp -c "
INSERT INTO trading_settings (setting_key, setting_value) 
VALUES ('tg_enabled_aws', 'true')
ON CONFLICT (setting_key) 
DO UPDATE SET setting_value = 'true';
"
```

**Verify:**
```bash
curl -s http://localhost:8002/api/health/system | grep -o '"kill_switch_enabled":[^,}]*'
# Should show: "kill_switch_enabled":true
```

---

### Gate 3: Bot Token

**Symptom:** `"bot_token_set": false`

**Check:**
```bash
docker compose --profile aws exec backend-aws env | grep -E "TELEGRAM_BOT_TOKEN"
```

**Fix:**
```bash
# Edit .env.aws
nano .env.aws

# Add:
TELEGRAM_BOT_TOKEN=<your_production_bot_token>
# OR
TELEGRAM_BOT_TOKEN_AWS=<your_production_bot_token>

# Restart
docker compose --profile aws restart backend-aws
```

**Verify:**
```bash
docker compose --profile aws exec backend-aws env | grep -E "TELEGRAM_BOT_TOKEN" | sed 's/=.*/=***MASKED***/'
# Should show: TELEGRAM_BOT_TOKEN=***MASKED***
```

---

### Gate 4: Chat ID

**Symptom:** `"chat_id_set": false`

**Check:**
```bash
docker compose --profile aws exec backend-aws env | grep -E "TELEGRAM_CHAT_ID"
```

**Fix:**
```bash
# Edit .env.aws
nano .env.aws

# Add:
TELEGRAM_CHAT_ID=<your_production_chat_id>
# OR
TELEGRAM_CHAT_ID_AWS=<your_production_chat_id>

# Restart
docker compose --profile aws restart backend-aws
```

**Verify:**
```bash
docker compose --profile aws exec backend-aws env | grep -E "TELEGRAM_CHAT_ID"
# Should show: TELEGRAM_CHAT_ID=<your_chat_id>
```

---

## Quick Reference Commands

### Check Current State
```bash
curl -s http://localhost:8002/api/health/system | grep -o '"telegram":{[^}]*}'
```

### Run All Steps
```bash
bash scripts/check_telegram_gates_aws.sh    # Diagnostic
bash scripts/fix_telegram_gates_aws.sh       # Fix
bash scripts/verify_telegram_green_aws.sh    # Verify
```

### Manual Health Check
```bash
curl -s http://localhost:8002/api/health/system
```

### Check Logs
```bash
docker compose --profile aws logs backend-aws --tail 100 | grep -i telegram
```

---

## Common Issues

### Issue: Script Fails with "container not found"

**Solution:**
```bash
# Check container name
docker ps | grep backend

# Update script if container name is different
# Or use docker compose:
docker compose --profile aws ps
```

### Issue: Database Connection Fails

**Solution:**
```bash
# Check database is running
docker compose --profile aws ps db

# Check DATABASE_URL in backend
docker compose --profile aws exec backend-aws env | grep DATABASE_URL
```

### Issue: Health Endpoint Returns 404

**Solution:**
```bash
# Check backend is running
docker compose --profile aws ps backend-aws

# Check backend logs
docker compose --profile aws logs backend-aws --tail 50

# Verify port
curl -v http://localhost:8002/api/health/system
```

---

## Evidence to Capture

After successful fix, capture:

1. **Health Endpoint Output:**
   ```bash
   curl -s http://localhost:8002/api/health/system | grep -o '"telegram":{[^}]*}'
   ```

2. **Container Status:**
   ```bash
   docker compose --profile aws ps backend-aws
   ```

3. **Recent Logs:**
   ```bash
   docker compose --profile aws logs backend-aws --tail 50 | grep -E "TELEGRAM|telegram"
   ```

4. **Gate Check Results:**
   ```bash
   bash scripts/check_telegram_gates_aws.sh
   ```

---

## Next Steps After GREEN

Once Telegram shows GREEN:

1. **Monitor for successful sends:**
   ```bash
   docker compose --profile aws logs backend-aws -f | grep -E "\[TELEGRAM_SEND\]|\[TELEGRAM_RESPONSE\]"
   ```

2. **Check database for sent messages:**
   ```bash
   docker compose --profile aws exec backend-aws python3 << 'PYEOF'
   from app.database import SessionLocal
   from app.models.telegram_message import TelegramMessage
   from datetime import datetime, timedelta
   db = SessionLocal()
   recent = db.query(TelegramMessage).filter(
       TelegramMessage.timestamp >= datetime.now() - timedelta(hours=1),
       TelegramMessage.blocked == False
   ).order_by(TelegramMessage.timestamp.desc()).limit(5).all()
   for msg in recent:
       print(f"[{msg.timestamp}] {msg.symbol or 'N/A'}: {msg.message[:60]}...")
   db.close()
   PYEOF
   ```

---

**End of Runbook**
