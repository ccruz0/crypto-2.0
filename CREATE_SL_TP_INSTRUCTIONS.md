# Create SL/TP Orders for Last SOL_USDT Order

This document explains how to create SL/TP orders for the last SOL_USDT order that doesn't have them.

## Method 1: Using the API Endpoint (Recommended)

If your backend is running, use the API endpoint:

```bash
# Using curl
curl -X POST "http://localhost:8000/api/orders/create-sl-tp-for-last-order?symbol=SOL_USDT"

# Or using the provided script
./create_sol_sl_tp_api.sh SOL_USDT
```

**Response on success:**
```json
{
  "ok": true,
  "message": "SL/TP orders created successfully for order 5755600477885552283",
  "order_id": "5755600477885552283",
  "symbol": "SOL_USDT",
  "filled_price": 166.98,
  "filled_qty": 0.059
}
```

## Method 2: Using Python Script (Direct Database Access)

If you have direct database access, run the Python script:

```bash
# From the backend directory
cd backend
python3 create_sl_tp_for_symbol.py SOL_USDT

# Or from project root
python3 backend/create_sl_tp_for_symbol.py SOL_USDT
```

## Method 3: Using Docker Exec

If your backend is running in Docker:

```bash
# Find the backend container
docker ps | grep backend

# Execute the script inside the container
docker exec -it <container_name> python3 create_sl_tp_for_symbol.py SOL_USDT
```

## What It Does

1. **Finds the last filled BUY order** for SOL_USDT (or specified symbol)
2. **Checks if SL/TP orders already exist** - if they do, it will report them
3. **Creates SL/TP orders** using the same logic as automatic orders:
   - Uses watchlist configuration (`sl_percentage`, `tp_percentage`, `sl_tp_mode`)
   - Blends with ATR-based calculations if available
   - Creates `STOP_LIMIT` and `TAKE_PROFIT_LIMIT` orders
   - Links them with an OCO group
   - Sends Telegram notifications

## SL/TP Calculation Logic

The SL/TP prices are calculated using:

1. **Watchlist configuration** (if set):
   - `sl_percentage` - Stop Loss percentage
   - `tp_percentage` - Take Profit percentage
   - `sl_tp_mode` - "conservative" or "aggressive"

2. **Default percentages** (if not set):
   - Conservative: 3% SL, 3% TP
   - Aggressive: 2% SL, 2% TP

3. **ATR blending** (if ATR is available):
   - Conservative: 2x ATR for SL, 3x ATR for TP
   - Aggressive: 1x ATR for SL, 2x ATR for TP
   - Blends with percentage-based calculations

## Verification

After creating SL/TP orders, verify they were created:

```bash
# Check via API
curl "http://localhost:8000/api/orders/open" | python3 -m json.tool | grep -A 10 "SOL_USDT"

# Or check the database directly
# (if you have database access)
```

## Troubleshooting

### Error: "No filled BUY orders found"
- Make sure there are filled BUY orders for the symbol
- Check the order history: `GET /api/orders/history?limit=10`

### Error: "Order already has SL/TP orders"
- The order already has SL/TP protection
- Check existing orders: The response will list them

### Error: Database connection timeout
- Make sure the database is running and accessible
- Check `DATABASE_URL` environment variable
- If using Docker, ensure the database container is running

### Error: API connection failed
- Make sure the backend is running
- Check the API URL (default: `http://localhost:8000`)
- Verify the endpoint is accessible: `curl http://localhost:8000/ping_fast`

## Notes

- The script uses the **same logic** as automatic SL/TP creation
- Orders are created with **OCO (One-Cancels-Other)** linking
- **Telegram notifications** are sent when orders are created
- The script respects `LIVE_TRADING` environment variable (DRY RUN if false)

