# Trade System Debug Evidence - January 1, 2026

## 1) Container status

```
NAME                                              IMAGE                                           COMMAND                  SERVICE              CREATED          STATUS                    PORTS
automated-trading-platform-backend-aws-1          automated-trading-platform-backend-aws          "/app/entrypoint.sh …"   backend-aws          10 minutes ago   Up 10 minutes (healthy)   0.0.0.0:8002->8002/tcp
automated-trading-platform-frontend-aws-1         automated-trading-platform-frontend-aws         "docker-entrypoint.s…"   frontend-aws         2 hours ago      Up 2 hours (healthy)      0.0.0.0:3000->3000/tcp
automated-trading-platform-market-updater-aws-1   automated-trading-platform-market-updater-aws   "/app/entrypoint.sh …"   market-updater-aws   2 hours ago      Up 2 hours (healthy)      8002/tcp
postgres_hardened                                 automated-trading-platform-db                   "docker-entrypoint.s…"   db                   10 minutes ago   Up 10 minutes (healthy)   0.0.0.0:5432->5432/tcp
```

All containers running and healthy.

## 2) Backend logs (trade-related)

Exchange connectivity is working:
- Open orders API calls successful (status 200)
- 18 open orders synced successfully
- Some 401 errors on trigger orders endpoint (non-critical, authentication issue for that specific endpoint)

## 3) Market-updater logs (sanity)

Market updater running and healthy.

## 4) Environment (trade-related)

(Environment variables checked - all trade-related configs present)

## 5) Open orders + exchange reachability

**Test 1: Direct query with PENDING enum (FAILS)**
```
Traceback (most recent call last):
  File "<string>", line 1, in <module>
  File "/usr/local/lib/python3.11/enum.py", line 786, in __getattr__
    raise AttributeError(name) from None
AttributeError: PENDING
```

**Test 2: count_total_open_positions function (WORKS)**
```
COUNT_TOTAL_OPEN_POSITIONS=22
```

**Exchange API:**
- Open orders endpoint: ✅ Working (200 status)
- Order history endpoint: ✅ Working (200 status)
- Trigger orders endpoint: ⚠️ 401 error (non-critical)

## 6) Database connectivity

✅ Database connection working (verified via successful `count_total_open_positions` call)

## 7) Trade system check endpoint (if exists)

Health endpoint available at `/api/health`

## 8) Audit rerun output (trade section)

```
TRADE_SYSTEM: FAIL
```

The audit shows TRADE_SYSTEM: FAIL with evidence: "Error checking trade system: PENDING"

## 9) Findings (suspected root cause candidates)

### ROOT CAUSE IDENTIFIED

**Error Type:** (e) code exception in the trade-check path

**Exact Error Message:**
```
AttributeError: PENDING
```

**Root Cause:**
The audit script at line 328 in `backend/scripts/audit_no_alerts_no_trades.py` uses `OrderStatusEnum.PENDING` which does not exist in the OrderStatusEnum enum.

**Available OrderStatusEnum values:**
- NEW
- ACTIVE
- PARTIALLY_FILLED
- FILLED
- CANCELLED
- REJECTED
- EXPIRED

**PENDING does NOT exist.**

**Problematic Code:**
```python
# Line 328 in backend/scripts/audit_no_alerts_no_trades.py
open_orders = db.query(ExchangeOrder).filter(
    ExchangeOrder.symbol == symbol,
    ExchangeOrder.status.in_([OrderStatusEnum.PENDING, OrderStatusEnum.NEW, OrderStatusEnum.PARTIALLY_FILLED])
).count()
```

**Evidence:**
1. Direct test shows `AttributeError: PENDING` when accessing `OrderStatusEnum.PENDING`
2. Available enum values confirmed: `['NEW', 'ACTIVE', 'PARTIALLY_FILLED', 'FILLED', 'CANCELLED', 'REJECTED', 'EXPIRED']`
3. The function `count_total_open_positions` works correctly (returns 22)
4. Exchange connectivity is working (can sync orders, status 200)
5. Database connectivity is working

**Minimal Fix:**

Remove `OrderStatusEnum.PENDING` from line 328 in `backend/scripts/audit_no_alerts_no_trades.py`.

**Change from:**
```python
ExchangeOrder.status.in_([OrderStatusEnum.PENDING, OrderStatusEnum.NEW, OrderStatusEnum.PARTIALLY_FILLED])
```

**Change to:**
```python
ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
```

**Rationale:**
- `ACTIVE` is the correct status for open orders that are active on the exchange
- `PENDING` does not exist in the enum
- This matches the pattern used in `count_open_positions_for_symbol` which uses `NEW`, `ACTIVE`, `PARTIALLY_FILLED`





