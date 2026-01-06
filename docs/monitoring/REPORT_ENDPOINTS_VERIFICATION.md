# Report Endpoints Verification Guide

## 📋 Summary

This document verifies the implementation of report endpoints for accessing watchlist consistency and dedup reports via friendly URLs.

## ✅ Implementation Status

### Backend Endpoints (✅ Complete)

All endpoints are implemented in `backend/app/api/routes_monitoring.py`:

1. **Watchlist Consistency Reports:**
   - `GET /api/monitoring/reports/watchlist-consistency/latest`
   - `GET /api/monitoring/reports/watchlist-consistency/{date}` (YYYYMMDD format)
   - Both support `HEAD` method

2. **Watchlist Dedup Reports:**
   - `GET /api/monitoring/reports/watchlist-dedup/latest`
   - `GET /api/monitoring/reports/watchlist-dedup/{date}` (YYYYMMDD format)
   - Both support `HEAD` method

### Nginx Configuration (✅ Complete)

All rewrite rules are configured in `nginx/dashboard.conf`:

- `/docs/monitoring/watchlist_consistency_report_latest.md` → `/api/monitoring/reports/watchlist-consistency/latest`
- `/docs/monitoring/watchlist_consistency_report_YYYYMMDD.md` → `/api/monitoring/reports/watchlist-consistency/YYYYMMDD`
- `/docs/monitoring/watchlist_dedup_report_latest.md` → `/api/monitoring/reports/watchlist-dedup/latest`
- `/docs/monitoring/watchlist_dedup_report_YYYYMMDD.md` → `/api/monitoring/reports/watchlist-dedup/YYYYMMDD`

### Frontend Timeout Fix (✅ Complete)

- Increased timeout for `/monitoring/workflows` from 30s to 150s
- Increased nginx timeout for monitoring endpoints from 120s to 180s

## 🧪 Testing Checklist

### 1. Test Backend Endpoints Directly

```bash
# Test latest watchlist consistency report
curl -I http://localhost:8002/api/monitoring/reports/watchlist-consistency/latest

# Test dated watchlist consistency report (replace 20251203 with actual date)
curl -I http://localhost:8002/api/monitoring/reports/watchlist-consistency/20251203

# Test latest watchlist dedup report
curl -I http://localhost:8002/api/monitoring/reports/watchlist-dedup/latest

# Test dated watchlist dedup report (replace date if exists)
curl -I http://localhost:8002/api/monitoring/reports/watchlist-dedup/20251203
```

**Expected Results:**
- ✅ 200 OK for existing reports
- ✅ 404 Not Found for non-existent reports
- ✅ 400 Bad Request for invalid date format

### 2. Test Nginx Rewrite Rules

```bash
# Test latest watchlist consistency report via nginx
curl -I https://dashboard.hilovivo.com/docs/monitoring/watchlist_consistency_report_latest.md

# Test dated watchlist consistency report via nginx
curl -I https://dashboard.hilovivo.com/docs/monitoring/watchlist_consistency_report_20251203.md

# Test latest watchlist dedup report via nginx
curl -I https://dashboard.hilovivo.com/docs/monitoring/watchlist_dedup_report_latest.md

# Test dated watchlist dedup report via nginx (if exists)
curl -I https://dashboard.hilovivo.com/docs/monitoring/watchlist_dedup_report_20251203.md
```

**Expected Results:**
- ✅ 200 OK with `Content-Type: text/markdown; charset=utf-8`
- ✅ 404 Not Found for non-existent reports
- ✅ Proper markdown content returned

### 3. Test Invalid Date Format

```bash
# Test with invalid date format
curl -I https://dashboard.hilovivo.com/docs/monitoring/watchlist_consistency_report_2025-12-24.md
curl -I https://dashboard.hilovivo.com/docs/monitoring/watchlist_consistency_report_abc12345.md
```

**Expected Results:**
- ✅ 400 Bad Request or 404 Not Found (depending on nginx rewrite matching)

### 4. Test Browser Access

1. Open browser and navigate to:
   - `https://dashboard.hilovivo.com/docs/monitoring/watchlist_consistency_report_latest.md`
   - `https://dashboard.hilovivo.com/docs/monitoring/watchlist_consistency_report_20251203.md`

2. Verify:
   - ✅ Report displays correctly as markdown
   - ✅ No "Not Found" errors
   - ✅ Content is readable and properly formatted

## 🔧 Deployment Steps

1. **Restart Backend Service:**
   ```bash
   # On server, restart the backend to load new endpoints
   sudo systemctl restart trading-backend
   # Or if using Docker:
   docker-compose restart backend
   ```

2. **Test Nginx Configuration:**
   ```bash
   sudo nginx -t
   ```

3. **Reload Nginx:**
   ```bash
   sudo nginx -s reload
   ```

4. **Verify Endpoints:**
   ```bash
   # Check backend health
   curl http://localhost:8002/health
   
   # Test one endpoint
   curl -I http://localhost:8002/api/monitoring/reports/watchlist-consistency/latest
   ```

## 📝 Notes

- Date format must be exactly 8 digits: `YYYYMMDD` (e.g., `20251224`)
- Reports are stored in `docs/monitoring/` directory
- Latest reports are always named `*_report_latest.md`
- Dated reports follow pattern `*_report_YYYYMMDD.md`
- All endpoints return proper markdown content-type headers
- All endpoints include no-cache headers to prevent stale content

## 🐛 Troubleshooting

### Issue: 404 Not Found for dated reports

**Possible Causes:**
- Report file doesn't exist for that date
- Date format is incorrect (must be YYYYMMDD)
- File path resolution issue in backend

**Solution:**
- Verify report file exists: `ls -la docs/monitoring/watchlist_consistency_report_YYYYMMDD.md`
- Check backend logs for path resolution errors
- Verify date format matches exactly 8 digits

### Issue: Nginx rewrite not working

**Possible Causes:**
- Nginx configuration not reloaded
- Regex pattern not matching
- Proxy pass configuration issue

**Solution:**
- Test nginx config: `sudo nginx -t`
- Check nginx error logs: `sudo tail -f /var/log/nginx/error.log`
- Verify rewrite rules are in correct order (most specific first)

### Issue: Timeout errors

**Possible Causes:**
- Frontend timeout too short (should be 150s)
- Nginx timeout too short (should be 180s)
- Backend processing too slow

**Solution:**
- Verify frontend timeout in `frontend/src/lib/api.ts` (150s for workflows)
- Verify nginx timeout in `nginx/dashboard.conf` (180s for monitoring)
- Check backend logs for slow operations

## ✅ Completion Checklist

- [x] Backend endpoints implemented
- [x] Nginx rewrite rules configured
- [x] Frontend timeout increased
- [x] Date validation added
- [x] Error handling implemented
- [x] Documentation created
- [ ] Backend service restarted
- [ ] Nginx configuration reloaded
- [ ] Endpoints tested
- [ ] Browser access verified

---

**Last Updated:** 2025-01-24
**Status:** ✅ Implementation Complete - Ready for Testing














