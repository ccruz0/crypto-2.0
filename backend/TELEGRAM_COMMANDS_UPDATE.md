# Telegram Commands Update

## Changes Made

### 1. Updated `/watchlist` Command
**Now shows:**
- Alert status: "Alert: YES" or "Alert: NO"  
- Margin status: "Margin: YES" or "Margin: NO"
- Amount separately displayed

**Example output:**
```
👀 *Watchlist (2 coins with Trade=YES)*

• *BTC_USDT*
  Alert: YES | Margin: NO
  Price: N/A | Target: N/A
  Amount: $100.00

• *ETH_USDT*
  Alert: YES | Margin: NO
  Price: N/A | Target: N/A
  Amount: $10.00
```

### 2. Added `/alerts` Command
**New command** to show only coins with Alert=YES

**Usage:** `/alerts`

**Example output:**
```
🔔 *Alerts (2 coins with Alert=YES)*

• *BTC_USDT*
  ✅ Trade | ❌ Margin
  Price: N/A | Target: N/A | Amount: $100.00

• *ETH_USDT*
  ✅ Trade | ❌ Margin
  Price: N/A | Target: N/A | Amount: $10.00
```

### 3. Improved `/analyze` Command
**Now supports two modes:**

**Mode 1: Without symbol** - Shows interactive menu
```
/analyze
```
Shows inline keyboard with all watchlist coins as buttons. Click a coin to analyze it.

**Mode 2: With symbol** - Direct analysis
```
/analyze BTC_USDT
```
Shows detailed analysis for that specific coin.

**Features:**
- Up to 20 coins shown in menu (2 per row)
- Inline keyboard for easy selection
- Fallback to text list if keyboard fails
- Callback handling for button clicks

## Files Modified
- `backend/app/services/telegram_commands.py`:
  - Added `send_alerts_list_message()` function
  - Updated `send_watchlist_message()` to show Alert and Margin status
  - Updated `send_analyze_message()` to show menu when no symbol provided
  - Added callback handler for `analyze_` buttons
  - Updated help messages

## Commands Available

| Command | Description |
|---------|-------------|
| /watchlist | Show coins with Trade=YES (with Alert/Margin status) |
| /alerts | Show coins with Alert=YES (with Trade/Margin status) |
| /analyze | Show menu to select coin, or /analyze SYMBOL for direct analysis |

## Next Steps
1. Test all commands in Telegram
2. Verify inline keyboard works
3. Check that Alert and Margin status display correctly
4. Consider adding similar improvements to other commands

