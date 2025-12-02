# BTC BUY INDEX Zombie Emitter Cleanup Report

**Date:** 2025-11-29  
**Status:** ✅ RESOLVED

## Problem
BTC BUY INDEX alerts were being sent repeatedly, even after throttling fixes were implemented in BuyIndexMonitorService.

## Root Cause
A **zombie systemd service** (`crypto-trading.service`) was running an old backend instance outside Docker:
- **Service:** `crypto-trading.service`
- **Processes:** Two Python processes (PIDs 2792569 and 3102798)
- **Command:** `/usr/bin/python3 /home/ubuntu/automated-trading-platform/working_crypto_server.py`
- **Status:** The file `working_crypto_server.py` no longer exists, but the processes were still running from a previous deployment
- **Location:** Running directly on the host (not in Docker)

This old backend instance was running its own BuyIndexMonitorService, which was sending BTC BUY INDEX alerts without the latest throttling logic.

## Solution Executed

### 1. Stopped the zombie service
```bash
sudo systemctl stop crypto-trading.service
```

### 2. Disabled the service from auto-starting
```bash
sudo systemctl disable crypto-trading.service
```

### 3. Killed any remaining processes
```bash
sudo pkill -f working_crypto_server.py
```

## Verification

### Before Cleanup
- Multiple backend instances running (Docker + systemd)
- Old processes (PIDs 2792569, 3102798) running `working_crypto_server.py`
- `crypto-trading.service` active and enabled

### After Cleanup
- ✅ `crypto-trading.service` stopped and disabled
- ✅ Zombie processes terminated
- ✅ Only legitimate backend running: `automated-trading-platform-backend-aws-1` (Docker)
- ✅ BuyIndexMonitorService running only in Docker backend

## Current State

### Active Services
1. **Docker Backend** (`automated-trading-platform-backend-aws-1`)
   - Running BuyIndexMonitorService with latest throttling logic
   - Only legitimate emitter of BTC BUY INDEX alerts

2. **Crypto Proxy** (`crypto-proxy.service`)
   - Not related to alerts (just a proxy service)

### Disabled Services
- `crypto-trading.service` - **DISABLED** (was the zombie emitter)

## Commands for Future Verification

To verify only one emitter is active:
```bash
# Check for zombie processes
ps aux | grep -E "working_crypto_server|buy_index" | grep -v grep

# Check systemd services
systemctl status crypto-trading.service

# Check Docker backend is running
docker ps | grep backend-aws

# Check BuyIndexMonitorService logs
cd /Users/carloscruz/automated-trading-platform && bash scripts/aws_backend_logs.sh | grep -i "BuyIndexMonitorService"
```

## Expected Behavior
- BTC BUY INDEX alerts should only come from the Docker backend
- Alerts should respect throttling rules (price change and time cooldown)
- No duplicate alerts from multiple emitters

## Notes
- The `crypto-trading.service` was likely from an older deployment method before Docker Compose was fully adopted
- The service file still exists at `/etc/systemd/system/crypto-trading.service` but is now disabled
- If needed in the future, the service can be removed entirely with: `sudo rm /etc/systemd/system/crypto-trading.service`


