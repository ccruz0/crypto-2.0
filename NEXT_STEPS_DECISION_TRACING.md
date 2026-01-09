# Next Steps: Decision Tracing System

## ✅ Current Status

**System Status:** ✅ All services running and healthy
- Database: ✅ Running with migration applied
- Market Updater: ✅ Running (monitoring 35 symbols)
- Backend API: ✅ Running
- Frontend: ✅ Running

**Decision Tracing:** ✅ Fully implemented and deployed

## 🎯 Immediate Next Steps

### 1. Monitor for Real-World Usage (Recommended)

**Wait for natural alerts** and observe decision tracing in action:

```bash
# Watch backend logs for decision traces
ssh ubuntu@47.130.143.159
cd ~/automated-trading-platform
docker compose --profile aws logs -f market-updater-aws | grep -i "DECISION\|TRADE_BLOCKED\|ORDER_FAILED"
```

**What to look for:**
- `[DECISION] symbol=... decision=SKIPPED reason=...` logs
- `[DECISION] symbol=... decision=FAILED reason=...` logs
- Check Monitor UI → Telegram (Mensajes Bloqueados) for new entries

**Expected timeline:** Within 1-24 hours depending on market conditions and your watchlist activity.

### 2. Test with Controlled Scenario (Quick Verification)

**Test SKIP scenario:**

1. **Choose a test symbol** (e.g., one that's currently active)
2. **Disable trading:**
   - Go to Dashboard → Watchlist
   - Find the symbol
   - Set `trade_enabled = False`
   - Save
3. **Wait for next alert** (or trigger manually if possible)
4. **Verify in Monitor:**
   - Go to Monitor → Telegram (Mensajes Bloqueados)
   - Look for entry with:
     - Decision Type: `SKIPPED` (yellow badge)
     - Reason Code: `TRADE_DISABLED`
     - Reason Message: "Trade is disabled for SYMBOL. trade_enabled=False."
     - Context JSON showing `trade_enabled: false`

**Test FAIL scenario:**

1. **Temporarily reduce balance** (if safe to do)
2. **Or use a symbol with very high trade_amount_usd** that exceeds balance
3. **Wait for alert**
4. **Verify:**
   - Monitor shows `FAILED` entry
   - Reason Code: `INSUFFICIENT_FUNDS` or `INSUFFICIENT_AVAILABLE_BALANCE`
   - Exchange error snippet included
   - Telegram failure notification received

### 3. Verify Database Entries

**Check recent blocked messages with decision tracing:**

```bash
ssh ubuntu@47.130.143.159
cd ~/automated-trading-platform
docker compose --profile aws exec -T -e PGPASSWORD=traderpass db psql -U trader -d atp << 'EOF'
SELECT 
    id,
    symbol,
    blocked,
    decision_type,
    reason_code,
    LEFT(reason_message, 80) as reason_preview,
    timestamp
FROM telegram_messages 
WHERE blocked = true 
AND timestamp >= NOW() - INTERVAL '24 hours'
AND decision_type IS NOT NULL
ORDER BY timestamp DESC 
LIMIT 20;
EOF
```

**Expected:** New entries should have `decision_type`, `reason_code`, and `reason_message` populated.

### 4. Check API Endpoint

**Verify API returns decision tracing fields:**

```bash
curl -s http://dashboard.hilovivo.com/api/monitoring/telegram-messages | jq '.messages[0] | {decision_type, reason_code, reason_message, context_json}'
```

**Expected:** Should see decision tracing fields in the response (may be `null` for old messages).

### 5. Monitor System Health

**Daily check script:**

```bash
# Run this daily to monitor decision tracing usage
ssh ubuntu@47.130.143.159 << 'EOF'
cd ~/automated-trading-platform
docker compose --profile aws exec -T -e PGPASSWORD=traderpass db psql -U trader -d atp << 'SQL'
SELECT 
    COUNT(*) as total_blocked_today,
    COUNT(CASE WHEN decision_type IS NOT NULL THEN 1 END) as with_decision_type,
    COUNT(CASE WHEN reason_code IS NOT NULL THEN 1 END) as with_reason_code,
    decision_type,
    reason_code
FROM telegram_messages 
WHERE blocked = true 
AND timestamp >= CURRENT_DATE
GROUP BY decision_type, reason_code
ORDER BY total_blocked_today DESC;
SQL
EOF
```

## 📊 Success Metrics

**After 24-48 hours, you should see:**

1. ✅ New blocked messages have `decision_type` populated
2. ✅ Reason codes match actual skip/fail scenarios
3. ✅ Monitor UI displays decision details correctly
4. ✅ Telegram failure notifications include error details
5. ✅ No errors in backend logs related to decision tracing

## 🔍 Troubleshooting

**If no decision tracing appears:**

1. **Check migration status:**
   ```bash
   docker compose --profile aws exec -T -e PGPASSWORD=traderpass db psql -U trader -d atp -c "SELECT column_name FROM information_schema.columns WHERE table_name = 'telegram_messages' AND column_name IN ('decision_type', 'reason_code');"
   ```
   Should return 2 rows.

2. **Check backend logs for errors:**
   ```bash
   docker compose --profile aws logs market-updater-aws | grep -i "error\|exception\|traceback" | tail -20
   ```

3. **Verify code is deployed:**
   ```bash
   docker compose --profile aws exec market-updater-aws python3 -c "from app.utils.decision_reason import DecisionReason; print('OK')"
   ```

4. **Check if alerts are being processed:**
   ```bash
   docker compose --profile aws logs market-updater-aws | grep -i "BUY alert\|signal" | tail -10
   ```

## 🎓 Understanding Decision Types

**SKIPPED** (Yellow badge):
- Order was never attempted
- Guard clause prevented order creation
- Examples: `TRADE_DISABLED`, `MAX_OPEN_TRADES_REACHED`, `INSUFFICIENT_AVAILABLE_BALANCE`

**FAILED** (Red badge):
- Order was attempted but exchange rejected it
- Examples: `EXCHANGE_REJECTED`, `INSUFFICIENT_FUNDS`, `AUTHENTICATION_ERROR`

## 📈 Long-Term Monitoring

**Weekly review:**
1. Check most common skip reasons
2. Identify patterns (e.g., frequent `INSUFFICIENT_BALANCE`)
3. Optimize trading parameters based on insights
4. Review failed orders for exchange issues

**Query for insights:**
```sql
SELECT 
    reason_code,
    COUNT(*) as count,
    COUNT(DISTINCT symbol) as affected_symbols
FROM telegram_messages
WHERE decision_type IS NOT NULL
AND timestamp >= NOW() - INTERVAL '7 days'
GROUP BY reason_code
ORDER BY count DESC;
```

## 🚀 Optional Enhancements (Future)

If you want to extend the system:

1. **Add analytics dashboard** - Visualize skip/fail patterns
2. **Alert on patterns** - Notify when specific reasons spike
3. **Auto-recovery** - Automatically retry certain failures
4. **Historical analysis** - Track decision trends over time

## ✅ Checklist

- [ ] System is running and healthy
- [ ] Migration verified (6 columns exist)
- [ ] Wait for natural alert OR test with controlled scenario
- [ ] Verify decision tracing appears in Monitor UI
- [ ] Check database entries have decision fields
- [ ] Verify API returns decision fields
- [ ] Monitor for 24-48 hours
- [ ] Review decision patterns

---

**Status:** Ready for monitoring and testing  
**Next Action:** Wait for alerts or run controlled test scenario

