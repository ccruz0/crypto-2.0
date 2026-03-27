# 🔐 Authentication Fix - README

## Problem
Order creation fails with authentication error, but read operations work fine.

## Solution
Skip the `exec_inst` parameter that was causing signature mismatch.

## Quick Fix

**On AWS server:**
```bash
cd ~/crypto-2.0
echo "CRYPTO_SKIP_EXEC_INST=true" >> .env.aws
echo "CRYPTO_AUTH_DIAG=true" >> .env.aws
docker compose restart backend
```

## Files

- **Start:** `START_HERE_AUTH_FIX.md`
- **Deploy:** `COPY_TO_AWS_AND_RUN.md`
- **Script:** `fix_auth_on_aws.sh`

## Status
✅ Code fix implemented  
✅ Scripts created  
✅ Documentation complete  
⏳ **Ready to deploy on AWS**

---

See `INDEX_AUTHENTICATION_FIX.md` for complete file index.

