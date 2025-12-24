# 🚀 Deployment Instructions: Authentication Fix

## Quick Deploy

**SSH into AWS server and run:**

```bash
cd ~/automated-trading-platform

# Copy and run the deployment script
# Option 1: Copy the script content below, or
# Option 2: Use these commands directly:

echo "CRYPTO_SKIP_EXEC_INST=true" >> .env.aws
echo "CRYPTO_AUTH_DIAG=true" >> .env.aws

# Restart backend
docker compose restart backend
# OR if not using Docker:
pkill -f "uvicorn app.main:app"
cd backend
source venv/bin/activate  # if using venv
nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > backend.log 2>&1 &
```

## Full Deployment Script

Copy the content of `deploy_auth_fix_on_aws.sh` to AWS:

1. **SSH into AWS**
2. **Create the file:**
   ```bash
   nano ~/deploy_auth_fix_on_aws.sh
   ```
3. **Paste the script content** (from the file shown above)
4. **Save and run:**
   ```bash
   chmod +x ~/deploy_auth_fix_on_aws.sh
   bash ~/deploy_auth_fix_on_aws.sh
   ```

## Verify Deployment

```bash
# Check .env.aws
grep CRYPTO_SKIP_EXEC_INST .env.aws

# Check logs
docker compose logs backend --tail 50 | grep "MARGIN ORDER CONFIGURED"
# OR
tail -50 backend/backend.log | grep "MARGIN ORDER CONFIGURED"
```

**Should show:** `exec_inst skipped per CRYPTO_SKIP_EXEC_INST=true`

## What Gets Deployed

- ✅ Environment variables added to `.env.aws`
- ✅ Backend restarted to load new variables
- ✅ Code changes already in place (from previous sync)

---

**The fix is simple - just add two environment variables and restart!**

