# Telegram Menu Review

**Date**: 2026-01-08  
**Purpose**: Comprehensive review of Telegram bot menu structure and functionality

---

## Overview

The Telegram bot provides an interactive menu system with inline keyboard buttons that match the dashboard layout. The menu is organized hierarchically with a main menu and sub-menus for different sections.

---

## Main Menu Structure

The main menu (`show_main_menu`) displays 7 primary sections matching the dashboard:

```
📋 Main Menu

Select a section:

[💼 Portfolio]
[📊 Watchlist]
[📋 Open Orders]
[🎯 Expected Take Profit]
[✅ Executed Orders]
[🔍 Monitoring]
[📝 Version History]
```

**Menu Items:**
1. **💼 Portfolio** - `menu:portfolio` - View portfolio and positions
2. **📊 Watchlist** - `menu:watchlist` - Manage watchlist coins
3. **📋 Open Orders** - `menu:open_orders` - View open trading orders
4. **🎯 Expected Take Profit** - `menu:expected_tp` - View expected TP orders
5. **✅ Executed Orders** - `menu:executed_orders` - View executed orders
6. **🔍 Monitoring** - `menu:monitoring` - System monitoring and health
7. **📝 Version History** - `cmd:version` - Show version information

---

## Persistent Keyboard (Bottom Buttons)

The bot also sets up a persistent keyboard that appears at the bottom of the chat:

```
[🚀 Start]
[📊 Status] [💰 Portfolio]
[📈 Signals] [📋 Watchlist]
[⚙️ Menu] [❓ Help]
```

**Buttons:**
- **🚀 Start** - Shows welcome message and main menu
- **📊 Status** - System status report
- **💰 Portfolio** - Portfolio view
- **📈 Signals** - Trading signals
- **📋 Watchlist** - Watchlist management
- **⚙️ Menu** - Main menu
- **❓ Help** - Help message

---

## Watchlist Menu

### Main Watchlist View

Shows paginated list of watchlist coins (9 per page, 3 per row):

```
⚙️ Watchlist Control

[BTC_USDT ✅] [ETH_USDT ✅] [DOT_USDT ✅]
[SOL_USDT ✅] [ADA_USDT ✅] [LINK_USDT ✅]
[MATIC_USDT ✅] [AVAX_USDT ✅] [ATOM_USDT ✅]

[⬅️ Prev] [📄 1/3] [Next ➡️]

[➕ Add Symbol] [🔄 Refresh]
[🏠 Main Menu]
```

**Features:**
- Pagination (9 coins per page)
- 3 coins per row
- Status icons for each coin
- Navigation buttons (Prev/Next)
- Add symbol button
- Refresh button
- Back to main menu

### Coin Detail Menu

When clicking on a coin, shows detailed controls:

```
⚙️ BTC_USDT Settings

[Coin summary with current settings]

[🔔 Alert] [🟢 Buy Alert] [🔻 Sell Alert]
[🤖 Trade] [⚡ Margin] [🎯 Risk Mode]
[💵 Amount USD] [📊 Min %] [⏱ Cooldown]
[📉 SL%] [📈 TP%] [🧠 Preset]
[📝 Notas] [🧪 Test Alert] [🗑️ Delete]
[🔙 Back] [🏠 Main]
```

**Toggle Buttons:**
- **🔔 Alert** - Toggle alert enabled
- **🟢 Buy Alert** - Toggle buy alert
- **🔻 Sell Alert** - Toggle sell alert
- **🤖 Trade** - Toggle trade enabled
- **⚡ Margin** - Toggle margin trading
- **🎯 Risk Mode** - Toggle between conservative/aggressive

**Setting Buttons:**
- **💵 Amount USD** - Set trading amount
- **📊 Min %** - Set minimum percentage
- **⏱ Cooldown** - Set cooldown period
- **📉 SL%** - Set stop loss percentage
- **📈 TP%** - Set take profit percentage
- **🧠 Preset** - Apply preset configuration

**Action Buttons:**
- **📝 Notas** - Edit notes
- **🧪 Test Alert** - Send test alert
- **🗑️ Delete** - Delete coin from watchlist
- **🔙 Back** - Return to watchlist
- **🏠 Main** - Return to main menu

---

## Portfolio Menu

Shows portfolio information with positions and balances.

**Features:**
- Open positions
- Account balance
- P&L information
- Back to main menu button

---

## Open Orders Menu

Displays all open trading orders.

**Features:**
- List of open orders
- Order details (symbol, side, price, quantity, status)
- Navigation buttons
- Back to main menu

---

## Expected Take Profit Menu

Shows expected TP orders and calculations.

**Features:**
- Expected TP orders
- TP calculations
- Position details
- Back to main menu

---

## Executed Orders Menu

Shows history of executed orders.

**Features:**
- Executed orders list
- Order history
- Execution details
- Back to main menu

---

## Monitoring Menu

System monitoring and health information.

**Features:**
- System health status
- Service status
- Market data status
- Signal monitor status
- Telegram status
- Trade system status
- Back to main menu

---

## Commands Available

### Text Commands

- `/start` - Show welcome message and main menu
- `/help` - Show help message with command list
- `/status` - Get bot status report
- `/portfolio` - List all open orders and active positions
- `/signals` - Display last 5 trading signals
- `/balance` - Show exchange account balance
- `/watchlist` - Show all coins with Trade=YES
- `/alerts` - Show all coins with Alert=YES
- `/analyze <symbol>` - Get detailed analysis for a coin
- `/add <symbol>` - Add a coin to the watchlist
- `/audit` or `/snapshot` - Show system audit snapshot
- `/create_sl_tp [symbol]` - Create SL/TP orders
- `/create_sl [symbol]` - Create only SL order
- `/create_tp [symbol]` - Create only TP order
- `/skip_sl_tp_reminder [symbol]` - Skip SL/TP reminders

### Bot Commands Menu

The bot registers only one command in Telegram's command menu:
- `/menu` - Open main menu

This keeps the command list clean while all functionality is available through the menu buttons.

---

## Callback Data Structure

The menu uses callback data to handle button clicks:

### Main Menu Callbacks
- `menu:main` - Show main menu
- `menu:portfolio` - Show portfolio
- `menu:watchlist` - Show watchlist
- `menu:open_orders` - Show open orders
- `menu:expected_tp` - Show expected TP
- `menu:executed_orders` - Show executed orders
- `menu:monitoring` - Show monitoring

### Watchlist Callbacks
- `watchlist:page:N` - Navigate to page N
- `watchlist:add` - Add new symbol
- `wl:coin:SYMBOL` - Show coin detail menu
- `wl:coin:SYMBOL:toggle:FIELD` - Toggle field (alert, trade, etc.)
- `wl:coin:SYMBOL:set:FIELD` - Set field value
- `wl:coin:SYMBOL:preset` - Apply preset
- `wl:coin:SYMBOL:test` - Test alert
- `wl:coin:SYMBOL:delete` - Delete coin

### Command Callbacks
- `cmd:version` - Show version
- `cmd:status` - Show status
- `cmd:help` - Show help

---

## Menu Features

### 1. Menu Editing
- Menus use `_send_or_edit_menu()` to update existing messages instead of creating new ones
- Keeps chat tidy by editing the same message
- Falls back to sending new message if edit fails

### 2. Authorization
- All menu actions check authorization via `_is_authorized()`
- Uses `TELEGRAM_AUTH_USER_ID` or `TELEGRAM_CHAT_ID` for authorization
- Unauthorized users see "⛔ Not authorized" message

### 3. Deduplication
- Prevents duplicate button clicks using callback data tracking
- TTL-based deduplication (5 seconds for callbacks, 3 seconds for text commands)
- Prevents duplicate toggles within 2 seconds

### 4. Pagination
- Watchlist uses pagination (9 items per page)
- Navigation buttons (Prev/Next) for page navigation
- Shows current page number (e.g., "📄 1/3")

### 5. Status Icons
- Coins show status icons in watchlist:
  - ✅ = Active/Enabled
  - ❌ = Disabled
  - ⚠️ = Warning
  - 🔔 = Alert enabled
  - 🤖 = Trade enabled

---

## Menu Flow

```
Main Menu
  ├── Portfolio
  │     └── [Back to Main]
  ├── Watchlist
  │     ├── Coin List (paginated)
  │     │     └── Coin Detail Menu
  │     │           ├── Toggle Buttons
  │     │           ├── Setting Buttons
  │     │           └── Action Buttons
  │     └── [Back to Main]
  ├── Open Orders
  │     └── [Back to Main]
  ├── Expected Take Profit
  │     └── [Back to Main]
  ├── Executed Orders
  │     └── [Back to Main]
  ├── Monitoring
  │     └── [Back to Main]
  └── Version History
```

---

## Implementation Details

### Keyboard Building
- Uses `_build_keyboard()` helper function
- Creates `inline_keyboard` structure for Telegram API
- Supports multiple rows and buttons per row

### Menu Messages
- Uses `_send_menu_message()` to send new menu messages
- Uses `_edit_menu_message()` to update existing messages
- HTML formatting for text (bold, emojis)

### Error Handling
- All menu functions have try/except blocks
- Errors are logged and user-friendly messages are sent
- Failed operations return `False` for monitoring

---

## Recommendations

### Current Strengths
✅ Clean menu structure matching dashboard  
✅ Hierarchical navigation with back buttons  
✅ Pagination for large lists  
✅ Deduplication prevents duplicate actions  
✅ Authorization checks on all actions  
✅ Status icons for quick visual feedback  

### Potential Improvements
1. **Breadcrumbs** - Show current location in menu hierarchy
2. **Search** - Add search functionality for watchlist
3. **Filters** - Filter watchlist by status (enabled/disabled)
4. **Quick Actions** - Add quick action buttons (e.g., "Create SL/TP for all")
5. **Notifications** - Menu notifications for important events
6. **Keyboard Shortcuts** - Support keyboard shortcuts for power users

---

## Testing

To test the menu:
1. Send `/start` or `/menu` to the bot
2. Navigate through all menu sections
3. Test toggle buttons on coin detail menu
4. Test pagination in watchlist
5. Verify back buttons work correctly
6. Test authorization (unauthorized users should be blocked)

---

## Related Files

- `backend/app/services/telegram_commands.py` - Main menu implementation
- `backend/app/services/telegram_notifier.py` - Message sending utilities
- `backend/app/models/telegram_state.py` - State management

---

**Last Updated**: 2026-01-08


