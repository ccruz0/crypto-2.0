# DNS Update Instructions for dashboard.hilovivo.com

## Current Status

✅ **Server is fully operational and ready**
- Server IP: `47.130.143.159`
- All containers healthy (frontend, backend, db)
- Nginx configured and running
- SSL certificate valid (expires 2026-02-03)
- Server responds correctly when accessed directly

❌ **DNS points to old IP**
- Current DNS: `dashboard.hilovivo.com` → `175.41.189.249` (OLD)
- Required DNS: `dashboard.hilovivo.com` → `47.130.143.159` (NEW)

## Action Required: Update DNS Record

### Step 1: Identify Your DNS Provider

Check where your DNS is managed:
- **Cloudflare**: If you see Cloudflare nameservers
- **AWS Route53**: If using AWS for DNS
- **Domain Registrar**: GoDaddy, Namecheap, etc.
- **Other**: Check your domain registrar's DNS settings

To check:
```bash
dig NS hilovivo.com
```

### Step 2: Update the A Record

**Record Type**: A  
**Name**: `dashboard` (or `dashboard.hilovivo.com` depending on provider)  
**Value**: `47.130.143.159`  
**TTL**: 300 seconds (5 minutes) - use low TTL initially for faster propagation

**Example for Cloudflare**:
1. Log in to Cloudflare dashboard
2. Select domain: `hilovivo.com`
3. Go to DNS → Records
4. Find A record for `dashboard` (or `dashboard.hilovivo.com`)
5. Edit: Change IP from `175.41.189.249` to `47.130.143.159`
6. Set TTL to 5 minutes (Auto)
7. Save

**Example for AWS Route53**:
1. AWS Console → Route53 → Hosted zones
2. Select `hilovivo.com`
3. Find A record: `dashboard.hilovivo.com`
4. Edit: Change value to `47.130.143.159`
5. Set TTL to 300
6. Save

### Step 3: Verify DNS Propagation

After updating, verify DNS has propagated:

```bash
# Check DNS resolution
dig +short dashboard.hilovivo.com A

# Should return: 47.130.143.159
```

Wait 5-60 minutes (depending on TTL) and check from multiple locations:
- https://www.whatsmydns.net/#A/dashboard.hilovivo.com
- https://dnschecker.org/#A/dashboard.hilovivo.com

### Step 4: Test Dashboard

Once DNS propagates:

```bash
# Test HTTP (should redirect to HTTPS)
curl -I http://dashboard.hilovivo.com

# Test HTTPS (should return 200)
curl -I https://dashboard.hilovivo.com

# Test in browser
# Open: https://dashboard.hilovivo.com
```

### Step 5: Verify SSL Certificate

After DNS update, verify SSL certificate is valid:

```bash
curl -Iv https://dashboard.hilovivo.com
```

The certificate should be valid for `dashboard.hilovivo.com` and issued by Let's Encrypt.

## Verification Checklist

- [ ] DNS A record updated to `47.130.143.159`
- [ ] DNS propagated (check with `dig` or online tools)
- [ ] HTTP redirects to HTTPS (301)
- [ ] HTTPS returns 200 OK
- [ ] SSL certificate valid
- [ ] Dashboard loads in browser
- [ ] API calls succeed (check browser Network tab)

## Troubleshooting

### DNS Still Points to Old IP

- Wait longer (DNS propagation can take up to 48 hours with high TTL)
- Clear DNS cache: `sudo dscacheutil -flushcache` (macOS)
- Check from different network/location
- Verify DNS record was saved correctly in DNS provider

### SSL Certificate Errors

If you see certificate errors after DNS update:
- Wait a few minutes for certificate validation
- The certificate is already installed and valid on the server
- If issues persist, renew certificate:
  ```bash
  ssh hilovivo-aws 'sudo certbot renew --nginx -d dashboard.hilovivo.com'
  ```

### Dashboard Still Not Loading

1. Verify DNS: `dig +short dashboard.hilovivo.com A`
2. Check server: `curl -I https://47.130.143.159 -H "Host: dashboard.hilovivo.com"`
3. Check containers: `ssh hilovivo-aws 'docker compose --profile aws ps'`
4. Check nginx: `ssh hilovivo-aws 'sudo systemctl status nginx'`
5. Check logs: `ssh hilovivo-aws 'sudo tail -f /var/log/nginx/error.log'`

## Server Status (Verified)

✅ **All systems operational**:
- Frontend: Running on port 3000
- Backend: Running on port 8002
- Database: Running on port 5432
- Nginx: Running and routing correctly
- SSL: Certificate valid until 2026-02-03
- HTTP: Redirects to HTTPS (301)
- HTTPS: Returns 200 OK

**The server is ready. Only DNS update is needed.**

