# Telegram messages – monitoring query

**Question:** Show blocked vs sent alerts per symbol in the last 24h.

**SQL (source of truth, run against `atp`):**

```sql
SELECT
  symbol,
  COUNT(*) FILTER (WHERE blocked = true)  AS blocked_count,
  COUNT(*) FILTER (WHERE blocked = false) AS sent_count,
  COUNT(*)                                AS total
FROM telegram_messages
WHERE timestamp >= NOW() - INTERVAL '24 hours'
GROUP BY symbol
ORDER BY total DESC;
```

Run with:

```bash
docker exec postgres_hardened bash -lc 'PGPASSWORD="traderpass" psql -U trader -d atp -c "<paste query>"'
```
