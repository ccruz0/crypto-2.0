# Deployment Instructions: Code Review Improvements

## Changes Deployed

1. **Improved Error Handling** - Better logging and exception handling in `_get_market_data_for_symbol()`
2. **HSTS Header** - Added Strict-Transport-Security header for enhanced security
3. **Rate Limiting** - Added rate limiting to API endpoints (DoS protection)
4. **Request Size Limits** - Added 10M limit for file uploads

## Deployment Steps

### 1. Pull Latest Code (on AWS server)

```bash
cd /home/ubuntu/automated-trading-platform
git pull origin main
```

### 2. Rebuild Backend Docker Image

```bash
docker compose build backend-aws
```

### 3. Restart Backend Service

```bash
docker compose restart backend-aws
```

### 4. Update Nginx Configuration

```bash
# Copy nginx config to server
sudo cp nginx/dashboard.conf /etc/nginx/sites-available/dashboard.hilovivo.com

# Test nginx configuration
sudo nginx -t

# If test passes, reload nginx
sudo systemctl reload nginx
```

**Important:** The rate limiting zones must be defined in the `http` block of nginx.conf. If they're not already there, add them:

```bash
# Edit main nginx config
sudo nano /etc/nginx/nginx.conf

# Add these lines in the http block (if not present):
# limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;
# limit_req_zone $binary_remote_addr zone=monitoring_limit:10m rate=5r/s;

# Then test and reload
sudo nginx -t
sudo systemctl reload nginx
```

### 5. Verify Deployment

#### Test Backend

```bash
# Check backend is running
docker compose ps backend-aws

# Check logs for errors
docker compose logs backend-aws --tail 50 | grep -i "error\|exception"

# Test API endpoint
curl -s http://localhost:8002/api/dashboard | jq '.[0] | {symbol, price, rsi}'
```

#### Test Nginx Configuration

```bash
# Test nginx config
sudo nginx -t

# Check rate limiting (should work normally)
curl -s https://dashboard.hilovivo.com/api/dashboard | head -20

# Check HSTS header
curl -I https://dashboard.hilovivo.com 2>&1 | grep -i "strict-transport"
```

**Expected:** Should see `Strict-Transport-Security: max-age=31536000; includeSubDomains`

#### Test Rate Limiting

```bash
# Make rapid requests (should eventually get 429)
for i in {1..15}; do
  curl -s -o /dev/null -w "%{http_code}\n" https://dashboard.hilovivo.com/api/dashboard
  sleep 0.1
done
```

**Expected:** First 10-20 requests succeed, then 429 (Too Many Requests)

### 6. Monitor Logs

```bash
# Watch backend logs
docker compose logs -f backend-aws | grep -i "marketdata\|error\|warning"

# Watch nginx logs for rate limiting
sudo tail -f /var/log/nginx/access.log | grep "429"
```

## What Changed

### Backend (`routes_dashboard.py`)

**Before:**
```python
def _get_market_data_for_symbol(db: Session, symbol: str) -> Optional[Any]:
    try:
        return db.query(MarketData).filter(MarketData.symbol == symbol).first()
    except Exception:
        return None  # Silent failure
```

**After:**
```python
def _get_market_data_for_symbol(db: Session, symbol: str) -> Optional[Any]:
    try:
        symbol_upper = symbol.upper() if symbol else ""
        return db.query(MarketData).filter(MarketData.symbol == symbol_upper).first()
    except sqlalchemy.exc.SQLAlchemyError as e:
        log.warning(f"Database error fetching MarketData for {symbol}: {e}")
        return None
    except Exception as e:
        log.error(f"Unexpected error fetching MarketData for {symbol}: {e}", exc_info=True)
        return None
```

**Benefits:**
- ✅ Better error visibility (logs warnings/errors)
- ✅ Case-insensitive symbol matching
- ✅ Specific exception handling

### Nginx (`dashboard.conf`)

**Added:**
1. **HSTS Header:**
   ```nginx
   add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
   ```

2. **Rate Limiting:**
   ```nginx
   limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;
   limit_req_zone $binary_remote_addr zone=monitoring_limit:10m rate=5r/s;
   
   location /api {
       limit_req zone=api_limit burst=20 nodelay;
   }
   ```

3. **Request Size Limits:**
   ```nginx
   client_max_body_size 10M;
   ```

**Benefits:**
- ✅ Enhanced security (HSTS)
- ✅ DoS protection (rate limiting)
- ✅ Prevents large file uploads

## Rollback Instructions

If issues occur:

```bash
# Revert to previous commit
git revert HEAD

# Rebuild backend
docker compose build backend-aws
docker compose restart backend-aws

# Restore old nginx config
sudo cp nginx/dashboard.conf.backup /etc/nginx/sites-available/dashboard.hilovivo.com
sudo nginx -t
sudo systemctl reload nginx
```

## Verification Checklist

- [ ] Backend service running
- [ ] No errors in backend logs
- [ ] Nginx config test passes
- [ ] HSTS header present in responses
- [ ] Rate limiting working (429 on excessive requests)
- [ ] API endpoints still accessible
- [ ] Frontend still works correctly

## Troubleshooting

### Issue: Nginx config test fails

**Error:** `unknown directive "limit_req_zone"`

**Solution:** Rate limiting zones must be in the `http` block of `/etc/nginx/nginx.conf`, not in the server block.

### Issue: Rate limiting too aggressive

**Solution:** Adjust rates in nginx.conf:
```nginx
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=20r/s;  # Increase rate
```

### Issue: HSTS header not appearing

**Solution:** 
- Ensure you're accessing via HTTPS (not HTTP)
- Check nginx config is loaded: `sudo nginx -t`
- Verify header in response: `curl -I https://dashboard.hilovivo.com`

## Post-Deployment

1. **Monitor for 24 hours** - Watch for any rate limiting issues
2. **Check error logs** - Verify improved error visibility
3. **Test rate limiting** - Ensure legitimate users aren't blocked
4. **Verify HSTS** - Check browser shows secure connection

## Support

If issues occur:
1. Check backend logs: `docker compose logs backend-aws`
2. Check nginx logs: `sudo tail -f /var/log/nginx/error.log`
3. Test nginx config: `sudo nginx -t`
4. Verify rate limiting: Check for 429 responses in access.log
