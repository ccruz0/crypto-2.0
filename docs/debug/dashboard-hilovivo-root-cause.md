# Dashboard Hilovivo Root Cause Analysis

**Date**: 2025-12-15  
**Issue**: `https://dashboard.hilovivo.com` does not load in browser  
**Status**: Root cause identified, DNS update required

## Executive Summary

The dashboard fails to load because DNS for `dashboard.hilovivo.com` points to the old server IP (`175.41.189.249`) instead of the current server IP (`47.130.143.159`). The server infrastructure is functioning correctly - nginx, frontend, and backend are all operational when accessed directly via the new IP.

## Symptoms

### Browser Behavior
- **URL**: `https://dashboard.hilovivo.com`
- **Result**: Blank screen, connection timeout
- **Network Error**: TLS handshake fails with `SSL_ERROR_SYSCALL` after ~12 seconds
- **Status Code**: Connection never completes (no HTTP response)

### Comparison: lovivo.com
- **URL**: `https://lovivo.com`
- **Result**: ✅ Loads successfully
- **DNS**: Resolves to `54.243.117.197` and `13.223.25.84`
- **TLS**: Handshake completes successfully

## Investigation Results

### 1. DNS Resolution

```bash
$ dig +short dashboard.hilovivo.com A
175.41.189.249  # ❌ OLD IP (wrong)

$ dig +short lovivo.com A
54.243.117.197
13.223.25.84
```

**Finding**: `dashboard.hilovivo.com` DNS A record points to `175.41.189.249` (old IP).

### 2. Server Current IP

```bash
$ ssh hilovivo-aws 'curl -s ifconfig.me'
47.130.143.159  # ✅ CURRENT IP (correct)
```

**Finding**: Server's current public IP is `47.130.143.159`.

### 3. Direct IP Access Test

```bash
$ curl -Ik https://47.130.143.159 -H "Host: dashboard.hilovivo.com"
HTTP/2 200 
server: nginx/1.24.0 (Ubuntu)
content-type: text/html; charset=utf-8
```

**Finding**: ✅ Server responds correctly when accessed via direct IP with correct Host header.

### 4. TLS Handshake Failure

```bash
$ curl -Iv https://dashboard.hilovivo.com
* Connected to dashboard.hilovivo.com (175.41.189.249) port 443
* TLS handshake, Client hello (1):
* [12 second timeout]
* LibreSSL SSL_connect: SSL_ERROR_SYSCALL
```

**Finding**: Connection attempts go to `175.41.189.249` (old IP), which either:
- No longer exists
- Has firewall blocking 443
- Is not running nginx/SSL service

### 5. Server Infrastructure Status

#### Containers (All Healthy)
```
✅ frontend-aws: Up 5 minutes (healthy) - Port 3000
✅ backend-aws: Up 2 hours (healthy) - Port 8002
✅ db: Up 2 hours (healthy) - Port 5432
✅ gluetun: Up 2 hours (healthy)
```

#### Nginx Status
```bash
$ sudo systemctl status nginx
● nginx.service - A high performance web server and a reverse proxy server
   Active: active (running)
```

**Finding**: ✅ All services are running and healthy.

#### Local Routing Test
```bash
$ curl -Ik https://localhost -H "Host: dashboard.hilovivo.com"
HTTP/2 200 
server: nginx/1.24.0 (Ubuntu)
content-type: text/html; charset=utf-8
```

**Finding**: ✅ Nginx correctly routes `dashboard.hilovivo.com` to frontend on port 3000.

### 6. Nginx Configuration Issues (Fixed)

**Problem Found**: Multiple duplicate nginx config files in `/etc/nginx/sites-enabled/`:
- `dashboard.conf` (active)
- `dashboard.conf.backup` (duplicate - removed)
- `dashboard.conf.bak-1763390341` (duplicate - removed)
- `dashboard.conf.bak-1764313291` (duplicate - removed)
- `dashboard.conf.bak.1763290130` (duplicate - removed)

**Nginx Warnings** (before fix):
```
[warn] conflicting server name "dashboard.hilovivo.com" on 0.0.0.0:80, ignored
[warn] conflicting server name "dashboard.hilovivo.com" on 0.0.0.0:443, ignored
```

**Action Taken**: Removed all backup/duplicate config files from `sites-enabled/`.

**Result**: ✅ Nginx config now clean, no conflicts.

### 7. Firewall Status

```bash
$ sudo ufw status
Status: inactive
```

**Finding**: UFW is inactive. AWS Security Group should be checked to ensure ports 80/443 are open.

## Root Cause

**Primary Issue**: DNS A record for `dashboard.hilovivo.com` points to old IP `175.41.189.249` instead of current IP `47.130.143.159`.

**Secondary Issue** (Fixed): Duplicate nginx configs causing server_name conflicts.

## What Changed

Based on repository history:
- Server IP was changed from `175.41.189.249` to `47.130.143.159`
- This change was made in code/config files (`.env.aws`, deployment scripts)
- **DNS records were NOT updated** to reflect the new IP

## Fix Required

### 1. Update DNS Records (CRITICAL)

Update the DNS A record for `dashboard.hilovivo.com`:

**Current (Wrong)**:
```
dashboard.hilovivo.com.  A  175.41.189.249
```

**Should Be**:
```
dashboard.hilovivo.com.  A  47.130.143.159
```

**Where to Update**:
- If using Cloudflare: DNS dashboard → `dashboard.hilovivo.com` → Edit A record
- If using AWS Route53: Route53 console → Hosted zone → Edit record
- If using other DNS provider: Access their DNS management interface

**TTL**: Consider setting a low TTL (300 seconds) initially for faster propagation, then increase after verification.

### 2. Verify AWS Security Group

Ensure the AWS EC2 Security Group allows inbound traffic:
- **Port 80** (HTTP) from `0.0.0.0/0`
- **Port 443** (HTTPS) from `0.0.0.0/0`

### 3. SSL Certificate Verification

After DNS update, verify SSL certificate is valid:
```bash
curl -Iv https://dashboard.hilovivo.com
```

The certificate should be valid for `dashboard.hilovivo.com` and issued by Let's Encrypt.

## Verification Evidence

### Server Responds Correctly (Direct IP)
```bash
$ curl -I https://47.130.143.159 -H "Host: dashboard.hilovivo.com"
HTTP/2 200 
server: nginx/1.24.0 (Ubuntu)
date: Mon, 15 Dec 2025 06:02:25 GMT
content-type: text/html; charset=utf-8
content-length: 12783
```

### Frontend Container Healthy
```bash
$ docker compose --profile aws ps frontend-aws
STATUS: Up 5 minutes (healthy)
PORTS: 0.0.0.0:3000->3000/tcp
```

### Backend Container Healthy
```bash
$ docker compose --profile aws ps backend-aws
STATUS: Up 2 hours (healthy)
PORTS: 0.0.0.0:8002->8002/tcp
```

### Nginx Routing Works
```bash
$ curl -I http://localhost:80 -H "Host: dashboard.hilovivo.com"
HTTP/1.1 301 Moved Permanently
Location: https://dashboard.hilovivo.com/
```

```bash
$ curl -Ik https://localhost -H "Host: dashboard.hilovivo.com"
HTTP/2 200 
content-type: text/html; charset=utf-8
```

## Files Changed

### Nginx Config Cleanup (Applied)
- Removed: `/etc/nginx/sites-enabled/dashboard.conf.backup`
- Removed: `/etc/nginx/sites-enabled/dashboard.conf.bak-1763390341`
- Removed: `/etc/nginx/sites-enabled/dashboard.conf.bak-1764313291`
- Removed: `/etc/nginx/sites-enabled/dashboard.conf.bak.1763290130`
- Kept: `/etc/nginx/sites-enabled/dashboard.conf` (active config)

## Next Steps

1. **Update DNS** (User action required):
   - Access DNS provider (Cloudflare/AWS Route53/etc.)
   - Change `dashboard.hilovivo.com` A record from `175.41.189.249` to `47.130.143.159`
   - Wait for DNS propagation (typically 5-60 minutes depending on TTL)

2. **Verify DNS Propagation**:
   ```bash
   dig +short dashboard.hilovivo.com A
   # Should return: 47.130.143.159
   ```

3. **Test Dashboard**:
   - Open browser: `https://dashboard.hilovivo.com`
   - Should load dashboard UI
   - Check browser console for errors
   - Verify API calls succeed (Network tab)

4. **Monitor Logs** (if issues persist):
   ```bash
   ssh hilovivo-aws 'docker compose --profile aws logs -f frontend-aws'
   ssh hilovivo-aws 'docker compose --profile aws logs -f backend-aws'
   sudo tail -f /var/log/nginx/error.log
   ```

## Conclusion

The server infrastructure is **fully operational**. The issue is purely a DNS misconfiguration where `dashboard.hilovivo.com` points to an old IP address. Once DNS is updated to point to `47.130.143.159`, the dashboard will load correctly.

**Status**: ✅ Server ready, ⏳ Waiting for DNS update

