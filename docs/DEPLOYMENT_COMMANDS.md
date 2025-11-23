# Deployment Commands for Alert Refactor

## 1. Run Database Migration (REQUIRED FIRST)

```bash
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && docker compose exec db psql -U trader -d atp -c \"
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='watchlist_items' AND column_name='buy_alert_enabled') THEN
        ALTER TABLE watchlist_items ADD COLUMN buy_alert_enabled BOOLEAN NOT NULL DEFAULT FALSE;
        RAISE NOTICE 'Added column buy_alert_enabled';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='watchlist_items' AND column_name='sell_alert_enabled') THEN
        ALTER TABLE watchlist_items ADD COLUMN sell_alert_enabled BOOLEAN NOT NULL DEFAULT FALSE;
        RAISE NOTICE 'Added column sell_alert_enabled';
    END IF;
    UPDATE watchlist_items SET buy_alert_enabled = alert_enabled, sell_alert_enabled = alert_enabled WHERE alert_enabled = TRUE;
    RAISE NOTICE 'Migration completed';
END
\$\$;
\""
```

## 2. Sync Code to AWS

```bash
cd /Users/carloscruz/automated-trading-platform
git add .
git commit -m "feat: Split alert button into Buy Alert and Sell Alert with full order creation support"
git push

ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && git pull"
```

## 3. Rebuild and Restart Services

```bash
# Backend
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && docker compose build backend && docker compose restart backend"

# Frontend
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && docker compose build frontend && docker compose restart frontend"
```

## 4. Verify Services

```bash
# Check backend logs
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && docker compose logs --tail=50 backend"

# Check frontend logs
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && docker compose logs --tail=50 frontend"

# Check if services are running
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && docker compose ps"
```

## 5. Test End-to-End

1. Open dashboard: `https://hilovivo.com`
2. Navigate to Watchlist tab
3. Verify Buy Alert and Sell Alert buttons appear (replacing single Alert button)
4. Test Buy Alert button:
   - Click to enable/disable
   - Verify state persists after page refresh
5. Test Sell Alert button:
   - Click to enable/disable
   - Verify state persists after page refresh
6. Test Test button:
   - Enable Buy Alert only → Click Test → Should send buy alert + create buy order (if Trade=YES)
   - Enable Sell Alert only → Click Test → Should send sell alert + create sell order (if Trade=YES)
   - Enable both → Click Test → Should send both alerts + create both orders (if Trade=YES)
7. Verify Telegram messages:
   - Check that messages show "🧪 TEST MODE" for test alerts
   - Check that messages show "🔴 LIVE ALERT" for live alerts
   - Verify BUY vs SELL distinction is clear

## Troubleshooting

### Dashboard Not Loading
- Check backend logs for errors
- Verify database migration completed successfully
- Check that columns exist: `SELECT column_name FROM information_schema.columns WHERE table_name='watchlist_items' AND column_name IN ('buy_alert_enabled', 'sell_alert_enabled');`

### Buttons Not Appearing
- Clear browser cache
- Check browser console for errors
- Verify frontend build completed successfully

### Alerts Not Sending
- Check `alert_enabled` master switch is True
- Verify `buy_alert_enabled` or `sell_alert_enabled` is True
- Check Telegram credentials are configured
- Check backend logs for blocking reasons

