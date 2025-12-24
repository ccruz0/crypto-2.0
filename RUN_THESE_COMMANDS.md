# 🔍 Run These Commands on AWS Server

Since SSH connection from local machine isn't working, **SSH into your AWS server manually** and run these commands:

## Step 1: Check Current Status

```bash
cd ~/automated-trading-platform

# Check if fix is in .env.aws
grep CRYPTO_SKIP_EXEC_INST .env.aws

# Check environment variables in running container
docker compose exec backend env | grep CRYPTO_SKIP_EXEC_INST

# Check recent authentication errors
docker compose logs backend --tail 500 | grep -A 30 "AUTHENTICATION FAILED" | tail -50

# Check SELL order creation
docker compose logs backend --tail 500 | grep -A 25 "Creating automatic SELL order" | tail -40

# Check if exec_inst is being skipped
docker compose logs backend --tail 200 | grep "MARGIN ORDER CONFIGURED"
```

## Step 2: Apply the Fix (if not already done)

```bash
cd ~/automated-trading-platform

# Add fix to .env.aws
echo "CRYPTO_SKIP_EXEC_INST=true" >> .env.aws
echo "CRYPTO_AUTH_DIAG=true" >> .env.aws

# Verify it was added
cat .env.aws | grep CRYPTO_SKIP_EXEC_INST

# Restart backend
docker compose restart backend

# Wait a few seconds
sleep 5

# Check logs to verify
docker compose logs backend --tail 50 | grep "MARGIN ORDER CONFIGURED"
```

## Step 3: Monitor Next Order

```bash
# Watch logs in real-time
docker compose logs backend -f | grep -E "AUTHENTICATION|order created|SELL order|MARGIN ORDER CONFIGURED"
```

## What to Look For

### ✅ Success Indicators:
- Logs show: `MARGIN ORDER CONFIGURED: leverage=10 (exec_inst skipped per CRYPTO_SKIP_EXEC_INST=true)`
- No "AUTHENTICATION FAILED" messages
- "order created successfully" appears

### ❌ If Still Failing:
- Check the exact error code and message
- Verify environment variable is set in container
- Check if backend was restarted after adding the variable

## Share Output

If it's still failing, share the output of:

```bash
# Full error context
docker compose logs backend --tail 500 | grep -B 10 -A 40 "AUTHENTICATION FAILED" > auth_error.txt

# Environment check
docker compose exec backend env | grep -E "CRYPTO|EXCHANGE" > env_vars.txt

# .env.aws check
cat .env.aws | grep -E "CRYPTO|EXCHANGE" > env_file.txt
```

Then share the contents of these files.

