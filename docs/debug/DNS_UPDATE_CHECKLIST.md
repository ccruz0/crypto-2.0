# DNS Update Checklist for dashboard.hilovivo.com

## Pre-Update Status

✅ **Server is ready and operational**
- Server IP: `47.130.143.159`
- All services healthy (frontend, backend, database, nginx)
- SSL certificate valid until 2026-02-03
- Server responds correctly when accessed directly

❌ **DNS needs update**
- Current: `dashboard.hilovivo.com` → `175.41.189.249` (OLD)
- Required: `dashboard.hilovivo.com` → `47.130.143.159` (NEW)

## Step-by-Step DNS Update

### Step 1: Identify DNS Provider

```bash
# Check nameservers
dig NS hilovivo.com

# Common providers:
# - Cloudflare: ns1.cloudflare.com, ns2.cloudflare.com
# - AWS Route53: ns-*.awsdns-*.com
# - GoDaddy: ns*.domaincontrol.com
# - Namecheap: dns1.registrar-servers.com
```

### Step 2: Update A Record

**Record Details**:
- **Type**: A
- **Name**: `dashboard` (or `dashboard.hilovivo.com`)
- **Value**: `47.130.143.159`
- **TTL**: 300 (5 minutes) - use low TTL initially

**Provider-Specific Instructions**:

#### Cloudflare
1. Log in to https://dash.cloudflare.com
2. Select domain: `hilovivo.com`
3. DNS → Records
4. Find/edit A record for `dashboard`
5. Change IP to `47.130.143.159`
6. Set TTL to "Auto" (or 300)
7. Save

#### AWS Route53
1. AWS Console → Route53 → Hosted zones
2. Select `hilovivo.com`
3. Find A record: `dashboard.hilovivo.com`
4. Edit → Change value to `47.130.143.159`
5. Set TTL to 300
6. Save changes

#### Other Providers
1. Log in to your DNS provider
2. Navigate to DNS management
3. Find A record for `dashboard.hilovivo.com`
4. Update IP to `47.130.143.159`
5. Save

### Step 3: Verify DNS Propagation

Wait 5-60 minutes (depending on TTL), then check:

```bash
# Local check
dig +short dashboard.hilovivo.com A
# Should return: 47.130.143.159

# Online tools
# https://www.whatsmydns.net/#A/dashboard.hilovivo.com
# https://dnschecker.org/#A/dashboard.hilovivo.com
```

### Step 4: Run Verification Script

After DNS propagates, run the verification script:

```bash
./scripts/verify_dashboard_dns.sh
```

This will check:
- ✅ DNS resolution
- ✅ HTTP redirect
- ✅ HTTPS access
- ✅ SSL certificate
- ✅ Frontend content
- ✅ API health
- ✅ API dashboard endpoint

### Step 5: Manual Browser Test

1. Open browser: `https://dashboard.hilovivo.com`
2. Check browser console (F12) for errors
3. Check Network tab - API calls should return 200
4. Verify dashboard UI loads correctly
5. Test functionality (portfolio, watchlist, etc.)

## Troubleshooting

### DNS Still Shows Old IP

- **Wait longer**: DNS propagation can take up to 48 hours with high TTL
- **Clear DNS cache**:
  ```bash
  # macOS
  sudo dscacheutil -flushcache
  
  # Linux
  sudo systemd-resolve --flush-caches
  
  # Windows
  ipconfig /flushdns
  ```
- **Check from different network**: Use mobile data or VPN
- **Verify DNS record saved**: Double-check in DNS provider dashboard

### SSL Certificate Errors

If you see certificate errors:
- Wait a few minutes after DNS update
- Certificate is already installed on server
- If issues persist:
  ```bash
  ssh hilovivo-aws 'sudo certbot renew --nginx -d dashboard.hilovivo.com'
  ```

### Dashboard Not Loading

1. **Verify DNS**: `dig +short dashboard.hilovivo.com A`
2. **Test direct IP**: `curl -I https://47.130.143.159 -H "Host: dashboard.hilovivo.com"`
3. **Check containers**: `ssh hilovivo-aws 'docker compose --profile aws ps'`
4. **Check nginx**: `ssh hilovivo-aws 'sudo systemctl status nginx'`
5. **Check logs**: `ssh hilovivo-aws 'sudo tail -f /var/log/nginx/error.log'`

### API Calls Failing

1. **Check API health**: `curl https://dashboard.hilovivo.com/api/health`
2. **Check backend**: `ssh hilovivo-aws 'docker compose --profile aws logs backend-aws'`
3. **Verify CORS**: Check browser console for CORS errors
4. **Check network**: Verify no firewall blocking

## Success Criteria

✅ All of these should pass:
- [ ] DNS resolves to `47.130.143.159`
- [ ] HTTP redirects to HTTPS (301)
- [ ] HTTPS returns 200 OK
- [ ] SSL certificate is valid
- [ ] Dashboard UI loads in browser
- [ ] No console errors
- [ ] API calls succeed (Network tab shows 200)
- [ ] Portfolio data loads
- [ ] Watchlist loads

## Post-Update

Once everything is working:

1. **Increase TTL** (optional): Change DNS TTL from 300 to 3600 (1 hour) for better caching
2. **Monitor**: Check dashboard regularly for first 24 hours
3. **Document**: Note the DNS update date/time for future reference

## Support

If issues persist after DNS update:
1. Run verification script: `./scripts/verify_dashboard_dns.sh`
2. Check server logs: `ssh hilovivo-aws 'docker compose --profile aws logs'`
3. Review root cause report: `docs/debug/dashboard-hilovivo-root-cause.md`

