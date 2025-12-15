# Hostinger DNS Update Guide

**Domain**: `hilovivo.com`  
**Registrar**: Hostinger  
**Current DNS**: Points to old IP `175.41.189.249`  
**Required DNS**: Point to new IP `47.130.143.159`

## Quick Steps

### Option 1: Update via Hostinger Control Panel

1. **Log in to Hostinger**:
   - Go to: https://www.hostinger.com/cpanel
   - Or: https://hpanel.hostinger.com

2. **Navigate to DNS Management**:
   - Go to **Domains** → **hilovivo.com**
   - Click **DNS / Name Servers**
   - Or look for **DNS Zone Editor** / **DNS Management**

3. **Find and Edit A Record**:
   - Look for A record with name: `dashboard` (or `dashboard.hilovivo.com`)
   - Current value: `175.41.189.249`
   - **Change to**: `47.130.143.159`
   - TTL: Set to 300 (5 minutes) or leave default
   - **Save**

4. **If A record doesn't exist**:
   - Click **Add Record**
   - Type: **A**
   - Name: `dashboard` (or `dashboard.hilovivo.com`)
   - Value: `47.130.143.159`
   - TTL: 300
   - **Save**

### Option 2: Change Nameservers to Cloudflare (Recommended)

If you want better DNS management, consider moving DNS to Cloudflare:

1. **Sign up for Cloudflare** (free): https://dash.cloudflare.com/sign-up
2. **Add domain**: Add `hilovivo.com` to Cloudflare
3. **Get nameservers**: Cloudflare will provide nameservers (e.g., `ns1.cloudflare.com`)
4. **Update nameservers in Hostinger**:
   - Hostinger → Domains → hilovivo.com → DNS / Name Servers
   - Change nameservers to Cloudflare's nameservers
5. **Update DNS in Cloudflare**:
   - Cloudflare Dashboard → DNS → Records
   - Add/Edit A record: `dashboard` → `47.130.143.159`

## Verification

After updating DNS:

```bash
# Check DNS resolution
dig +short dashboard.hilovivo.com A
# Should return: 47.130.143.159

# Run verification script
./scripts/verify_dashboard_dns.sh

# Test in browser
# https://dashboard.hilovivo.com
```

## Troubleshooting

### Can't Find DNS Settings in Hostinger

- Look for: **DNS Zone**, **DNS Management**, **DNS Records**, **Advanced DNS**
- Contact Hostinger support if you can't find DNS settings

### DNS Not Updating

- Wait 5-60 minutes for propagation
- Clear DNS cache:
  ```bash
  # macOS
  sudo dscacheutil -flushcache
  
  # Linux
  sudo systemd-resolve --flush-caches
  ```
- Check from different network/location

### Still Points to Old IP

- Verify DNS record was saved correctly
- Check TTL - if it's high (3600+), wait longer
- Try accessing via direct IP: `https://47.130.143.159` (with Host header)

## Contact Information

**Hostinger Support**:
- Website: https://www.hostinger.com/contact
- Email: support@hostinger.com
- Phone: Check Hostinger website for current support number

## Alternative: Use Script

Run the helper script for current status:

```bash
./scripts/update_dashboard_dns.sh
```

This will show:
- Current DNS status
- Required changes
- Step-by-step instructions

