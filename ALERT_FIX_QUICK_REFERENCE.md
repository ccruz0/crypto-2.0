# Alert Fix - Quick Reference Guide

## 🚀 Quick Start

### 1. Execute Migration (One-time)
```bash
./RUN_ALERT_FIX_ON_AWS.sh
```

### 2. Verify Fix
```bash
./VERIFY_ALERT_FIX.sh
```

---

## 📋 Manual Commands

### Database Migration
```bash
docker exec -it postgres_hardened psql -U trader -d atp -f /app/backend/migrations/enable_alerts_for_all_coins.sql
```

### Verify Database State
```bash
docker exec -it postgres_hardened psql -U trader -d atp -c "
SELECT 
    COUNT(*) as total,
    COUNT(*) FILTER (WHERE alert_enabled = true) as enabled,
    COUNT(*) FILTER (WHERE alert_enabled = false) as disabled
FROM watchlist_items
WHERE is_deleted = false;"
```

### Check API Alert Stats
```bash
curl -s http://localhost:8000/api/dashboard/alert-stats | jq '{
  total_items,
  alert_enabled,
  alert_disabled,
  alert_disabled_coins
}'
```

### Check Startup Logs
```bash
docker logs backend | grep "STARTUP_ALERT_CONFIG" | head -30
```

### Check Alert Decisions
```bash
# Allowed alerts
docker logs backend | grep "ALERT_ALLOWED" | tail -20

# Blocked alerts
docker logs backend | grep "ALERT_CHECK.*BLOCK" | tail -20
```

---

## 🔍 Expected Results

### Database
```
total  | enabled | disabled
-------|---------|----------
50     | 50      | 0        ✅
```

### API Response
```json
{
  "total_items": 50,
  "alert_enabled": 50,
  "alert_disabled": 0,
  "alert_disabled_coins": []
}
```

### Startup Logs
```
[STARTUP_ALERT_CONFIG] total_active_coins=50 alert_enabled_true=50 alert_enabled_false=0
[STARTUP_ALERT_CONFIG] symbol=BTC_USDT alert_enabled=True buy_alert_enabled=True sell_alert_enabled=True source=db
```

---

## 📊 Log Formats

### Startup Configuration
```
[STARTUP_ALERT_CONFIG] total_active_coins=50 alert_enabled_true=50 alert_enabled_false=0
[STARTUP_ALERT_CONFIG] symbol=XXX alert_enabled=True buy_alert_enabled=True sell_alert_enabled=True source=db
```

### Alert Allowed
```
[ALERT_ALLOWED] symbol=XXX gate=alert_enabled+buy_alert_enabled decision=ALLOW alert_enabled=True buy_alert_enabled=True sell_alert_enabled=True source=db evaluation_id=xxx
```

### Alert Blocked
```
[ALERT_CHECK] symbol=XXX gate=alert_enabled decision=BLOCK reason=ALERT_DISABLED alert_enabled=False ... source=db evaluation_id=xxx
🚫 BLOQUEADO: XXX - Las alertas están deshabilitadas (alert_enabled=False)
```

---

## 🔧 Troubleshooting

### Issue: Migration not executed
**Solution**: Run `./RUN_ALERT_FIX_ON_AWS.sh`

### Issue: Backend logs show alert_enabled_false > 0
**Solution**: 
1. Verify migration was executed
2. Restart backend container
3. Check logs again

### Issue: API shows alert_disabled > 0
**Solution**:
1. Check database state directly
2. Verify migration was executed
3. Restart backend to refresh cache

### Issue: No startup logs
**Solution**: Backend needs to be restarted after code deployment

---

## 📁 Files Reference

- **Migration**: `backend/migrations/enable_alerts_for_all_coins.sql`
- **Execution Script**: `RUN_ALERT_FIX_ON_AWS.sh`
- **Verification Script**: `VERIFY_ALERT_FIX.sh`
- **Full Documentation**: `ALERT_FIX_FINAL_SUMMARY.md`

---

## ✅ Checklist

- [ ] Migration executed
- [ ] Database shows disabled=0
- [ ] Backend restarted
- [ ] Startup logs show correct config
- [ ] API shows alert_disabled=0
- [ ] Alerts are being sent (ALERT_ALLOWED logs)
- [ ] No blocking messages for enabled coins

---

**Last Updated**: After deployment
**Status**: Ready for production
