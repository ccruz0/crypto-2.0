# Open Order Limit Reference

**Document Purpose**: This document defines the global rules used across the system to limit the execution of BUY and SELL (short) orders based on open positions. This is the source of truth for all developers and trading logic implementations.

---

## 1. Core Concept

### Open Position Definition

An **open position** is inferred from pending exit orders, not from entry orders.

- Exit orders define exposure, not the original entry orders.
- The system counts active exit orders to determine how many positions are currently open.
- Historical entry orders are irrelevant for position counting.

---

## 2. Take Profit Logic (Long Positions)

### Rules

- Every active Take Profit order represents **one open long position**.
- The system ignores how many historical BUY orders exist.
- The count of active Take Profit orders equals the count of open long positions.

### Example

If there are **3 active Take Profit orders**:
- The system assumes there are **3 open long positions**.
- **No new BUY orders are allowed** (limit reached).
- **SELL (short) orders are still allowed**, unless blocked by Stop Loss limits.

---

## 3. Stop Loss Logic (Short Positions)

### Rules

- Every active Stop Loss order represents **one open short position**.
- Stop Loss here refers to the protective exit of a short (SELL) position.
- The count of active Stop Loss orders equals the count of open short positions.

### Example

If there are **3 active Stop Loss orders**:
- The system assumes there are **3 open short positions**.
- **No new SELL (short) orders are allowed** (limit reached).
- **BUY orders are still allowed**, unless blocked by Take Profit limits.

---

## 4. Symmetry Rule

### Independent Checks

- **BUY logic** only checks Take Profit count.
- **SELL (short) logic** only checks Stop Loss count.
- **BUY logic does NOT care about Stop Loss count**.
- **SELL logic does NOT care about Take Profit count**.

### Implication

Long and short positions are tracked and limited independently. The system maintains separate counters for each side.

---

## 5. Hard Limit Rule

### Maximum Positions Per Side

- The maximum number of open positions per side (long or short) is **3**.
- Once the limit is reached:
  - The system must **block any new order** of that same side.
  - The system must **not partially allow, queue, or delay** the order.
  - The order is **rejected immediately**.

### Enforcement

- No exceptions or overrides.
- No partial fills or queuing mechanisms.
- Immediate rejection with appropriate error response.

---

## 6. Examples

### Scenario 1: 3 Take Profits, 0 Stop Losses

**State**:
- Active Take Profit orders: 3
- Active Stop Loss orders: 0

**Result**:
- **BUY**: Blocked (3 long positions, limit reached)
- **SELL**: Allowed (0 short positions, under limit)

---

### Scenario 2: 2 Take Profits, 3 Stop Losses

**State**:
- Active Take Profit orders: 2
- Active Stop Loss orders: 3

**Result**:
- **BUY**: Allowed (2 long positions, under limit)
- **SELL**: Blocked (3 short positions, limit reached)

---

### Scenario 3: 3 Take Profits, 3 Stop Losses

**State**:
- Active Take Profit orders: 3
- Active Stop Loss orders: 3

**Result**:
- **BUY**: Blocked (3 long positions, limit reached)
- **SELL**: Blocked (3 short positions, limit reached)

---

### Scenario 4: 1 Take Profit, 1 Stop Loss

**State**:
- Active Take Profit orders: 1
- Active Stop Loss orders: 1

**Result**:
- **BUY**: Allowed (1 long position, under limit)
- **SELL**: Allowed (1 short position, under limit)

---

## 7. Non-Goals and Exclusions

This document **does not** define:

- **Strategy logic**: Entry/exit signals, market analysis, or trading strategies.
- **Signal generation**: How trading signals are created or evaluated.
- **Order management**: Order sizing, price calculation, timing, or execution details.
- **Risk management**: Position sizing, leverage, or margin requirements beyond the count limit.

This document **only** defines:
- Exposure limits based on open exit orders.
- The counting mechanism for determining open positions.
- The blocking rules for new orders when limits are reached.

---

## 8. Implementation Note

### Requirements

- This logic **must be checked before any order is created**.
- This logic **must be shared and reused** by:
  - Backend API endpoints
  - Background workers
  - Simulation engines
  - Any other order creation pathways

### Maintenance

- Any future changes to these rules **must update this document first**.
- This document serves as the single source of truth for all implementations.
- All code must reference this document for validation of limit logic.

### Code Location

Implementations should centralize this logic in a shared utility function or service that can be imported and used consistently across all order creation points.







