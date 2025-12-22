# Telegram Menu – Reference Specification

**Version:** 1.0  
**Last Updated:** 2025-01-27  
**Status:** Authoritative Single Source of Truth

---

## Document Purpose

This document defines the exact structure, content, and behavior of the Telegram bot menu. It serves as the **single source of truth** for all Telegram menu implementations.

**Governance Rule:** Any modification to the Telegram menu must be reflected in this document **before** implementation. The Telegram menu must never diverge structurally from the Dashboard without updating this document.

---

## 1. General Principles

### 1.1 Core Principles

- **Mirror Principle:** The Telegram menu mirrors the Dashboard structure, sections, and data exactly.
- **No New Concepts:** No new concepts are introduced in Telegram that do not exist in the Dashboard.
- **Read-and-Control Interface:** Telegram acts as a read-and-control interface, not as an alternative logic layer.
- **Data Source Consistency:** All values shown must match the same data sources used by the Dashboard.

### 1.2 Data Source Requirements

- All portfolio data must use the same API endpoints as the Dashboard (`/api/portfolio`, `/api/dashboard/state`)
- All watchlist data must use the same database queries as the Dashboard
- All order data must use the same exchange API calls as the Dashboard
- All calculations (PnL, percentages, etc.) must use identical formulas as the Dashboard

---

## 2. Top-Level Menu Structure

The Telegram menu contains the following top-level sections, in this **exact order**:

1. **Portfolio**
2. **Watchlist**
3. **Open Orders**
4. **Expected Take Profit**
5. **Executed Orders**
6. **Monitoring**
7. **Version History**

Each section corresponds directly to an existing Dashboard tab with identical functionality and data.

---

## 3. Portfolio Section

### 3.1 Portfolio Overview (Shown First)

The Portfolio section **always starts** with a global summary card displaying:

#### Summary Metrics

- **Total Portfolio Value** (USD)
  - Source: `portfolio.total_value_usd` from `/api/portfolio`
  - Format: Currency with thousand separators (e.g., `$45,442.92`)

#### Profit and Loss Breakdown

- **Realized PnL**
  - Source: Calculated from executed orders
  - Format: Currency with sign (e.g., `+$1,234.56` or `-$567.89`)
  
- **Potential PnL**
  - Source: Calculated from open positions (unrealized gains/losses)
  - Format: Currency with sign
  
- **Total PnL**
  - Source: Sum of Realized PnL + Potential PnL
  - Format: Currency with sign

**Data Source:** These values must be identical to those shown in the Dashboard Portfolio tab summary cards.

### 3.2 Portfolio Positions List

Below the summary, display a list of all portfolio positions.

#### Sorting

- **Default Sort:** By position value (USD), **descending** (highest value first)
- **User Sort:** Allow sorting by any column (same as Dashboard)

#### Display Format

For each coin, display the following fields in a table format:

| Field | Source | Format | Notes |
|-------|--------|--------|-------|
| **Coin Symbol** | `asset.coin` | Text (e.g., `BTC`, `ETH`) | Primary identifier |
| **Position Value** | `asset.usd_value` | Currency (e.g., `$20,157.97`) | Total USD value of holdings |
| **Units Held** | `asset.balance` | Number with decimals (e.g., `5.12 ETH`) | Total balance including reserved |
| **Available Units** | `asset.available` | Number with decimals | Available (not locked) balance |
| **Reserved Units** | `asset.balance - asset.available` | Number with decimals | Locked/reserved balance |
| **Number of Open Orders** | Count from `open_orders` filtered by symbol | Integer | Count of active orders |
| **Take Profit Value** | Calculated from TP orders | Currency | Sum of all TP order values |
| **Stop Loss Value** | Calculated from SL orders | Currency | Sum of all SL order values |
| **% Portfolio** | `(asset.usd_value / total_value_usd) * 100` | Percentage (e.g., `44.4%`) | Portfolio allocation percentage |

#### Data Source

- **Primary:** `/api/portfolio` endpoint
- **Open Orders Count:** `/api/orders/open` filtered by symbol
- **TP/SL Values:** Calculated from open orders with type `TAKE_PROFIT` or `STOP_LOSS`

#### Read-Only Status

This section is **read-only**. No editing or control actions are available in the Portfolio section.

---

## 4. Watchlist Section

### 4.1 Watchlist Coin List

Display all coins currently tracked in the Watchlist.

#### Data Source

- **Primary:** `/api/dashboard/watchlist` or database query to `watchlist_items` table
- **Filter:** Only show items where `deleted_at IS NULL` or `is_deleted = false`

#### Display Format

For each coin, display the following fields:

| Field | Source | Format | Notes |
|-------|--------|--------|-------|
| **Coin Symbol** | `item.symbol` | Text (e.g., `BTC_USDT`) | Primary identifier |
| **Last Price** | `item.last_price` or from signals | Currency (e.g., `$45,234.56`) | Most recent price |
| **Last Updated** | `item.last_updated` or `item.updated_at` | Timestamp | ISO format or relative time |
| **Strategy (Straight)** | `item.strategy` or calculated | Yes / No | Whether straight strategy is enabled |
| **Trade Enabled** | `item.trade_enabled` | Yes / No | Whether automatic trading is enabled |
| **Amount (USD)** | `item.trade_amount_usd` | Currency (e.g., `$1,000.00`) | Trading amount per signal |
| **Stop Loss Value** | `item.sl_price` or calculated | Currency | Stop loss price level |
| **Take Profit Value** | `item.tp_price` or calculated | Currency | Take profit price level |
| **Stop Loss %** | `item.sl_percentage` | Percentage (e.g., `5.0%`) | SL percentage from entry |
| **Take Profit %** | `item.tp_percentage` | Percentage (e.g., `10.0%`) | TP percentage from entry |
| **Margin Trading** | `item.trade_on_margin` | Yes / No | Whether margin trading is enabled |
| **Risk Mode** | `item.sl_tp_mode` | Text (e.g., `conservative`, `moderate`, `aggressive`) | Risk profile |
| **Alerts Enabled** | `item.alert_enabled` | Yes / No | Master alert toggle |
| **Buy Alert Enabled** | `item.buy_alert_enabled` | Yes / No | Buy signal alerts |
| **Sell Alert Enabled** | `item.sell_alert_enabled` | Yes / No | Sell signal alerts |
| **Min Price Change %** | `item.min_price_change_pct` | Percentage (e.g., `1.5%`) | Minimum change to trigger alert |
| **Alert Cooldown** | `item.alert_cooldown_minutes` | Minutes (e.g., `5 min`) | Cooldown between alerts |

#### Technical Indicators

Display all technical indicators exactly as shown in Dashboard:

- **RSI** (Relative Strength Index)
  - Source: `signals.rsi` or `item.rsi`
  - Format: Number with 2 decimals (e.g., `45.67`) or `N/A` if not available
  
- **ATR** (Average True Range)
  - Source: `signals.atr` or `item.atr`
  - Format: Number with 2 decimals or `N/A`
  
- **Resistance Up** (Res Up)
  - Source: `signals.res_up` or `item.resistance_up`
  - Format: Currency or `N/A`
  
- **Resistance Down** (Res Down)
  - Source: `signals.res_down` or `item.resistance_down`
  - Format: Currency or `N/A`
  
- **MA50** (50-period Moving Average)
  - Source: `signals.ma50` or `item.ma50`
  - Format: Currency or `N/A`
  
- **Any other indicators** shown in Dashboard Watchlist tab

**Important:** All `N/A` values must be displayed as `N/A` (not blank, not `0`, not `null`).

### 4.2 Watchlist Coin Detail View

When a coin is selected from the list, show a detailed view with:

#### Display

1. **All values listed above** (from section 4.1)
2. **Additional metadata:**
   - Exchange name
   - Notes/description (if any)
   - Created date
   - Last modified date

#### Configuration Buttons

Below the data, show configuration buttons equivalent to the Dashboard controls:

| Button | Action | API Endpoint | Notes |
|--------|--------|--------------|-------|
| **Toggle Strategy** | Toggle `strategy` field | `POST /api/dashboard/watchlist/{symbol}` | Toggle straight strategy on/off |
| **Toggle Trade** | Toggle `trade_enabled` | `POST /api/dashboard/watchlist/{symbol}` | Enable/disable automatic trading |
| **Toggle Margin** | Toggle `trade_on_margin` | `POST /api/dashboard/watchlist/{symbol}` | Enable/disable margin trading |
| **Update Amount (USD)** | Update `trade_amount_usd` | `POST /api/dashboard/watchlist/{symbol}` | Prompt for new amount value |
| **Update SL %** | Update `sl_percentage` | `POST /api/dashboard/watchlist/{symbol}` | Prompt for new SL percentage |
| **Update TP %** | Update `tp_percentage` | `POST /api/dashboard/watchlist/{symbol}` | Prompt for new TP percentage |
| **Toggle Buy Alert** | Toggle `buy_alert_enabled` | `POST /api/dashboard/watchlist/{symbol}` | Enable/disable buy alerts |
| **Toggle Sell Alert** | Toggle `sell_alert_enabled` | `POST /api/dashboard/watchlist/{symbol}` | Enable/disable sell alerts |
| **Toggle Master Alert** | Toggle `alert_enabled` | `POST /api/dashboard/watchlist/{symbol}` | Master alert toggle |
| **Update Risk Mode** | Update `sl_tp_mode` | `POST /api/dashboard/watchlist/{symbol}` | Select: conservative, moderate, aggressive |
| **Delete Coin** | Mark as deleted | `DELETE /api/dashboard/watchlist/{symbol}` | Remove from watchlist |

#### Action Requirements

- **Pressing a button must update the underlying configuration** using the same logic as the Dashboard
- **All updates must use the same API endpoints** as the Dashboard
- **Validation rules must match** the Dashboard (e.g., minimum amounts, percentage ranges)
- **Success/error feedback** must be provided to the user

---

## 5. Open Orders Section

### 5.1 Display Format

Display all open orders in a table format.

#### Data Source

- **Primary:** `/api/orders/open` endpoint
- **Filter:** Only orders with status `OPEN`, `PARTIALLY_FILLED`, or equivalent active statuses

#### Display Fields

| Field | Source | Format | Notes |
|-------|--------|--------|-------|
| **Created Date** | `order.create_time` or `order.created_at` | Timestamp | ISO format or relative time |
| **Symbol** | `order.symbol` | Text (e.g., `BTC_USDT`) | Trading pair |
| **Side** | `order.side` | Text (`BUY` or `SELL`) | Order direction |
| **Type** | `order.type` | Text (e.g., `LIMIT`, `MARKET`, `STOP_LOSS`, `TAKE_PROFIT`) | Order type |
| **Quantity** | `order.quantity` | Number with decimals | Order size |
| **Price** | `order.price` | Currency | Limit price (if applicable) |
| **Wallet Balance** | Calculated from portfolio | Currency | Available balance for this coin |
| **Status** | `order.status` | Text (e.g., `OPEN`, `PARTIALLY_FILLED`) | Current order status |
| **Order ID** | `order.order_id` or `order.client_oid` | Text | Exchange order identifier |

#### Sorting

- **Default Sort:** By created date, **descending** (most recent first)
- **User Sort:** Allow sorting by any column (same as Dashboard)

#### Read-Only Status

This section is **read-only by default**. No cancellation or modification actions are available.

### 5.2 Optional Features

#### Filter by Coin Symbol

- Provide a search/filter input field
- Filter orders by symbol (case-insensitive partial match)
- Display filtered count: "Showing X of Y orders"

---

## 6. Expected Take Profit Section

### 6.1 Display Format

Display all currently open positions with their Expected Take Profit values.

#### Data Source

- **Primary:** `/api/expected-take-profit/summary` endpoint
- **Alternative:** Calculate from open positions and TP orders

#### Display Fields

| Field | Source | Format | Notes |
|-------|--------|--------|-------|
| **Symbol** | `item.symbol` | Text (e.g., `BTC_USDT`) | Trading pair |
| **Net Quantity** | `item.net_qty` | Number with decimals | Net position size (positive = long, negative = short) |
| **Average Entry Price** | `item.avg_entry_price` | Currency | Weighted average entry price |
| **Current Price** | `item.current_price` | Currency | Latest market price |
| **Expected Take Profit** | `item.expected_tp` | Currency | Calculated TP value |
| **Expected Take Profit %** | Calculated | Percentage | TP percentage from entry |
| **Unrealized PnL** | Calculated | Currency | Current unrealized profit/loss |
| **Unrealized PnL %** | Calculated | Percentage | PnL as percentage of entry |

#### Sorting

- **Default Sort:** By Expected Take Profit value, **descending** (highest TP first)
- **User Sort:** Allow sorting by any column

### 6.2 Position Details Button

For each entry, include a button to **view full position details**.

#### Details View

When clicked, display:

- **Full position breakdown:**
  - All buy orders contributing to position
  - All sell orders contributing to position
  - Matched lots (FIFO or LIFO matching)
  - Individual lot PnL
  - Total position metrics

- **Data Source:** `/api/expected-take-profit/details/{symbol}`

- **Display Format:** Match the Dashboard "Expected Take Profit Details" dialog exactly

---

## 7. Executed Orders Section

### 7.1 Display Format

Display all executed orders (filled/completed orders).

#### Data Source

- **Primary:** `/api/orders/history` endpoint
- **Filter:** Only orders with status `FILLED`, `EXECUTED`, or equivalent completed statuses
- **Optional Filter:** Hide cancelled/rejected orders (user preference)

#### Display Fields

| Field | Source | Format | Notes |
|-------|--------|--------|-------|
| **Executed Date** | `order.executed_time` or `order.filled_time` | Timestamp | When order was filled |
| **Symbol** | `order.symbol` | Text (e.g., `BTC_USDT`) | Trading pair |
| **Side** | `order.side` | Text (`BUY` or `SELL`) | Order direction |
| **Type** | `order.type` | Text | Order type |
| **Quantity** | `order.filled_quantity` or `order.quantity` | Number with decimals | Executed quantity |
| **Price** | `order.filled_price` or `order.avg_price` | Currency | Execution price |
| **Total Value** | `quantity * price` | Currency | Total order value |
| **Status** | `order.status` | Text (e.g., `FILLED`) | Order status |
| **Order ID** | `order.order_id` | Text | Exchange order identifier |
| **Realized PnL** | Calculated | Currency | Profit/loss from this order (if applicable) |

#### Sorting

- **Default Sort:** By executed date, **descending** (most recent first)
- **User Sort:** Allow sorting by any column

### 7.2 Optional Features

#### Filter by Coin Symbol

- Provide a search/filter input field
- Filter orders by symbol (case-insensitive partial match)
- Display filtered count: "Showing X of Y executed orders"

#### Date Range Filter

- Optional: Filter by date range (start date, end date)
- Display orders within specified range only

---

## 8. Monitoring Section

The Monitoring section contains the following sub-sections, accessible via buttons:

### 8.1 System Monitoring

**Button Label:** "System Monitoring"

#### Display Content

- **Overall system health and metrics**, identical to the Dashboard Monitoring tab
- **Data Source:** `/api/monitoring/health` or equivalent endpoint

#### Metrics to Display

- Backend service status (running/stopped)
- Database connection status
- Exchange API connection status
- Last sync timestamps
- Error counts and recent errors
- Performance metrics (response times, query times)
- Trading bot status (LIVE/DRY_RUN)
- Any other metrics shown in Dashboard System Monitoring

### 8.2 Throttle

**Button Label:** "Throttle"

#### Display Content

- **Most recent messages sent to Telegram**
- **Data Source:** `/api/monitoring/telegram-messages` or database query to `telegram_messages` table

#### Display Format

- List of recent messages with:
  - Timestamp
  - Message content (truncated if long)
  - Message type/classification
  - Status (sent, blocked, throttled)

#### Sorting

- **Default Sort:** By timestamp, **descending** (most recent first)

### 8.3 Monitoring Workflows

**Button Label:** "Monitoring Workflows"

#### Display Content

- **Workflow-level monitoring information**
- **Data Source:** `/api/monitoring/workflows` or equivalent endpoint

#### Display Format

- List of workflows with:
  - Workflow name
  - Last execution time
  - Execution status (success, error, pending)
  - Execution count
  - Last error message (if any)
  - Next scheduled execution (if applicable)

### 8.4 Blocked Telegram Messages

**Button Label:** "Blocked Telegram Messages"

#### Display Content

- **Messages that were blocked or suppressed**
- **Data Source:** Filter `telegram_messages` where `blocked = true` or `suppressed = true`

#### Display Format

- List of blocked messages with:
  - Timestamp
  - Message content
  - Block reason (e.g., "Throttled", "Duplicate", "Origin: LOCAL")
  - Original message metadata

#### Sorting

- **Default Sort:** By timestamp, **descending** (most recent first)

---

## 9. Version History Section

### 9.1 Display Format

Display version history exactly as shown in the Dashboard Version History tab.

#### Data Source

- **Primary:** Hardcoded version history array (same as Dashboard)
- **Alternative:** `/api/version/history` if endpoint exists

#### Display Fields

| Field | Format | Notes |
|-------|--------|-------|
| **Version Number** | Text (e.g., `0.45`) | Version identifier |
| **Release Date** | Date (e.g., `2025-01-15`) | When version was released |
| **Details** | Text (multi-line) | Changelog details |

#### Display Format

- List of versions in reverse chronological order (newest first)
- Each version entry shows:
  - Version number (e.g., `v0.45`)
  - Release date
  - Detailed changelog

#### Read-Only Status

This section is **read-only**. No editing or modification is possible.

---

## 10. Implementation Requirements

### 10.1 Data Source Consistency

All Telegram menu implementations must:

1. **Use the same API endpoints** as the Dashboard
2. **Use the same database queries** as the Dashboard
3. **Use the same calculation formulas** as the Dashboard
4. **Handle errors identically** to the Dashboard (same error messages, fallbacks)

### 10.2 Update Frequency

- **Real-time updates:** When user navigates to a section, fetch fresh data
- **Background refresh:** Optional automatic refresh every 30-60 seconds when section is active
- **Manual refresh:** Provide refresh button in each section

### 10.3 Error Handling

- **Network errors:** Display user-friendly error message, allow retry
- **Data errors:** Display partial data if available, show error indicator
- **Authentication errors:** Redirect to authorization check

### 10.4 User Experience

- **Navigation:** Clear section buttons, breadcrumb navigation for detail views
- **Loading states:** Show loading indicators while fetching data
- **Empty states:** Display helpful messages when no data is available
- **Pagination:** For large lists, implement pagination (same page size as Dashboard)

---

## 11. Governance and Maintenance

### 11.1 Change Process

1. **Document First:** Any change to Telegram menu structure must be documented here first
2. **Dashboard Alignment:** Verify change exists in Dashboard before implementing in Telegram
3. **Implementation:** Implement change according to this specification
4. **Verification:** Test that Telegram menu matches Dashboard behavior exactly

### 11.2 Version Control

- **Document Version:** Update version number and "Last Updated" date when making changes
- **Change Log:** Document significant changes in a changelog section (if needed)

### 11.3 Compliance

- **No Divergence:** Telegram menu must never diverge from Dashboard without updating this document
- **Single Source of Truth:** This document is authoritative for all Telegram menu implementations
- **Review Required:** Any structural changes require review and approval before implementation

---

## 12. Appendices

### 12.1 API Endpoint Reference

| Section | Endpoint | Method | Notes |
|---------|----------|--------|-------|
| Portfolio | `/api/portfolio` | GET | Returns portfolio assets and total value |
| Portfolio | `/api/dashboard/state` | GET | Returns full dashboard state |
| Watchlist | `/api/dashboard/watchlist` | GET | Returns watchlist items |
| Watchlist | `/api/dashboard/watchlist/{symbol}` | POST | Update watchlist item |
| Open Orders | `/api/orders/open` | GET | Returns open orders |
| Expected TP | `/api/expected-take-profit/summary` | GET | Returns TP summary |
| Expected TP | `/api/expected-take-profit/details/{symbol}` | GET | Returns TP details for symbol |
| Executed Orders | `/api/orders/history` | GET | Returns order history |
| Monitoring | `/api/monitoring/health` | GET | Returns system health |
| Monitoring | `/api/monitoring/telegram-messages` | GET | Returns Telegram messages |
| Monitoring | `/api/monitoring/workflows` | GET | Returns workflow status |

### 12.2 Data Model Reference

Refer to Dashboard TypeScript types for exact data structures:

- `PortfolioAsset`
- `WatchlistItem`
- `OpenOrder`
- `ExpectedTPSummaryItem`
- `ExpectedTPDetails`
- `TelegramMessage`
- `DashboardState`

---

## Document Status

**Status:** ✅ Active and Authoritative  
**Maintained By:** Development Team  
**Review Frequency:** Quarterly or when Dashboard structure changes  
**Last Review Date:** 2025-01-27

---

**End of Specification**

