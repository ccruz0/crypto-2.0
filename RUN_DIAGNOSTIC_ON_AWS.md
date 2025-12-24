# 🚀 Run Diagnostic on AWS - Actual Commands

## Your AWS Server

Based on your deployment scripts, your AWS server appears to be:

**IP Address:** `175.41.189.249`  
**User:** `ubuntu`

## Commands to Run

### Option 1: One-Liner (from your local machine)

```bash
# Test setup first
ssh ubuntu@175.41.189.249 "cd ~/automated-trading-platform/backend && python3 scripts/test_script_works.py"

# Then run deep diagnostic
ssh ubuntu@175.41.189.249 "cd ~/automated-trading-platform/backend && python3 scripts/deep_auth_diagnostic.py"

# Or run comprehensive diagnostic
ssh ubuntu@175.41.189.249 "cd ~/automated-trading-platform/backend && python3 scripts/diagnose_auth_40101.py"

# Or connection test
ssh ubuntu@175.41.189.249 "cd ~/automated-trading-platform/backend && python3 scripts/test_crypto_connection.py"
```

### Option 2: SSH First, Then Run (Interactive)

```bash
# 1. SSH to AWS
ssh ubuntu@175.41.189.249

# 2. Navigate to backend
cd ~/automated-trading-platform/backend

# 3. Test setup
python3 scripts/test_script_works.py

# 4. Run diagnostic
python3 scripts/deep_auth_diagnostic.py
```

### Option 3: All-in-One Test

```bash
ssh ubuntu@175.41.189.249 "cd ~/automated-trading-platform/backend && python3 scripts/test_script_works.py && echo '---' && python3 scripts/deep_auth_diagnostic.py"
```

## If IP or User is Different

If your AWS server details are different, replace:
- `175.41.189.249` with your actual AWS IP or hostname
- `ubuntu` with your actual username (could be `ec2-user`, `admin`, etc.)

To find your AWS server details:
- Check your AWS EC2 console
- Check your SSH config: `cat ~/.ssh/config`
- Check deployment scripts: `grep -r "ssh.*@" deploy*.sh`

## Alternative: If Using SSH Key

If you use an SSH key file:

```bash
ssh -i /path/to/your-key.pem ubuntu@175.41.189.249 "cd ~/automated-trading-platform/backend && python3 scripts/deep_auth_diagnostic.py"
```

## What to Expect

### ✅ If Setup is Correct:
```
✅ All checks passed! Diagnostic scripts should work.
```

### ❌ If Authentication Fails:
```
❌ Private API error: Crypto.com API authentication failed: Authentication failure (code: 40101)
```

The diagnostic will show:
- Your outbound IP (for whitelist)
- Exact signature generation process
- Specific recommendations to fix

## Next Steps After Running

1. **If you see error 40101:**
   - Note the outbound IP shown
   - Go to https://exchange.crypto.com/ → Settings → API Keys
   - Edit your API key
   - Enable "Read" permission ✅
   - Add the outbound IP to whitelist
   - Wait 30 seconds
   - Run diagnostic again

2. **If authentication works:**
   - ✅ Great! The issue is resolved
   - Check why daily summary might still fail (could be a different issue)

