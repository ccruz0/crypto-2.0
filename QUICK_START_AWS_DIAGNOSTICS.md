# 🚀 Quick Start: Run Diagnostics on AWS via SSH

## One-Liner Commands

### SSH and Run Deep Diagnostic
```bash
ssh your-aws-server "cd ~/crypto-2.0/backend && python3 scripts/deep_auth_diagnostic.py"
```

### SSH and Run Comprehensive Diagnostic
```bash
ssh your-aws-server "cd ~/crypto-2.0/backend && python3 scripts/diagnose_auth_40101.py"
```

### SSH and Run Connection Test
```bash
ssh your-aws-server "cd ~/crypto-2.0/backend && python3 scripts/test_crypto_connection.py"
```

## Step-by-Step (Interactive)

### 1. SSH to AWS Server
```bash
ssh your-aws-server
# or
ssh ubuntu@your-aws-ip
```

### 2. Navigate to Backend
```bash
# Try these locations:
cd ~/crypto-2.0/backend
# or
cd /opt/automated-trading-platform/backend
# or find it:
find ~ -name "crypto_com_trade.py" 2>/dev/null | head -1 | xargs dirname | xargs dirname
```

### 3. Run Diagnostic

**Option A: Use Shell Wrapper**
```bash
bash scripts/deep_auth_diagnostic_aws.sh
```

**Option B: Run Python Directly**
```bash
python3 scripts/deep_auth_diagnostic.py
```

## What Each Script Does

### `deep_auth_diagnostic.py` (Most Detailed)
- Shows step-by-step signature generation
- Tests encoding and string construction
- Makes actual API requests
- Provides detailed error analysis

**Best for:** Understanding exactly what's happening

### `diagnose_auth_40101.py` (Comprehensive)
- Checks environment variables
- Shows outbound IP
- Tests API endpoints
- Provides specific recommendations

**Best for:** General troubleshooting

### `test_crypto_connection.py` (Quick Test)
- Tests public API
- Tests private API
- Tests open orders
- Tests order history

**Best for:** Quick verification

## Environment Variables

The scripts automatically:
1. ✅ Try to load from `.env.local` files (multiple locations)
2. ✅ Use system environment variables if set
3. ✅ Show what was loaded

**Manual setup (if needed):**
```bash
export EXCHANGE_CUSTOM_API_KEY="your_key"
export EXCHANGE_CUSTOM_API_SECRET="your_secret"
export LIVE_TRADING="true"
```

## Expected Output

### ✅ Success
```
✅ Private API works! Found X account(s)
✅ Open orders API works! Found X open order(s)
```

### ❌ Failure (with full error code now!)
```
❌ Private API error: Crypto.com API authentication failed: Authentication failure (code: 40101)
```

## Most Common Fix

After running diagnostic, if you see error 40101:

1. Go to https://exchange.crypto.com/ → Settings → API Keys
2. Edit your API key
3. **Enable "Read" permission** ✅
4. Save
5. Wait 30 seconds
6. Run diagnostic again

## Files Available

All scripts work directly on AWS:
- ✅ `deep_auth_diagnostic.py` - Step-by-step testing
- ✅ `diagnose_auth_40101.py` - Comprehensive diagnostic
- ✅ `test_crypto_connection.py` - Connection test
- ✅ `verify_api_key_setup.py` - Setup verification

Shell wrappers (optional):
- `deep_auth_diagnostic_aws.sh`
- `diagnose_auth_40101_aws.sh`
- `test_crypto_connection_aws.sh`

## Troubleshooting

**"Cannot find backend code"**
```bash
find ~ -name "crypto_com_trade.py" 2>/dev/null
```

**"python3 not found"**
```bash
which python3
# or
python3 --version
```

**"Missing packages"**
```bash
pip3 install requests
```

**"Environment variables not loaded"**
```bash
# Check if set
echo $EXCHANGE_CUSTOM_API_KEY

# Or find .env file
find ~ -name ".env.local" 2>/dev/null
```

## Full Documentation

See `RUN_DIAGNOSTICS_ON_AWS.md` for complete guide.

