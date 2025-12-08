# Quick Reference: Migration Commands

## 1. Run Migration Locally

```bash
cd /Users/carloscruz/automated-trading-platform && docker compose exec backend python scripts/migrate_add_order_skipped.py
```

## 2. Verify Locally

```bash
cd /Users/carloscruz/automated-trading-platform && docker compose exec db psql -U trader -d atp -c "SELECT id, symbol, blocked, order_skipped, LEFT(message, 60) as msg FROM telegram_messages ORDER BY timestamp DESC LIMIT 5;"
```

## 3. Run Migration on AWS

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws exec backend-aws python scripts/migrate_add_order_skipped.py'
```

## 4. Verify on AWS

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws exec db-aws psql -U trader -d atp -c "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '\''telegram_messages'\'' AND column_name = '\''order_skipped'\'';"'
```

## 5. Restart Backend on AWS

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws restart backend-aws'
```

## 6. Check Backend Status

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws ps backend-aws'
```

## 7. Run Position Limit Test on AWS

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws exec backend-aws python scripts/test_position_limit_alert_behavior.py'
```

## 8. Check Real Monitoring Rows on AWS

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws exec db-aws psql -U trader -d atp -c "SELECT id, symbol, blocked, order_skipped, LEFT(message, 80) as message FROM telegram_messages ORDER BY timestamp DESC LIMIT 5;"'
```
