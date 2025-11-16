# Issue: Open Orders Inconsistency

## Problem
The `/api/orders/open` endpoint shows 2 open orders, but `/api/dashboard/state` shows only 1 open order. The user reports that "open orders no son correctas" (open orders are not correct).

## Findings

### Orders Found
1. **`dry_123456`** (Recent order - Nov 6, 2025)
   - Symbol: BTC_USDT
   - Status: ACTIVE
   - Quantity: 0.001
   - Price: 50000.0
   - ✅ **Present in both endpoints**

2. **`OPEN0004`** (Old order - Oct 26, 2025)
   - Symbol: BTC_USDT
   - Status: ACTIVE
   - Quantity: 0.044779
   - Price: 48790.82
   - ⚠️ **Only present in `/api/orders/open`**
   - ⚠️ **NOT present in `/api/dashboard/state`**

## Root Cause

The two endpoints query data differently:

### `/api/orders/open` (routes_orders.py)
```python
# Queries PostgreSQL
orders = db.query(ExchangeOrder).filter(ExchangeOrder.status.in_(open_statuses))...

# ALSO queries SQLite for backward compatibility
sqlite_orders = order_history_db.get_orders_by_status(['ACTIVE', 'NEW', 'PARTIALLY_FILLED'], limit=100)
# Merges both sources
```

### `/api/dashboard/state` (routes_dashboard.py)
```python
# Only queries PostgreSQL
db_orders = db.query(ExchangeOrder).filter(
    ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
).order_by(ExchangeOrder.exchange_create_time.desc()).limit(50).all()
# Does NOT query SQLite
```

## Issue
The order `OPEN0004` from Oct 26 is:
1. **Either** stored only in SQLite (not in PostgreSQL)
2. **Or** very old and should have been cancelled/filled but wasn't updated

## Recommendations

### Short-term Fix
1. **Clean up old orders** in SQLite that are over 30 days old and still marked as ACTIVE
2. **Sync SQLite orders to PostgreSQL** if they're legitimate open orders
3. **Or remove SQLite querying** from `/api/orders/open` to only use PostgreSQL (preferred)

### Long-term Solution
1. **Deprecate SQLite `order_history_db`** completely
2. **Only use PostgreSQL** for all order storage
3. **Add a cleanup job** that marks orders as CANCELLED if they're over X days old and still ACTIVE

## Current State
- `/api/dashboard/state`: Shows 1 open order (only PostgreSQL data)
- `/api/orders/open`: Shows 2 open orders (PostgreSQL + SQLite data)
- The `OPEN0004` order from Oct 26 is likely stale and should be cancelled

## Proposed Fix
Remove the SQLite query from `/api/orders/open` or add a time filter to exclude orders older than 30 days.

