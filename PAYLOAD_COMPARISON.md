# Payload Comparison: Manual Order vs Bot Order

## Manual Order (SUCCESSFUL) - BTC_USD

Order ID: 5755600478601727672
Status: FILLED

**From API Response:**
```json
{
  "order_id": "5755600478601727672",
  "client_oid": "fLodSVBrL-tnSqpMOSpcx",
  "order_type": "MARKET",
  "time_in_force": "GOOD_TILL_CANCEL",
  "side": "BUY",
  "exec_inst": ["MARGIN_ORDER"],  // ⭐ KEY DIFFERENCE!
  "quantity": "0.01044",
  "order_value": "1049.429844",
  "instrument_name": "BTC_USD",
  "status": "FILLED"
}
```

**Key observation:** The response includes `"exec_inst": ["MARGIN_ORDER"]`, which suggests the original request payload likely included `exec_inst` as a parameter.

## Bot Order (FAILING) - BTC_USDT

**From [ENTRY_ORDER][AUTO] logs:**
```json
{
  "id": 1,
  "method": "private/create-order",
  "api_key": "...",
  "params": {
    "instrument_name": "BTC_USDT",
    "side": "BUY",
    "type": "MARKET",
    "client_oid": "...",
    "notional": "1000.00",
    "leverage": "2"  // ⭐ We send leverage but NOT exec_inst
  },
  "nonce": ...,
  "sig": "..."
}
```

**Response:**
```json
{
  "code": 306,
  "message": "INSUFFICIENT_AVAILABLE_BALANCE",
  "result": {
    "client_oid": "...",
    "order_id": "..."
  }
}
```

## KEY DIFFERENCE IDENTIFIED

**Manual order response includes:**
- `"exec_inst": ["MARGIN_ORDER"]` ✅

**Bot order payload includes:**
- `"leverage": "2"` ❌
- NO `exec_inst` parameter ❌

## Hypothesis

The manual order likely sends `exec_inst` in the request payload, while the bot sends `leverage`. Crypto.com might require `exec_inst: ["MARGIN_ORDER"]` to properly identify the order as a margin order, in addition to (or instead of) the `leverage` parameter.

## Next Step

Try adding `exec_inst: ["MARGIN_ORDER"]` to the bot's payload and see if that fixes the issue.

