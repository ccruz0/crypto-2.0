# Watchlist Consistency Report

**Generated:** 2025-12-31T13:11:44.925768

**Purpose:** Compares dashboard API data (`/api/dashboard`) with backend database (`WatchlistItem`)

## Summary

- **Total Items (DB):** 23
- **API Available:** ❌ No
- **Trade Enabled (DB):** 5
- **Alert Enabled (Master, DB):** 5
- **Buy Alert Enabled (DB):** 5
- **Sell Alert Enabled (DB):** 5
- **With Throttle State:** 1

### API vs Database Comparison

- **API Mismatches:** 0
- **Only in DB:** 23
- **Only in API:** 0

## ⚠️ Issues Found

- **BTC_USDT**: Symbol exists in DB but not in API response
- **ETH_USDT**: Symbol exists in DB but not in API response
- **SOL_USDT**: Symbol exists in DB but not in API response
- **DOGE_USDT**: Symbol exists in DB but not in API response
- **ADA_USDT**: Symbol exists in DB but not in API response
- **BNB_USDT**: Symbol exists in DB but not in API response
- **XRP_USDT**: Symbol exists in DB but not in API response
- **MATIC_USDT**: Symbol exists in DB but not in API response
- **AVAX_USDT**: Symbol exists in DB but not in API response
- **DOT_USDT**: Symbol exists in DB but not in API response
- **LINK_USDT**: Symbol exists in DB but not in API response
- **UNI_USDT**: Symbol exists in DB but not in API response
- **ATOM_USDT**: Symbol exists in DB but not in API response
- **ALGO_USDT**: Symbol exists in DB but not in API response
- **NEAR_USDT**: Symbol exists in DB but not in API response
- **ICP_USDT**: Symbol exists in DB but not in API response
- **FIL_USDT**: Symbol exists in DB but not in API response
- **APT_USDT**: Symbol exists in DB but not in API response
- **BTC_USD**: Symbol exists in DB but not in API response
- **BONK_USD**: Symbol exists in DB but not in API response
- **LDO_USD**: Symbol exists in DB but not in API response
- **ETC_USDT**: Symbol exists in DB but not in API response
- **TRX_USDT**: Symbol exists in DB but not in API response

## Watchlist Items

| Symbol | Trade | Alert | Buy Alert | Sell Alert | Strategy (DB) | Strategy (API) | Throttle | In API | Issues |
|--------|-------|-------|-----------|------------|---------------|---------------|----------|--------|--------|
| BTC_USDT | ❌ | ❌ | ❌ | ❌ | ⚠️ swing-conservative | ⚠️ None | — | ❌ | Symbol exists in DB but not in API response |
| ETH_USDT | ❌ | ❌ | ❌ | ❌ | ⚠️ intraday-conservative | ⚠️ None | — | ❌ | Symbol exists in DB but not in API response |
| SOL_USDT | ❌ | ❌ | ❌ | ❌ | ⚠️ swing-conservative | ⚠️ None | — | ❌ | Symbol exists in DB but not in API response |
| DOGE_USDT | ❌ | ❌ | ❌ | ❌ | ⚠️ swing-conservative | ⚠️ None | — | ❌ | Symbol exists in DB but not in API response |
| ADA_USDT | ❌ | ❌ | ❌ | ❌ | ⚠️ swing-conservative | ⚠️ None | — | ❌ | Symbol exists in DB but not in API response |
| BNB_USDT | ❌ | ❌ | ❌ | ❌ | ⚠️ swing-conservative | ⚠️ None | — | ❌ | Symbol exists in DB but not in API response |
| XRP_USDT | ❌ | ❌ | ❌ | ❌ | ⚠️ swing-conservative | ⚠️ None | — | ❌ | Symbol exists in DB but not in API response |
| MATIC_USDT | ❌ | ❌ | ❌ | ❌ | ⚠️ swing-conservative | ⚠️ None | — | ❌ | Symbol exists in DB but not in API response |
| AVAX_USDT | ❌ | ❌ | ❌ | ❌ | ⚠️ swing-conservative | ⚠️ None | — | ❌ | Symbol exists in DB but not in API response |
| DOT_USDT | ❌ | ❌ | ❌ | ❌ | ⚠️ scalp-conservative | ⚠️ None | — | ❌ | Symbol exists in DB but not in API response |
| LINK_USDT | ❌ | ❌ | ❌ | ❌ | ⚠️ scalp-conservative | ⚠️ None | — | ❌ | Symbol exists in DB but not in API response |
| UNI_USDT | ✅ | ✅ | ✅ | ✅ | ⚠️ swing-conservative | ⚠️ None | — | ❌ | Symbol exists in DB but not in API response |
| ATOM_USDT | ❌ | ❌ | ❌ | ❌ | ⚠️ swing-conservative | ⚠️ None | — | ❌ | Symbol exists in DB but not in API response |
| ALGO_USDT | ❌ | ❌ | ❌ | ❌ | ⚠️ scalp-conservative | ⚠️ None | — | ❌ | Symbol exists in DB but not in API response |
| NEAR_USDT | ❌ | ❌ | ❌ | ❌ | ⚠️ swing-conservative | ⚠️ None | — | ❌ | Symbol exists in DB but not in API response |
| ICP_USDT | ❌ | ❌ | ❌ | ❌ | ⚠️ swing-conservative | ⚠️ None | — | ❌ | Symbol exists in DB but not in API response |
| FIL_USDT | ❌ | ❌ | ❌ | ❌ | ⚠️ swing-conservative | ⚠️ None | — | ❌ | Symbol exists in DB but not in API response |
| APT_USDT | ❌ | ❌ | ❌ | ❌ | ⚠️ swing-conservative | ⚠️ None | — | ❌ | Symbol exists in DB but not in API response |
| BTC_USD | ✅ | ✅ | ✅ | ✅ | ⚠️ scalp-conservative | ⚠️ None | ✅ | ❌ | Symbol exists in DB but not in API response |
| BONK_USD | ❌ | ❌ | ❌ | ❌ | ⚠️ swing-aggressive | ⚠️ None | — | ❌ | Symbol exists in DB but not in API response |
| LDO_USD | ✅ | ✅ | ✅ | ✅ | ⚠️ scalp-conservative | ⚠️ None | — | ❌ | Symbol exists in DB but not in API response |
| ETC_USDT | ✅ | ✅ | ✅ | ✅ | ⚠️ swing-conservative | ⚠️ None | — | ❌ | Symbol exists in DB but not in API response |
| TRX_USDT | ✅ | ✅ | ✅ | ✅ | ⚠️ swing-aggressive | ⚠️ None | — | ❌ | Symbol exists in DB but not in API response |