# ✅ Deployment Checklist: Authentication Fix

## Pre-Deployment

- [x] Code changes implemented in `crypto_com_trade.py`
- [x] Diagnostic logging added to `signal_monitor.py`
- [x] Documentation created
- [x] Diagnostic scripts created

## Deployment Steps

### 1. On AWS Server

```bash
cd ~/automated-trading-platform

# Apply fix
echo "CRYPTO_SKIP_EXEC_INST=true" >> .env.aws
echo "CRYPTO_AUTH_DIAG=true" >> .env.aws

# Restart backend
docker compose restart backend
```

### 2. Verify Fix Applied

```bash
# Check .env.aws
grep CRYPTO_SKIP_EXEC_INST .env.aws

# Check container environment
docker compose exec backend env | grep CRYPTO_SKIP_EXEC_INST

# Check logs
docker compose logs backend --tail 50 | grep "MARGIN ORDER CONFIGURED"
```

### 3. Test Order Creation

- [ ] Trigger test alert or wait for next SELL signal
- [ ] Monitor logs for authentication errors
- [ ] Verify order is created successfully
- [ ] Check order appears in exchange

## Post-Deployment Verification

- [ ] No "AUTHENTICATION FAILED" errors in logs
- [ ] Logs show "exec_inst skipped" message
- [ ] Orders are being created successfully
- [ ] Diagnostic logs working (if enabled)

## Rollback (if needed)

If the fix causes issues:

```bash
# Remove the setting
sed -i '/^CRYPTO_SKIP_EXEC_INST=/d' .env.aws
sed -i '/^CRYPTO_AUTH_DIAG=/d' .env.aws

# Restart
docker compose restart backend
```

## Monitoring

After deployment, monitor for:
- Authentication errors (should be none)
- Order creation success rate
- Any new error patterns

---

**Ready to deploy!** Follow the steps above.
