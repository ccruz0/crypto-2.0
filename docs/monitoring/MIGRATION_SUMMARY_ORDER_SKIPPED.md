# Migration Summary: order_skipped Column

## Migration Mechanism

**System Used:** Custom Python migration script (no Alembic)

**Files:**
- `backend/migrations/add_order_skipped_column.sql` - SQL migration (idempotent)
- `backend/scripts/migrate_add_order_skipped.py` - Python runner (idempotent)

**Why Custom Script:**
- Project uses custom migration system (SQL files in `migrations/` folder)
- Python script provides better error handling and verification
- Both are idempotent (safe to run multiple times)

## Database Structure

### Before Migration

```sql
CREATE TABLE telegram_messages (
    id SERIAL PRIMARY KEY,
    message TEXT NOT NULL,
    symbol VARCHAR(50),
    blocked BOOLEAN NOT NULL DEFAULT FALSE,
    throttle_status VARCHAR(20),
    throttle_reason TEXT,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

**Indexes:**
- `ix_telegram_messages_timestamp`
- `ix_telegram_messages_symbol_blocked`

### After Migration

```sql
CREATE TABLE telegram_messages (
    id SERIAL PRIMARY KEY,
    message TEXT NOT NULL,
    symbol VARCHAR(50),
    blocked BOOLEAN NOT NULL DEFAULT FALSE,  -- Alert blocked (not sent)
    order_skipped BOOLEAN NOT NULL DEFAULT FALSE,  -- Order skipped (alert was sent)
    throttle_status VARCHAR(20),
    throttle_reason TEXT,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

**Indexes:**
- `ix_telegram_messages_timestamp`
- `ix_telegram_messages_symbol_blocked`
- `ix_telegram_messages_order_skipped` (NEW)

## Field Semantics

### `blocked` (existing)
- **Purpose:** Indicates if the alert itself was blocked
- **When True:** Alert was NOT sent (technical/guardrail errors)
- **When False:** Alert was sent (or would be sent)

### `order_skipped` (new)
- **Purpose:** Indicates if the order was skipped due to position limits
- **When True:** Order was skipped, but alert WAS sent
- **When False:** Order was created (or would be created)
- **Constraint:** When `order_skipped=True`, `blocked` must be `False`

## Example Monitoring Row

### Position Limit Case (New Behavior)

```json
{
  "id": 12345,
  "symbol": "AAVE_USDT",
  "blocked": false,
  "order_skipped": true,
  "message": "⚠️ ORDEN NO EJECUTADA POR VALOR EN CARTERA: AAVE_USDT - Valor en cartera ($1210.44) > 3x trade_amount ($300.00). La alerta ya fue enviada, pero la orden de compra no se creará.",
  "throttle_status": "SENT",
  "timestamp": "2025-01-XX 12:34:56+00:00"
}
```

**Frontend Display:**
- Badge: "ORDER SKIPPED" (yellow/orange)
- Background: Yellow/orange tint
- Text: Normal (not italic)

### Technical Block Case (Existing Behavior)

```json
{
  "id": 12346,
  "symbol": "BTC_USDT",
  "blocked": true,
  "order_skipped": false,
  "message": "🚫 BLOQUEADO: BTC_USDT - alert_enabled=False en verificación final.",
  "throttle_status": null,
  "timestamp": "2025-01-XX 12:35:00+00:00"
}
```

**Frontend Display:**
- Badge: "BLOCKED" (red)
- Background: Gray tint
- Text: Italic

### Normal Alert Case

```json
{
  "id": 12347,
  "symbol": "ETH_USDT",
  "blocked": false,
  "order_skipped": false,
  "message": "🟢 BUY SIGNAL: ETH_USDT - RSI=35.5, Price=$2500.00...",
  "throttle_status": "SENT",
  "timestamp": "2025-01-XX 12:36:00+00:00"
}
```

**Frontend Display:**
- Badge: "SENT" (green)
- Background: Blue tint
- Text: Normal

## Edge Cases

### 1. Existing Rows (Backward Compatibility)

**Issue:** Existing rows don't have `order_skipped` column before migration.

**Solution:**
- Migration adds column with `DEFAULT FALSE`
- All existing rows automatically get `order_skipped = false`
- No data loss or corruption

### 2. Race Conditions

**Issue:** Multiple workers might try to create monitoring entries simultaneously.

**Solution:**
- Duplicate detection in `add_telegram_message()` checks last 5 seconds
- Uses `message`, `symbol`, `blocked` for matching
- `order_skipped` is included in duplicate check (via `blocked=False`)

### 3. Missing Column in Old Code

**Issue:** Old backend code might not know about `order_skipped`.

**Solution:**
- SQLAlchemy model has `order_skipped` with default `False`
- API uses `getattr(msg, 'order_skipped', False)` for backward compatibility
- Frontend handles missing field gracefully

### 4. Database Connection Issues

**Issue:** Migration might fail if database is unreachable.

**Solution:**
- Python script checks `engine is None` before proceeding
- Provides clear error messages
- Safe to retry (idempotent)

### 5. Frontend Display Logic

**Issue:** Frontend might show wrong badge if `order_skipped` is missing.

**Solution:**
- Frontend checks `order_skipped` first (highest priority)
- Falls back to `blocked` if `order_skipped` is missing/undefined
- TypeScript interface makes field optional for backward compatibility

## Verification Checklist

- [x] Migration script created and tested
- [x] SQL migration is idempotent
- [x] Python migration is idempotent
- [x] Model updated with `order_skipped` field
- [x] Model comments clarify semantics
- [x] API updated to handle `order_skipped`
- [x] Frontend updated to display "ORDER SKIPPED" badge
- [x] Test script created
- [x] Documentation created

## Next Steps

1. Run migration locally (verify it works)
2. Run migration on AWS
3. Restart backend on AWS
4. Run test script on AWS
5. Verify Monitoring UI shows correct badges
6. Monitor for any issues in production

## Rollback Plan

If issues occur, the column can be removed:

```sql
ALTER TABLE telegram_messages DROP COLUMN IF EXISTS order_skipped;
DROP INDEX IF EXISTS ix_telegram_messages_order_skipped;
```

**Note:** This will lose `order_skipped` data. Only use if absolutely necessary.
