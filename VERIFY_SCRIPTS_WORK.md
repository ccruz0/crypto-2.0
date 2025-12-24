# ✅ Verify Diagnostic Scripts Work

## Quick Test

Run this first to verify everything is set up correctly:

```bash
# On AWS server
cd ~/automated-trading-platform/backend
python3 scripts/test_script_works.py
```

This will check:
- ✅ Python version
- ✅ Required packages
- ✅ Backend code location
- ✅ Environment variables
- ✅ .env file locations
- ✅ Network connectivity

## Expected Output

### ✅ All Good
```
✅ All checks passed! Diagnostic scripts should work.

💡 Next step: Run diagnostic script
   python3 scripts/deep_auth_diagnostic.py
```

### ⚠️ Issues Found
The script will tell you what's missing:
- Missing packages → `pip3 install requests`
- Backend code not found → Navigate to correct directory
- Credentials not set → Load from .env or set environment variables

## After Verification Passes

Run the actual diagnostic:

```bash
# Deep diagnostic (most detailed)
python3 scripts/deep_auth_diagnostic.py

# Or comprehensive diagnostic
python3 scripts/diagnose_auth_40101.py

# Or connection test
python3 scripts/test_crypto_connection.py
```

## One-Liner Test (from local machine)

```bash
ssh your-aws-server "cd ~/automated-trading-platform/backend && python3 scripts/test_script_works.py"
```

## Troubleshooting

### "Missing packages"
```bash
pip3 install requests
```

### "Backend code not found"
```bash
# Find it
find ~ -name "crypto_com_trade.py" 2>/dev/null

# Navigate there
cd /path/to/backend
```

### "Credentials not set"
```bash
# Find .env file
find ~ -name ".env.local" 2>/dev/null

# Or set manually
export EXCHANGE_CUSTOM_API_KEY="your_key"
export EXCHANGE_CUSTOM_API_SECRET="your_secret"
```

