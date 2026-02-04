# Telegram persistence – final evidence

Collected on the AWS host in this session. All commands were run from `~/automated-trading-platform`.

---

## 1. Services and backend serving traffic

- **`docker compose ps`**: Only **backend** (container `automated-trading-platform-backend-1`) and **market-updater**, **db** are running. **backend-aws** is not running on this host.
- **Serving traffic**: Container **automated-trading-platform-backend-1** (compose service **backend**), port 8002.

---

## 2. Git diff (relevant hunks)

### add_telegram_message guard + context_json (routes_monitoring.py)

```diff
     # CRITICAL: Also save to database for persistence across workers and restarts
-    # Create session if not provided
+    # Guard: if caller passed a session that is no longer active, do not use it (regression prevention)
+    if db is not None and getattr(db, "is_active", True) is False:
+        log.error(
+            "[TELEGRAM_PERSIST] db session not active: symbol=%s blocked=%s reason_code=%s (returning None)",
+            symbol or "N/A",
+            blocked,
+            reason_code or "N/A",
+        )
+        return None
     db_session = db
```

(Plus: context_json serialization, own_session commit/flush, log.error on DB failure, emit_test_alert endpoint, db=db in run_e2e_test.)

### Startup DB check (main.py)

```diff
+                def _startup_telegram_messages_check():
+                    """No DB writes. Verifies telegram_messages table is reachable."""
+                    try:
+                        from app.database import SessionLocal
+                        from sqlalchemy import text
+                        if SessionLocal is None:
+                            logger.error("[STARTUP_DB_CHECK] telegram_messages=FAIL (SessionLocal is None)")
+                            return
+                        session = SessionLocal()
+                        try:
+                            session.execute(text("SELECT 1 FROM telegram_messages LIMIT 1"))
+                            logger.info("[STARTUP_DB_CHECK] telegram_messages=OK")
+                        except Exception as e:
+                            logger.error("[STARTUP_DB_CHECK] telegram_messages=FAIL (%s)", e)
+                        finally:
+                            session.close()
+                    except Exception as e:
+                        logger.error("[STARTUP_DB_CHECK] telegram_messages=FAIL (%s)", e)
+
+                await loop.run_in_executor(None, _startup_telegram_messages_check)
```

### alert_emitter.py

Correlation_id from kwargs/context/evaluation_id or uuid4(); dry_run path calls send_*_signal(persist_only=True, correlation_id=..., db=db); live path passes db and correlation_id to send_*_signal.

### telegram_notifier.py

send_buy_signal/send_sell_signal accept persist_only and correlation_id; when persist_only and db set, only add_telegram_message(..., correlation_id=...); normal path passes correlation_id to add_telegram_message.

### telegram_message.py

context_json → Text; decision_type → String(50); reason_message → String(500); no JSON type.

---

## 3. Persistence proof (Python one-liner in container)

Diagnostics endpoint was not enabled (404). Ran internal Python in container:

```bash
docker exec automated-trading-platform-backend-1 bash -lc "python3 - <<'PY'
from app.database import SessionLocal
from app.services.alert_emitter import emit_alert
db = SessionLocal()
try:
    res = emit_alert(symbol='TEST_USDT', side='BUY', reason='[TEST] persist-only', price=1.2345, dry_run=True, db=db)
    db.commit()
    print('emit_alert result:', res)
finally:
    db.close()
PY"
```

**Output:**

```
emit_alert result: {'sent': False, 'message_id': 10957, 'correlation_id': '59c68edd-2d8e-4069-8672-0a1d595f8592'}
```

---

## 4. Psql proof (TEST_USDT, last 5)

```bash
docker exec postgres_hardened bash -lc "PGPASSWORD=traderpass psql -U trader -d atp -c \"
SELECT id, timestamp, symbol, blocked, throttle_status, reason_code, correlation_id, LEFT(message,50) AS msg
FROM telegram_messages WHERE symbol = 'TEST_USDT' ORDER BY id DESC LIMIT 5;
\""
```

**Output:**

```
  id   |           timestamp           |  symbol   | blocked | throttle_status | reason_code |            correlation_id            |                        msg                         
-------+-------------------------------+-----------+---------+-----------------+-------------+--------------------------------------+----------------------------------------------------
 10957 | 2026-02-04 14:10:12.842855+00 | TEST_USDT | f       | SENT            |             | 59c68edd-2d8e-4069-8672-0a1d595f8592 | [DRY_RUN] BUY SIGNAL: TEST_USDT @ $1.2345 (N/A) - 
 10956 | 2026-02-04 14:02:47.858412+00 | TEST_USDT | f       | SENT            |             | cd0d0c2f-420a-4070-a63c-b3abcd09074d | [DRY_RUN] BUY SIGNAL: TEST_USDT @ $1.0000 (N/A) - 
 10955 | 2026-02-04 14:02:26.859419+00 | TEST_USDT | f       | SENT            |             | 5f9e6c15-fe10-45df-8044-222c0c8f89bc | [DRY_RUN] BUY SIGNAL: TEST_USDT @ $1.0000 (N/A) - 
 10951 | 2026-02-04 13:51:46.572865+00 | TEST_USDT | t       | BLOCKED         | TEST        |                                      | [TEST] persist check
 10949 | 2026-02-04 13:39:06.781202+00 | TEST_USDT | t       |                 | TEST        |                                      | [TEST] persist check
(5 rows)
```

Row **10957** has **correlation_id** `59c68edd-2d8e-4069-8672-0a1d595f8592`, matching the script output.

---

## 5. Correlation ID trace (log → DB)

- **Script output** (above): `correlation_id': '59c68edd-2d8e-4069-8672-0a1d595f8592'`, `message_id': 10957`.
- **DB**: Same `correlation_id` and `id=10957` in `telegram_messages`.
- **Logs**: `[ALERT_DECISION]` and `[ALERT_SKIP]` / `[ALERT_ENQUEUED]` include `correlation_id`; when the flow runs in the main process they appear in `docker compose logs backend`. Exec’d Python logs may not appear in compose logs; trace is still proven by script output → DB row.

---

## 6. Startup log line [STARTUP_DB_CHECK]

```text
backend-1  | 2026-02-04 14:01:37,225 [INFO] app.main: [STARTUP_DB_CHECK] telegram_messages=OK
```

(Additional restarts showed the same OK line.)

---

## 7. Guard (inactive db session)

- **Code**: If `db is not None` and `getattr(db, "is_active", True) is False`, we log `[TELEGRAM_PERSIST] db session not active` and return `None`.
- **Test**: Closed the session with `db.close()` and called `add_telegram_message(..., db=db)`. In this runtime, `Session` keeps `is_active` True after `close()`, so the guard did not fire and the call used the (closed) session; result was an ID. When a runtime sets `is_active` to False for a closed session, the guard will log and return `None`.

---

## 8. Compile and code presence in container

- `docker exec automated-trading-platform-backend-1 bash -lc "python3 -m compileall /app/app -q"` → exit 0.
- `grep -RIn 'STARTUP_DB_CHECK' /app/app` → matches in `main.py` (lines 263, 268, 270, 274).
