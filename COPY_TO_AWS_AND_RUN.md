# 📋 Copy to AWS and Run

Since SSH connection isn't working, here's what to do:

## Option 1: Copy Script to AWS

1. **Copy the script content** from `fix_auth_on_aws.sh`
2. **SSH into AWS manually**
3. **Create the file:**
   ```bash
   nano ~/fix_auth_on_aws.sh
   # Paste the content, save (Ctrl+X, Y, Enter)
   ```
4. **Make it executable:**
   ```bash
   chmod +x ~/fix_auth_on_aws.sh
   ```
5. **Run it:**
   ```bash
   bash ~/fix_auth_on_aws.sh
   ```

## Option 2: Run Commands Directly

**SSH into AWS and run these commands:**

```bash
cd ~/automated-trading-platform

# Add fix
echo "CRYPTO_SKIP_EXEC_INST=true" >> .env.aws
echo "CRYPTO_AUTH_DIAG=true" >> .env.aws

# Verify
cat .env.aws | grep CRYPTO_SKIP_EXEC_INST

# If using Docker:
docker compose restart backend

# If running as process:
pkill -f "uvicorn app.main:app"
cd ~/automated-trading-platform/backend
source venv/bin/activate  # if using venv
nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > backend.log 2>&1 &
```

## Verify It Worked

```bash
# Check .env.aws
grep CRYPTO_SKIP_EXEC_INST .env.aws

# Check logs (Docker)
docker compose logs backend --tail 50 | grep "MARGIN ORDER CONFIGURED"

# Check logs (Process)
tail -50 ~/automated-trading-platform/backend/backend.log | grep "MARGIN ORDER CONFIGURED"
```

**You should see:**
```
📊 MARGIN ORDER CONFIGURED: leverage=10 (exec_inst skipped per CRYPTO_SKIP_EXEC_INST=true)
```

---

**The fix is simple - just add those two lines to .env.aws and restart your backend!**

