# 🚀 Running Diagnostics on AWS via SSH

## Quick Start

### Step 1: SSH to AWS Server

```bash
ssh your-aws-server
# or
ssh ubuntu@your-aws-ip
```

### Step 2: Navigate to Backend Directory

```bash
# Common locations (try these):
cd ~/automated-trading-platform/backend
# or
cd /opt/automated-trading-platform/backend
# or
cd /home/ubuntu/automated-trading-platform/backend
```

### Step 3: Run Diagnostic Scripts

#### Option A: Use Shell Wrappers (Recommended)

```bash
# Deep diagnostic (step-by-step signature testing)
bash scripts/deep_auth_diagnostic_aws.sh

# Comprehensive diagnostic
bash scripts/diagnose_auth_40101_aws.sh

# Connection test
bash scripts/test_crypto_connection_aws.sh
```

#### Option B: Run Python Scripts Directly

```bash
# Make sure environment variables are loaded
export LIVE_TRADING=true

# Run diagnostic
python3 scripts/deep_auth_diagnostic.py

# Or comprehensive diagnostic
python3 scripts/diagnose_auth_40101.py

# Or connection test
python3 scripts/test_crypto_connection.py
```

## Finding Your Backend Directory

If you're not sure where the backend code is:

```bash
# Search for the backend directory
find ~ -name "crypto_com_trade.py" 2>/dev/null | head -1

# Or search in common locations
find /opt /home -name "crypto_com_trade.py" 2>/dev/null | head -1
```

## Loading Environment Variables

The scripts will automatically try to load from:
1. `$PROJECT_ROOT/.env.local`
2. `$PROJECT_ROOT/.env`
3. `$HOME/.env.local`
4. `/opt/automated-trading-platform/.env.local`
5. `/home/ubuntu/automated-trading-platform/.env.local`

### Manual Environment Setup

If automatic loading doesn't work:

```bash
# Find your .env file
find ~ -name ".env.local" 2>/dev/null | head -1

# Load it manually
source /path/to/.env.local

# Or export variables directly
export EXCHANGE_CUSTOM_API_KEY="your_api_key"
export EXCHANGE_CUSTOM_API_SECRET="your_api_secret"
export LIVE_TRADING="true"
```

## Required Python Packages

Make sure these are installed:

```bash
pip3 install requests
# The other packages (hmac, hashlib, json) are standard library
```

## Quick Diagnostic Commands

### 1. Deep Diagnostic (Most Detailed)

```bash
cd ~/automated-trading-platform/backend
bash scripts/deep_auth_diagnostic_aws.sh
```

**What it shows:**
- Step-by-step signature generation
- String-to-sign construction
- Encoding verification
- Actual API requests
- Detailed error analysis

### 2. Comprehensive Diagnostic

```bash
cd ~/automated-trading-platform/backend
bash scripts/diagnose_auth_40101_aws.sh
```

**What it shows:**
- Environment variable check
- Outbound IP address
- API testing
- Specific recommendations

### 3. Connection Test

```bash
cd ~/automated-trading-platform/backend
bash scripts/test_crypto_connection_aws.sh
```

**What it shows:**
- Public API test
- Private API test
- Open orders test
- Order history test

## Troubleshooting

### Issue: "Cannot find backend code"

**Solution:**
```bash
# Find where the backend code is
find ~ -name "crypto_com_trade.py" 2>/dev/null

# Navigate to that directory's parent
cd /path/to/backend
```

### Issue: "python3 not found"

**Solution:**
```bash
# Install Python 3
sudo apt-get update
sudo apt-get install python3 python3-pip
```

### Issue: "Missing required packages"

**Solution:**
```bash
pip3 install requests
```

### Issue: "Environment variables not loaded"

**Solution:**
```bash
# Find and load .env file manually
find ~ -name ".env.local" 2>/dev/null
source /path/to/.env.local

# Or export directly
export EXCHANGE_CUSTOM_API_KEY="your_key"
export EXCHANGE_CUSTOM_API_SECRET="your_secret"
```

### Issue: "Permission denied"

**Solution:**
```bash
# Make scripts executable
chmod +x scripts/*.sh
chmod +x scripts/*.py
```

## Expected Output

### ✅ Success
```
✅ Private API works! Found X account(s)
✅ Open orders API works! Found X open order(s)
```

### ❌ Failure
```
❌ Private API error: Crypto.com API authentication failed: Authentication failure (code: 40101)
```

## Next Steps After Running Diagnostics

1. **If signature generation fails:**
   - Check credential format
   - Verify encoding
   - Check for hidden characters

2. **If signature works but request fails:**
   - Enable "Read" permission in Crypto.com Exchange
   - Check API key status
   - Verify IP whitelist

3. **If all tests pass:**
   - ✅ Authentication is working!
   - Check why daily summary still fails (might be a different issue)

## Quick Reference

```bash
# SSH to server
ssh your-aws-server

# Navigate to backend
cd ~/automated-trading-platform/backend

# Run deep diagnostic
bash scripts/deep_auth_diagnostic_aws.sh

# Or run directly
python3 scripts/deep_auth_diagnostic.py
```

## Files Created

- `deep_auth_diagnostic_aws.sh` - Shell wrapper for deep diagnostic
- `diagnose_auth_40101_aws.sh` - Shell wrapper for comprehensive diagnostic
- `test_crypto_connection_aws.sh` - Shell wrapper for connection test
- `RUN_DIAGNOSTICS_ON_AWS.md` - This guide

All scripts automatically:
- Find the backend directory
- Load environment variables
- Check for required packages
- Run the Python diagnostic scripts

