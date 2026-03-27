# ⚡ Quick Reference: Authentication Fix

## 🎯 The Fix

Add these two lines to `.env.aws` on AWS server:
```bash
CRYPTO_SKIP_EXEC_INST=true
CRYPTO_AUTH_DIAG=true
```

Then restart backend.

## 🚀 Commands (Copy-Paste Ready)

```bash
cd ~/crypto-2.0
echo "CRYPTO_SKIP_EXEC_INST=true" >> .env.aws
echo "CRYPTO_AUTH_DIAG=true" >> .env.aws
docker compose restart backend
```

## ✅ Verify

```bash
docker compose logs backend --tail 50 | grep "MARGIN ORDER CONFIGURED"
```

Should show: `exec_inst skipped per CRYPTO_SKIP_EXEC_INST=true`

## 📚 Full Docs

- `START_HERE_AUTH_FIX.md` - Complete guide
- `COPY_TO_AWS_AND_RUN.md` - How to deploy
- `fix_auth_on_aws.sh` - Automated script

---

**That's it!**

