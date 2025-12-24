# 🚀 Authentication Troubleshooting - Quick Reference

## Quick Commands

```bash
# 1. Enable detailed diagnostics
docker compose exec backend-aws python scripts/enable_auth_diagnostics.py
docker compose restart backend-aws

# 2. Run deep diagnostic (step-by-step signature testing)
docker compose exec backend-aws python scripts/deep_auth_diagnostic.py

# 3. Run comprehensive diagnostic
docker compose exec backend-aws python scripts/diagnose_auth_40101.py

# 4. Test connection
docker compose exec backend-aws python scripts/test_crypto_connection.py

# 5. Verify setup
docker compose exec backend-aws python scripts/verify_api_key_setup.py

# 6. Get outbound IP
docker compose exec backend-aws python -c "import requests; print(requests.get('https://api.ipify.org', timeout=5).text.strip())"
```

## Error 40101 - Quick Fix Checklist

- [ ] **Enable "Read" permission** in Crypto.com Exchange → Settings → API Keys
- [ ] **Verify API key status** is "Enabled" (not Disabled/Suspended)
- [ ] **Add server IP to whitelist** (get IP from diagnostic)
- [ ] **Verify credentials** are correct (no quotes, no extra spaces)
- [ ] **Wait 30-60 seconds** after making changes
- [ ] **Restart backend**: `docker compose restart backend-aws`
- [ ] **Test again**: Run diagnostic scripts

## Most Common Fix (90% of cases)

1. Go to https://exchange.crypto.com/ → Settings → API Keys
2. Edit your API key
3. **Enable "Read" permission** ✅
4. Save
5. Wait 30 seconds
6. Test: `docker compose exec backend-aws python scripts/test_crypto_connection.py`

## Diagnostic Tools

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `deep_auth_diagnostic.py` | Step-by-step signature testing | When you need to see exact signature generation |
| `diagnose_auth_40101.py` | Comprehensive diagnostic | General troubleshooting |
| `test_crypto_connection.py` | Connection testing | Quick verification |
| `verify_api_key_setup.py` | Setup verification | Check configuration |
| `enable_auth_diagnostics.py` | Enable detailed logging | Enable detailed logs |

## Expected Results

### ✅ Success
```
✅ Private API works! Found X account(s)
✅ Open orders API works! Found X open order(s)
```

### ❌ Failure
```
❌ Private API error: Crypto.com API authentication failed: Authentication failure (code: 40101)
```

## Next Steps Based on Results

### If Deep Diagnostic Shows Signature Issues
→ Check credential format (no quotes, no spaces)
→ Verify encoding (should be UTF-8)
→ Regenerate API key

### If Signature Works But Request Fails
→ Check API key permissions (enable "Read")
→ Check API key status (must be Enabled)
→ Check IP whitelist

### If Some Endpoints Work But Others Don't
→ Check endpoint-specific permissions
→ Compare working vs non-working requests
→ Check parameter format

## Documentation

- **Quick Fix**: `QUICK_FIX_40101.md`
- **Deep Dive**: `TROUBLESHOOTING_DEEP_DIVE.md`
- **Complete Guide**: `CRYPTO_COM_AUTHENTICATION_GUIDE.md`
- **Action Plan**: `NEXT_STEPS_ACTION_PLAN.md`

## Support

If still not working after trying all steps:
1. Run `deep_auth_diagnostic.py` and save output
2. Collect logs: `docker compose logs backend-aws | grep -i "crypto\|auth" > logs.txt`
3. Contact Crypto.com Support with diagnostic output

