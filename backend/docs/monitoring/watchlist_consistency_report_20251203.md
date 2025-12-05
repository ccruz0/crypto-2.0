# Watchlist Consistency Report — 2025-12-03

**Generated:** 2025-12-03T12:57:44.271596+00:00

## Summary

- **Total coins checked:** 20
- **Coins with mismatches:** 20
- **Coins fully correct:** 0
- **Coins with minor drift:** 0

- **Average backend query time:** 0.075s

## Symbols with Issues

| Symbol | Status | Issues |
|--------|--------|--------|
| BTC_USDT | HAS_ISSUES | price, rsi, ma50, ma200, ema10 (+3 more) |
| ETH_USDT | HAS_ISSUES | price, rsi, ma50, ma200, ema10 (+3 more) |
| SOL_USDT | HAS_ISSUES | price, rsi, ma50, ma200, ema10 (+3 more) |
| DOGE_USDT | HAS_ISSUES | price, rsi, ma50, ma200, ema10 (+3 more) |
| ADA_USDT | HAS_ISSUES | price, rsi, ma50, ma200, ema10 (+3 more) |
| BNB_USDT | HAS_ISSUES | price, rsi, ma50, ma200, ema10 (+3 more) |
| XRP_USDT | HAS_ISSUES | price, rsi, ma50, ma200, ema10 (+3 more) |
| MATIC_USDT | HAS_ISSUES | price, rsi, ma50, ma200, ema10 (+3 more) |
| AVAX_USDT | HAS_ISSUES | price, rsi, ma50, ma200, ema10 (+3 more) |
| DOT_USDT | HAS_ISSUES | price, rsi, ma50, ma200, ema10 (+3 more) |
| LINK_USDT | HAS_ISSUES | price, rsi, ma50, ma200, ema10 (+3 more) |
| UNI_USDT | HAS_ISSUES | price, rsi, ma50, ma200, ema10 (+3 more) |
| ATOM_USDT | HAS_ISSUES | price, rsi, ma50, ma200, ema10 (+3 more) |
| ALGO_USDT | HAS_ISSUES | price, rsi, ma50, ma200, ema10 (+3 more) |
| NEAR_USDT | HAS_ISSUES | price, rsi, ma50, ma200, ema10 (+3 more) |
| ICP_USDT | HAS_ISSUES | price, rsi, ma50, ma200, ema10 (+3 more) |
| FIL_USDT | HAS_ISSUES | price, rsi, ma50, ma200, ema10 (+3 more) |
| APT_USDT | HAS_ISSUES | price, rsi, ma50, ma200, ema10 (+3 more) |
| BTC_USD | HAS_ISSUES | price, rsi, ma50, ma200, ema10 (+4 more) |
| BONK_USD | HAS_ISSUES | price, rsi, ma50, ma200, ema10 (+1 more) |

## Detailed Results

| Symbol | Field | Frontend | Backend | Status |
|--------|-------|----------|---------|--------|
| BTC_USDT | price | - | 103069.2000 | MISMATCH |
| BTC_USDT | rsi | - | 41.3400 | MISMATCH |
| BTC_USDT | ma50 | - | 102742.1300 | MISMATCH |
| BTC_USDT | ma200 | - | 107787.9700 | MISMATCH |
| BTC_USDT | ema10 | - | 103230.2800 | MISMATCH |
| BTC_USDT | atr | - | - | EXACT_MATCH |
| BTC_USDT | buy_target | - | - | EXACT_MATCH |
| BTC_USDT | take_profit | - | - | EXACT_MATCH |
| BTC_USDT | stop_loss | - | - | EXACT_MATCH |
| BTC_USDT | sl_price | - | - | EXACT_MATCH |
| BTC_USDT | tp_price | - | - | EXACT_MATCH |
| BTC_USDT | sl_percentage | - | - | EXACT_MATCH |
| BTC_USDT | tp_percentage | - | - | EXACT_MATCH |
| BTC_USDT | min_price_change_pct | - | - | EXACT_MATCH |
| BTC_USDT | alert_cooldown_minutes | - | - | EXACT_MATCH |
| BTC_USDT | trade_amount_usd | - | - | EXACT_MATCH |
| BTC_USDT | alert_enabled | - | - | EXACT_MATCH |
| BTC_USDT | buy_alert_enabled | - | - | EXACT_MATCH |
| BTC_USDT | sell_alert_enabled | - | - | EXACT_MATCH |
| BTC_USDT | trade_enabled | - | 0 | EXACT_MATCH |
| BTC_USDT | trade_on_margin | - | 0 | EXACT_MATCH |
| BTC_USDT | sold | - | 0 | EXACT_MATCH |
| BTC_USDT | is_deleted | - | - | EXACT_MATCH |
| BTC_USDT | skip_sl_tp_reminder | - | - | EXACT_MATCH |
| BTC_USDT | sl_tp_mode | - | conservative | MISMATCH |
| BTC_USDT | order_status | - | PENDING | MISMATCH |
| BTC_USDT | exchange | - | CRYPTO_COM | MISMATCH |
| BTC_USDT | throttle_buy | - | - | BACKEND_ONLY |
| BTC_USDT | throttle_sell | - | - | BACKEND_ONLY |
| BTC_USDT | alert_enabled | - | - | MATCH |
| BTC_USDT | buy_alert_enabled | - | - | MATCH |
| BTC_USDT | sell_alert_enabled | - | - | MATCH |

| ETH_USDT | price | - | 3396.1700 | MISMATCH |
| ETH_USDT | rsi | - | 37.1600 | MISMATCH |
| ETH_USDT | ma50 | - | 3377.7300 | MISMATCH |
| ETH_USDT | ma200 | - | 3716.1600 | MISMATCH |
| ETH_USDT | ema10 | - | 3397.7200 | MISMATCH |
| ETH_USDT | atr | - | - | EXACT_MATCH |
| ETH_USDT | buy_target | - | - | EXACT_MATCH |
| ETH_USDT | take_profit | - | - | EXACT_MATCH |
| ETH_USDT | stop_loss | - | - | EXACT_MATCH |
| ETH_USDT | sl_price | - | - | EXACT_MATCH |
| ETH_USDT | tp_price | - | - | EXACT_MATCH |
| ETH_USDT | sl_percentage | - | - | EXACT_MATCH |
| ETH_USDT | tp_percentage | - | - | EXACT_MATCH |
| ETH_USDT | min_price_change_pct | - | - | EXACT_MATCH |
| ETH_USDT | alert_cooldown_minutes | - | - | EXACT_MATCH |
| ETH_USDT | trade_amount_usd | - | - | EXACT_MATCH |
| ETH_USDT | alert_enabled | - | - | EXACT_MATCH |
| ETH_USDT | buy_alert_enabled | - | - | EXACT_MATCH |
| ETH_USDT | sell_alert_enabled | - | - | EXACT_MATCH |
| ETH_USDT | trade_enabled | - | 0 | EXACT_MATCH |
| ETH_USDT | trade_on_margin | - | 0 | EXACT_MATCH |
| ETH_USDT | sold | - | 0 | EXACT_MATCH |
| ETH_USDT | is_deleted | - | - | EXACT_MATCH |
| ETH_USDT | skip_sl_tp_reminder | - | - | EXACT_MATCH |
| ETH_USDT | sl_tp_mode | - | conservative | MISMATCH |
| ETH_USDT | order_status | - | PENDING | MISMATCH |
| ETH_USDT | exchange | - | CRYPTO_COM | MISMATCH |
| ETH_USDT | throttle_buy | - | - | BACKEND_ONLY |
| ETH_USDT | throttle_sell | - | - | BACKEND_ONLY |
| ETH_USDT | alert_enabled | - | - | MATCH |
| ETH_USDT | buy_alert_enabled | - | - | MATCH |
| ETH_USDT | sell_alert_enabled | - | - | MATCH |

| SOL_USDT | price | - | 158.8100 | MISMATCH |
| SOL_USDT | rsi | - | 34.2300 | MISMATCH |
| SOL_USDT | ma50 | - | 158.8300 | MISMATCH |
| SOL_USDT | ma200 | - | 178.0200 | MISMATCH |
| SOL_USDT | ema10 | - | 159.6400 | MISMATCH |
| SOL_USDT | atr | - | - | EXACT_MATCH |
| SOL_USDT | buy_target | - | - | EXACT_MATCH |
| SOL_USDT | take_profit | - | - | EXACT_MATCH |
| SOL_USDT | stop_loss | - | - | EXACT_MATCH |
| SOL_USDT | sl_price | - | - | EXACT_MATCH |
| SOL_USDT | tp_price | - | - | EXACT_MATCH |
| SOL_USDT | sl_percentage | - | - | EXACT_MATCH |
| SOL_USDT | tp_percentage | - | - | EXACT_MATCH |
| SOL_USDT | min_price_change_pct | - | - | EXACT_MATCH |
| SOL_USDT | alert_cooldown_minutes | - | - | EXACT_MATCH |
| SOL_USDT | trade_amount_usd | - | - | EXACT_MATCH |
| SOL_USDT | alert_enabled | - | - | EXACT_MATCH |
| SOL_USDT | buy_alert_enabled | - | - | EXACT_MATCH |
| SOL_USDT | sell_alert_enabled | - | - | EXACT_MATCH |
| SOL_USDT | trade_enabled | - | 0 | EXACT_MATCH |
| SOL_USDT | trade_on_margin | - | 0 | EXACT_MATCH |
| SOL_USDT | sold | - | 0 | EXACT_MATCH |
| SOL_USDT | is_deleted | - | - | EXACT_MATCH |
| SOL_USDT | skip_sl_tp_reminder | - | - | EXACT_MATCH |
| SOL_USDT | sl_tp_mode | - | conservative | MISMATCH |
| SOL_USDT | order_status | - | PENDING | MISMATCH |
| SOL_USDT | exchange | - | CRYPTO_COM | MISMATCH |
| SOL_USDT | throttle_buy | - | - | BACKEND_ONLY |
| SOL_USDT | throttle_sell | - | - | BACKEND_ONLY |
| SOL_USDT | alert_enabled | - | - | MATCH |
| SOL_USDT | buy_alert_enabled | - | - | MATCH |
| SOL_USDT | sell_alert_enabled | - | - | MATCH |

| DOGE_USDT | price | - | 0.162844 | MISMATCH |
| DOGE_USDT | rsi | - | 42.4500 | MISMATCH |
| DOGE_USDT | ma50 | - | 0.146287 | MISMATCH |
| DOGE_USDT | ma200 | - | 0.156277 | MISMATCH |
| DOGE_USDT | ema10 | - | 0.138924 | MISMATCH |
| DOGE_USDT | atr | - | - | EXACT_MATCH |
| DOGE_USDT | buy_target | - | - | EXACT_MATCH |
| DOGE_USDT | take_profit | - | - | EXACT_MATCH |
| DOGE_USDT | stop_loss | - | - | EXACT_MATCH |
| DOGE_USDT | sl_price | - | - | EXACT_MATCH |
| DOGE_USDT | tp_price | - | - | EXACT_MATCH |
| DOGE_USDT | sl_percentage | - | - | EXACT_MATCH |
| DOGE_USDT | tp_percentage | - | - | EXACT_MATCH |
| DOGE_USDT | min_price_change_pct | - | - | EXACT_MATCH |
| DOGE_USDT | alert_cooldown_minutes | - | - | EXACT_MATCH |
| DOGE_USDT | trade_amount_usd | - | - | EXACT_MATCH |
| DOGE_USDT | alert_enabled | - | - | EXACT_MATCH |
| DOGE_USDT | buy_alert_enabled | - | - | EXACT_MATCH |
| DOGE_USDT | sell_alert_enabled | - | - | EXACT_MATCH |
| DOGE_USDT | trade_enabled | - | 0 | EXACT_MATCH |
| DOGE_USDT | trade_on_margin | - | 0 | EXACT_MATCH |
| DOGE_USDT | sold | - | 0 | EXACT_MATCH |
| DOGE_USDT | is_deleted | - | - | EXACT_MATCH |
| DOGE_USDT | skip_sl_tp_reminder | - | - | EXACT_MATCH |
| DOGE_USDT | sl_tp_mode | - | conservative | MISMATCH |
| DOGE_USDT | order_status | - | PENDING | MISMATCH |
| DOGE_USDT | exchange | - | CRYPTO_COM | MISMATCH |
| DOGE_USDT | throttle_buy | - | - | BACKEND_ONLY |
| DOGE_USDT | throttle_sell | - | - | BACKEND_ONLY |
| DOGE_USDT | alert_enabled | - | - | MATCH |
| DOGE_USDT | buy_alert_enabled | - | - | MATCH |
| DOGE_USDT | sell_alert_enabled | - | - | MATCH |

| ADA_USDT | price | - | 0.534540 | MISMATCH |
| ADA_USDT | rsi | - | 35.5200 | MISMATCH |
| ADA_USDT | ma50 | - | 0.540000 | MISMATCH |
| ADA_USDT | ma200 | - | 0.590000 | MISMATCH |
| ADA_USDT | ema10 | - | 0.540000 | MISMATCH |
| ADA_USDT | atr | - | - | EXACT_MATCH |
| ADA_USDT | buy_target | - | - | EXACT_MATCH |
| ADA_USDT | take_profit | - | - | EXACT_MATCH |
| ADA_USDT | stop_loss | - | - | EXACT_MATCH |
| ADA_USDT | sl_price | - | - | EXACT_MATCH |
| ADA_USDT | tp_price | - | - | EXACT_MATCH |
| ADA_USDT | sl_percentage | - | - | EXACT_MATCH |
| ADA_USDT | tp_percentage | - | - | EXACT_MATCH |
| ADA_USDT | min_price_change_pct | - | - | EXACT_MATCH |
| ADA_USDT | alert_cooldown_minutes | - | - | EXACT_MATCH |
| ADA_USDT | trade_amount_usd | - | - | EXACT_MATCH |
| ADA_USDT | alert_enabled | - | - | EXACT_MATCH |
| ADA_USDT | buy_alert_enabled | - | - | EXACT_MATCH |
| ADA_USDT | sell_alert_enabled | - | - | EXACT_MATCH |
| ADA_USDT | trade_enabled | - | 0 | EXACT_MATCH |
| ADA_USDT | trade_on_margin | - | 0 | EXACT_MATCH |
| ADA_USDT | sold | - | 0 | EXACT_MATCH |
| ADA_USDT | is_deleted | - | - | EXACT_MATCH |
| ADA_USDT | skip_sl_tp_reminder | - | - | EXACT_MATCH |
| ADA_USDT | sl_tp_mode | - | conservative | MISMATCH |
| ADA_USDT | order_status | - | PENDING | MISMATCH |
| ADA_USDT | exchange | - | CRYPTO_COM | MISMATCH |
| ADA_USDT | throttle_buy | - | - | BACKEND_ONLY |
| ADA_USDT | throttle_sell | - | - | BACKEND_ONLY |
| ADA_USDT | alert_enabled | - | - | MATCH |
| ADA_USDT | buy_alert_enabled | - | - | MATCH |
| ADA_USDT | sell_alert_enabled | - | - | MATCH |

| BNB_USDT | price | - | 815.2900 | MISMATCH |
| BNB_USDT | rsi | - | 50.0000 | MISMATCH |
| BNB_USDT | ma50 | - | 815.2900 | MISMATCH |
| BNB_USDT | ma200 | - | 815.2900 | MISMATCH |
| BNB_USDT | ema10 | - | 815.2900 | MISMATCH |
| BNB_USDT | atr | - | - | EXACT_MATCH |
| BNB_USDT | buy_target | - | - | EXACT_MATCH |
| BNB_USDT | take_profit | - | - | EXACT_MATCH |
| BNB_USDT | stop_loss | - | - | EXACT_MATCH |
| BNB_USDT | sl_price | - | - | EXACT_MATCH |
| BNB_USDT | tp_price | - | - | EXACT_MATCH |
| BNB_USDT | sl_percentage | - | - | EXACT_MATCH |
| BNB_USDT | tp_percentage | - | - | EXACT_MATCH |
| BNB_USDT | min_price_change_pct | - | - | EXACT_MATCH |
| BNB_USDT | alert_cooldown_minutes | - | - | EXACT_MATCH |
| BNB_USDT | trade_amount_usd | - | - | EXACT_MATCH |
| BNB_USDT | alert_enabled | - | - | EXACT_MATCH |
| BNB_USDT | buy_alert_enabled | - | - | EXACT_MATCH |
| BNB_USDT | sell_alert_enabled | - | - | EXACT_MATCH |
| BNB_USDT | trade_enabled | - | 0 | EXACT_MATCH |
| BNB_USDT | trade_on_margin | - | 0 | EXACT_MATCH |
| BNB_USDT | sold | - | 0 | EXACT_MATCH |
| BNB_USDT | is_deleted | - | - | EXACT_MATCH |
| BNB_USDT | skip_sl_tp_reminder | - | - | EXACT_MATCH |
| BNB_USDT | sl_tp_mode | - | conservative | MISMATCH |
| BNB_USDT | order_status | - | PENDING | MISMATCH |
| BNB_USDT | exchange | - | CRYPTO_COM | MISMATCH |
| BNB_USDT | throttle_buy | - | - | BACKEND_ONLY |
| BNB_USDT | throttle_sell | - | - | BACKEND_ONLY |
| BNB_USDT | alert_enabled | - | - | MATCH |
| BNB_USDT | buy_alert_enabled | - | - | MATCH |
| BNB_USDT | sell_alert_enabled | - | - | MATCH |

| XRP_USDT | price | - | 2.2931 | MISMATCH |
| XRP_USDT | rsi | - | 38.2300 | MISMATCH |
| XRP_USDT | ma50 | - | 2.2700 | MISMATCH |
| XRP_USDT | ma200 | - | 2.4300 | MISMATCH |
| XRP_USDT | ema10 | - | 2.3200 | MISMATCH |
| XRP_USDT | atr | - | - | EXACT_MATCH |
| XRP_USDT | buy_target | - | - | EXACT_MATCH |
| XRP_USDT | take_profit | - | - | EXACT_MATCH |
| XRP_USDT | stop_loss | - | - | EXACT_MATCH |
| XRP_USDT | sl_price | - | - | EXACT_MATCH |
| XRP_USDT | tp_price | - | - | EXACT_MATCH |
| XRP_USDT | sl_percentage | - | - | EXACT_MATCH |
| XRP_USDT | tp_percentage | - | - | EXACT_MATCH |
| XRP_USDT | min_price_change_pct | - | - | EXACT_MATCH |
| XRP_USDT | alert_cooldown_minutes | - | - | EXACT_MATCH |
| XRP_USDT | trade_amount_usd | - | - | EXACT_MATCH |
| XRP_USDT | alert_enabled | - | - | EXACT_MATCH |
| XRP_USDT | buy_alert_enabled | - | - | EXACT_MATCH |
| XRP_USDT | sell_alert_enabled | - | - | EXACT_MATCH |
| XRP_USDT | trade_enabled | - | 0 | EXACT_MATCH |
| XRP_USDT | trade_on_margin | - | 0 | EXACT_MATCH |
| XRP_USDT | sold | - | 0 | EXACT_MATCH |
| XRP_USDT | is_deleted | - | - | EXACT_MATCH |
| XRP_USDT | skip_sl_tp_reminder | - | - | EXACT_MATCH |
| XRP_USDT | sl_tp_mode | - | conservative | MISMATCH |
| XRP_USDT | order_status | - | PENDING | MISMATCH |
| XRP_USDT | exchange | - | CRYPTO_COM | MISMATCH |
| XRP_USDT | throttle_buy | - | - | BACKEND_ONLY |
| XRP_USDT | throttle_sell | - | - | BACKEND_ONLY |
| XRP_USDT | alert_enabled | - | - | MATCH |
| XRP_USDT | buy_alert_enabled | - | - | MATCH |
| XRP_USDT | sell_alert_enabled | - | - | MATCH |

| MATIC_USDT | price | - | 0.130488 | MISMATCH |
| MATIC_USDT | rsi | - | 50.0000 | MISMATCH |
| MATIC_USDT | ma50 | - | 0.130488 | MISMATCH |
| MATIC_USDT | ma200 | - | 0.130488 | MISMATCH |
| MATIC_USDT | ema10 | - | 0.130488 | MISMATCH |
| MATIC_USDT | atr | - | - | EXACT_MATCH |
| MATIC_USDT | buy_target | - | - | EXACT_MATCH |
| MATIC_USDT | take_profit | - | - | EXACT_MATCH |
| MATIC_USDT | stop_loss | - | - | EXACT_MATCH |
| MATIC_USDT | sl_price | - | - | EXACT_MATCH |
| MATIC_USDT | tp_price | - | - | EXACT_MATCH |
| MATIC_USDT | sl_percentage | - | - | EXACT_MATCH |
| MATIC_USDT | tp_percentage | - | - | EXACT_MATCH |
| MATIC_USDT | min_price_change_pct | - | - | EXACT_MATCH |
| MATIC_USDT | alert_cooldown_minutes | - | - | EXACT_MATCH |
| MATIC_USDT | trade_amount_usd | - | - | EXACT_MATCH |
| MATIC_USDT | alert_enabled | - | - | EXACT_MATCH |
| MATIC_USDT | buy_alert_enabled | - | - | EXACT_MATCH |
| MATIC_USDT | sell_alert_enabled | - | - | EXACT_MATCH |
| MATIC_USDT | trade_enabled | - | 0 | EXACT_MATCH |
| MATIC_USDT | trade_on_margin | - | 0 | EXACT_MATCH |
| MATIC_USDT | sold | - | 0 | EXACT_MATCH |
| MATIC_USDT | is_deleted | - | - | EXACT_MATCH |
| MATIC_USDT | skip_sl_tp_reminder | - | - | EXACT_MATCH |
| MATIC_USDT | sl_tp_mode | - | conservative | MISMATCH |
| MATIC_USDT | order_status | - | PENDING | MISMATCH |
| MATIC_USDT | exchange | - | CRYPTO_COM | MISMATCH |
| MATIC_USDT | throttle_buy | - | - | BACKEND_ONLY |
| MATIC_USDT | throttle_sell | - | - | BACKEND_ONLY |
| MATIC_USDT | alert_enabled | - | - | MATCH |
| MATIC_USDT | buy_alert_enabled | - | - | MATCH |
| MATIC_USDT | sell_alert_enabled | - | - | MATCH |

| AVAX_USDT | price | - | 16.2980 | MISMATCH |
| AVAX_USDT | rsi | - | 31.0700 | MISMATCH |
| AVAX_USDT | ma50 | - | 16.4100 | MISMATCH |
| AVAX_USDT | ma200 | - | 17.8900 | MISMATCH |
| AVAX_USDT | ema10 | - | 16.3900 | MISMATCH |
| AVAX_USDT | atr | - | - | EXACT_MATCH |
| AVAX_USDT | buy_target | - | - | EXACT_MATCH |
| AVAX_USDT | take_profit | - | - | EXACT_MATCH |
| AVAX_USDT | stop_loss | - | - | EXACT_MATCH |
| AVAX_USDT | sl_price | - | - | EXACT_MATCH |
| AVAX_USDT | tp_price | - | - | EXACT_MATCH |
| AVAX_USDT | sl_percentage | - | - | EXACT_MATCH |
| AVAX_USDT | tp_percentage | - | - | EXACT_MATCH |
| AVAX_USDT | min_price_change_pct | - | - | EXACT_MATCH |
| AVAX_USDT | alert_cooldown_minutes | - | - | EXACT_MATCH |
| AVAX_USDT | trade_amount_usd | - | - | EXACT_MATCH |
| AVAX_USDT | alert_enabled | - | - | EXACT_MATCH |
| AVAX_USDT | buy_alert_enabled | - | - | EXACT_MATCH |
| AVAX_USDT | sell_alert_enabled | - | - | EXACT_MATCH |
| AVAX_USDT | trade_enabled | - | 0 | EXACT_MATCH |
| AVAX_USDT | trade_on_margin | - | 0 | EXACT_MATCH |
| AVAX_USDT | sold | - | 0 | EXACT_MATCH |
| AVAX_USDT | is_deleted | - | - | EXACT_MATCH |
| AVAX_USDT | skip_sl_tp_reminder | - | - | EXACT_MATCH |
| AVAX_USDT | sl_tp_mode | - | conservative | MISMATCH |
| AVAX_USDT | order_status | - | PENDING | MISMATCH |
| AVAX_USDT | exchange | - | CRYPTO_COM | MISMATCH |
| AVAX_USDT | throttle_buy | - | - | BACKEND_ONLY |
| AVAX_USDT | throttle_sell | - | - | BACKEND_ONLY |
| AVAX_USDT | alert_enabled | - | - | MATCH |
| AVAX_USDT | buy_alert_enabled | - | - | MATCH |
| AVAX_USDT | sell_alert_enabled | - | - | MATCH |

| DOT_USDT | price | - | 2.6074 | MISMATCH |
| DOT_USDT | rsi | - | 33.9400 | MISMATCH |
| DOT_USDT | ma50 | - | 2.5900 | MISMATCH |
| DOT_USDT | ma200 | - | 2.8200 | MISMATCH |
| DOT_USDT | ema10 | - | 2.6200 | MISMATCH |
| DOT_USDT | atr | - | - | EXACT_MATCH |
| DOT_USDT | buy_target | - | - | EXACT_MATCH |
| DOT_USDT | take_profit | - | - | EXACT_MATCH |
| DOT_USDT | stop_loss | - | - | EXACT_MATCH |
| DOT_USDT | sl_price | - | - | EXACT_MATCH |
| DOT_USDT | tp_price | - | - | EXACT_MATCH |
| DOT_USDT | sl_percentage | - | - | EXACT_MATCH |
| DOT_USDT | tp_percentage | - | - | EXACT_MATCH |
| DOT_USDT | min_price_change_pct | - | - | EXACT_MATCH |
| DOT_USDT | alert_cooldown_minutes | - | - | EXACT_MATCH |
| DOT_USDT | trade_amount_usd | - | - | EXACT_MATCH |
| DOT_USDT | alert_enabled | - | - | EXACT_MATCH |
| DOT_USDT | buy_alert_enabled | - | - | EXACT_MATCH |
| DOT_USDT | sell_alert_enabled | - | - | EXACT_MATCH |
| DOT_USDT | trade_enabled | - | 0 | EXACT_MATCH |
| DOT_USDT | trade_on_margin | - | 0 | EXACT_MATCH |
| DOT_USDT | sold | - | 0 | EXACT_MATCH |
| DOT_USDT | is_deleted | - | - | EXACT_MATCH |
| DOT_USDT | skip_sl_tp_reminder | - | - | EXACT_MATCH |
| DOT_USDT | sl_tp_mode | - | conservative | MISMATCH |
| DOT_USDT | order_status | - | PENDING | MISMATCH |
| DOT_USDT | exchange | - | CRYPTO_COM | MISMATCH |
| DOT_USDT | alert_enabled | - | - | MATCH |
| DOT_USDT | buy_alert_enabled | - | - | MATCH |
| DOT_USDT | sell_alert_enabled | - | - | MATCH |

| LINK_USDT | price | - | 11.8240 | MISMATCH |
| LINK_USDT | rsi | - | 36.6100 | MISMATCH |
| LINK_USDT | ma50 | - | 12.6400 | MISMATCH |
| LINK_USDT | ma200 | - | 13.5300 | MISMATCH |
| LINK_USDT | ema10 | - | 12.0100 | MISMATCH |
| LINK_USDT | atr | - | - | EXACT_MATCH |
| LINK_USDT | buy_target | - | - | EXACT_MATCH |
| LINK_USDT | take_profit | - | - | EXACT_MATCH |
| LINK_USDT | stop_loss | - | - | EXACT_MATCH |
| LINK_USDT | sl_price | - | - | EXACT_MATCH |
| LINK_USDT | tp_price | - | - | EXACT_MATCH |
| LINK_USDT | sl_percentage | - | - | EXACT_MATCH |
| LINK_USDT | tp_percentage | - | - | EXACT_MATCH |
| LINK_USDT | min_price_change_pct | - | - | EXACT_MATCH |
| LINK_USDT | alert_cooldown_minutes | - | - | EXACT_MATCH |
| LINK_USDT | trade_amount_usd | - | - | EXACT_MATCH |
| LINK_USDT | alert_enabled | - | - | EXACT_MATCH |
| LINK_USDT | buy_alert_enabled | - | - | EXACT_MATCH |
| LINK_USDT | sell_alert_enabled | - | - | EXACT_MATCH |
| LINK_USDT | trade_enabled | - | 0 | EXACT_MATCH |
| LINK_USDT | trade_on_margin | - | 0 | EXACT_MATCH |
| LINK_USDT | sold | - | 0 | EXACT_MATCH |
| LINK_USDT | is_deleted | - | - | EXACT_MATCH |
| LINK_USDT | skip_sl_tp_reminder | - | - | EXACT_MATCH |
| LINK_USDT | sl_tp_mode | - | conservative | MISMATCH |
| LINK_USDT | order_status | - | PENDING | MISMATCH |
| LINK_USDT | exchange | - | CRYPTO_COM | MISMATCH |
| LINK_USDT | alert_enabled | - | - | MATCH |
| LINK_USDT | buy_alert_enabled | - | - | MATCH |
| LINK_USDT | sell_alert_enabled | - | - | MATCH |

| UNI_USDT | price | - | 6.2154 | MISMATCH |
| UNI_USDT | rsi | - | 39.8300 | MISMATCH |
| UNI_USDT | ma50 | - | 6.5900 | MISMATCH |
| UNI_USDT | ma200 | - | 7.1800 | MISMATCH |
| UNI_USDT | ema10 | - | 6.3800 | MISMATCH |
| UNI_USDT | atr | - | - | EXACT_MATCH |
| UNI_USDT | buy_target | - | - | EXACT_MATCH |
| UNI_USDT | take_profit | - | - | EXACT_MATCH |
| UNI_USDT | stop_loss | - | - | EXACT_MATCH |
| UNI_USDT | sl_price | - | - | EXACT_MATCH |
| UNI_USDT | tp_price | - | - | EXACT_MATCH |
| UNI_USDT | sl_percentage | - | - | EXACT_MATCH |
| UNI_USDT | tp_percentage | - | - | EXACT_MATCH |
| UNI_USDT | min_price_change_pct | - | - | EXACT_MATCH |
| UNI_USDT | alert_cooldown_minutes | - | - | EXACT_MATCH |
| UNI_USDT | trade_amount_usd | - | - | EXACT_MATCH |
| UNI_USDT | alert_enabled | - | - | EXACT_MATCH |
| UNI_USDT | buy_alert_enabled | - | - | EXACT_MATCH |
| UNI_USDT | sell_alert_enabled | - | - | EXACT_MATCH |
| UNI_USDT | trade_enabled | - | 0 | EXACT_MATCH |
| UNI_USDT | trade_on_margin | - | 0 | EXACT_MATCH |
| UNI_USDT | sold | - | 0 | EXACT_MATCH |
| UNI_USDT | is_deleted | - | - | EXACT_MATCH |
| UNI_USDT | skip_sl_tp_reminder | - | - | EXACT_MATCH |
| UNI_USDT | sl_tp_mode | - | conservative | MISMATCH |
| UNI_USDT | order_status | - | PENDING | MISMATCH |
| UNI_USDT | exchange | - | CRYPTO_COM | MISMATCH |
| UNI_USDT | throttle_buy | - | - | BACKEND_ONLY |
| UNI_USDT | throttle_sell | - | - | BACKEND_ONLY |
| UNI_USDT | alert_enabled | - | - | MATCH |
| UNI_USDT | buy_alert_enabled | - | - | MATCH |
| UNI_USDT | sell_alert_enabled | - | - | MATCH |

| ATOM_USDT | price | - | 2.4590 | MISMATCH |
| ATOM_USDT | rsi | - | 33.3300 | MISMATCH |
| ATOM_USDT | ma50 | - | 2.7000 | MISMATCH |
| ATOM_USDT | ma200 | - | 2.7800 | MISMATCH |
| ATOM_USDT | ema10 | - | 2.4900 | MISMATCH |
| ATOM_USDT | atr | - | - | EXACT_MATCH |
| ATOM_USDT | buy_target | - | - | EXACT_MATCH |
| ATOM_USDT | take_profit | - | - | EXACT_MATCH |
| ATOM_USDT | stop_loss | - | - | EXACT_MATCH |
| ATOM_USDT | sl_price | - | - | EXACT_MATCH |
| ATOM_USDT | tp_price | - | - | EXACT_MATCH |
| ATOM_USDT | sl_percentage | - | - | EXACT_MATCH |
| ATOM_USDT | tp_percentage | - | - | EXACT_MATCH |
| ATOM_USDT | min_price_change_pct | - | - | EXACT_MATCH |
| ATOM_USDT | alert_cooldown_minutes | - | - | EXACT_MATCH |
| ATOM_USDT | trade_amount_usd | - | - | EXACT_MATCH |
| ATOM_USDT | alert_enabled | - | - | EXACT_MATCH |
| ATOM_USDT | buy_alert_enabled | - | - | EXACT_MATCH |
| ATOM_USDT | sell_alert_enabled | - | - | EXACT_MATCH |
| ATOM_USDT | trade_enabled | - | 0 | EXACT_MATCH |
| ATOM_USDT | trade_on_margin | - | 0 | EXACT_MATCH |
| ATOM_USDT | sold | - | 0 | EXACT_MATCH |
| ATOM_USDT | is_deleted | - | - | EXACT_MATCH |
| ATOM_USDT | skip_sl_tp_reminder | - | - | EXACT_MATCH |
| ATOM_USDT | sl_tp_mode | - | conservative | MISMATCH |
| ATOM_USDT | order_status | - | PENDING | MISMATCH |
| ATOM_USDT | exchange | - | CRYPTO_COM | MISMATCH |
| ATOM_USDT | throttle_buy | - | - | BACKEND_ONLY |
| ATOM_USDT | throttle_sell | - | - | BACKEND_ONLY |
| ATOM_USDT | alert_enabled | - | - | MATCH |
| ATOM_USDT | buy_alert_enabled | - | - | MATCH |
| ATOM_USDT | sell_alert_enabled | - | - | MATCH |

| ALGO_USDT | price | - | 0.134750 | MISMATCH |
| ALGO_USDT | rsi | - | 38.7400 | MISMATCH |
| ALGO_USDT | ma50 | - | 0.140000 | MISMATCH |
| ALGO_USDT | ma200 | - | 0.150000 | MISMATCH |
| ALGO_USDT | ema10 | - | 0.140000 | MISMATCH |
| ALGO_USDT | atr | - | - | EXACT_MATCH |
| ALGO_USDT | buy_target | - | - | EXACT_MATCH |
| ALGO_USDT | take_profit | - | - | EXACT_MATCH |
| ALGO_USDT | stop_loss | - | - | EXACT_MATCH |
| ALGO_USDT | sl_price | - | - | EXACT_MATCH |
| ALGO_USDT | tp_price | - | - | EXACT_MATCH |
| ALGO_USDT | sl_percentage | - | - | EXACT_MATCH |
| ALGO_USDT | tp_percentage | - | - | EXACT_MATCH |
| ALGO_USDT | min_price_change_pct | - | - | EXACT_MATCH |
| ALGO_USDT | alert_cooldown_minutes | - | - | EXACT_MATCH |
| ALGO_USDT | trade_amount_usd | - | - | EXACT_MATCH |
| ALGO_USDT | alert_enabled | - | - | EXACT_MATCH |
| ALGO_USDT | buy_alert_enabled | - | - | EXACT_MATCH |
| ALGO_USDT | sell_alert_enabled | - | - | EXACT_MATCH |
| ALGO_USDT | trade_enabled | - | 0 | EXACT_MATCH |
| ALGO_USDT | trade_on_margin | - | 0 | EXACT_MATCH |
| ALGO_USDT | sold | - | 0 | EXACT_MATCH |
| ALGO_USDT | is_deleted | - | - | EXACT_MATCH |
| ALGO_USDT | skip_sl_tp_reminder | - | - | EXACT_MATCH |
| ALGO_USDT | sl_tp_mode | - | conservative | MISMATCH |
| ALGO_USDT | order_status | - | PENDING | MISMATCH |
| ALGO_USDT | exchange | - | CRYPTO_COM | MISMATCH |
| ALGO_USDT | alert_enabled | - | - | MATCH |
| ALGO_USDT | buy_alert_enabled | - | - | MATCH |
| ALGO_USDT | sell_alert_enabled | - | - | MATCH |

| NEAR_USDT | price | - | 1.8214 | MISMATCH |
| NEAR_USDT | rsi | - | 36.1000 | MISMATCH |
| NEAR_USDT | ma50 | - | 2.0300 | MISMATCH |
| NEAR_USDT | ma200 | - | 2.2700 | MISMATCH |
| NEAR_USDT | ema10 | - | 1.8600 | MISMATCH |
| NEAR_USDT | atr | - | - | EXACT_MATCH |
| NEAR_USDT | buy_target | - | - | EXACT_MATCH |
| NEAR_USDT | take_profit | - | - | EXACT_MATCH |
| NEAR_USDT | stop_loss | - | - | EXACT_MATCH |
| NEAR_USDT | sl_price | - | - | EXACT_MATCH |
| NEAR_USDT | tp_price | - | - | EXACT_MATCH |
| NEAR_USDT | sl_percentage | - | - | EXACT_MATCH |
| NEAR_USDT | tp_percentage | - | - | EXACT_MATCH |
| NEAR_USDT | min_price_change_pct | - | - | EXACT_MATCH |
| NEAR_USDT | alert_cooldown_minutes | - | - | EXACT_MATCH |
| NEAR_USDT | trade_amount_usd | - | - | EXACT_MATCH |
| NEAR_USDT | alert_enabled | - | - | EXACT_MATCH |
| NEAR_USDT | buy_alert_enabled | - | - | EXACT_MATCH |
| NEAR_USDT | sell_alert_enabled | - | - | EXACT_MATCH |
| NEAR_USDT | trade_enabled | - | 0 | EXACT_MATCH |
| NEAR_USDT | trade_on_margin | - | 0 | EXACT_MATCH |
| NEAR_USDT | sold | - | 0 | EXACT_MATCH |
| NEAR_USDT | is_deleted | - | - | EXACT_MATCH |
| NEAR_USDT | skip_sl_tp_reminder | - | - | EXACT_MATCH |
| NEAR_USDT | sl_tp_mode | - | conservative | MISMATCH |
| NEAR_USDT | order_status | - | PENDING | MISMATCH |
| NEAR_USDT | exchange | - | CRYPTO_COM | MISMATCH |
| NEAR_USDT | throttle_buy | - | - | BACKEND_ONLY |
| NEAR_USDT | throttle_sell | - | - | BACKEND_ONLY |
| NEAR_USDT | alert_enabled | - | - | MATCH |
| NEAR_USDT | buy_alert_enabled | - | - | MATCH |
| NEAR_USDT | sell_alert_enabled | - | - | MATCH |

| ICP_USDT | price | - | 4.1124 | MISMATCH |
| ICP_USDT | rsi | - | 31.4000 | MISMATCH |
| ICP_USDT | ma50 | - | 4.5300 | MISMATCH |
| ICP_USDT | ma200 | - | 5.0800 | MISMATCH |
| ICP_USDT | ema10 | - | 4.2100 | MISMATCH |
| ICP_USDT | atr | - | - | EXACT_MATCH |
| ICP_USDT | buy_target | - | - | EXACT_MATCH |
| ICP_USDT | take_profit | - | - | EXACT_MATCH |
| ICP_USDT | stop_loss | - | - | EXACT_MATCH |
| ICP_USDT | sl_price | - | - | EXACT_MATCH |
| ICP_USDT | tp_price | - | - | EXACT_MATCH |
| ICP_USDT | sl_percentage | - | - | EXACT_MATCH |
| ICP_USDT | tp_percentage | - | - | EXACT_MATCH |
| ICP_USDT | min_price_change_pct | - | - | EXACT_MATCH |
| ICP_USDT | alert_cooldown_minutes | - | - | EXACT_MATCH |
| ICP_USDT | trade_amount_usd | - | - | EXACT_MATCH |
| ICP_USDT | alert_enabled | - | - | EXACT_MATCH |
| ICP_USDT | buy_alert_enabled | - | - | EXACT_MATCH |
| ICP_USDT | sell_alert_enabled | - | - | EXACT_MATCH |
| ICP_USDT | trade_enabled | - | 0 | EXACT_MATCH |
| ICP_USDT | trade_on_margin | - | 0 | EXACT_MATCH |
| ICP_USDT | sold | - | 0 | EXACT_MATCH |
| ICP_USDT | is_deleted | - | - | EXACT_MATCH |
| ICP_USDT | skip_sl_tp_reminder | - | - | EXACT_MATCH |
| ICP_USDT | sl_tp_mode | - | conservative | MISMATCH |
| ICP_USDT | order_status | - | PENDING | MISMATCH |
| ICP_USDT | exchange | - | CRYPTO_COM | MISMATCH |
| ICP_USDT | throttle_buy | - | - | BACKEND_ONLY |
| ICP_USDT | throttle_sell | - | - | BACKEND_ONLY |
| ICP_USDT | alert_enabled | - | - | MATCH |
| ICP_USDT | buy_alert_enabled | - | - | MATCH |
| ICP_USDT | sell_alert_enabled | - | - | MATCH |

| FIL_USDT | price | - | 1.6114 | MISMATCH |
| FIL_USDT | rsi | - | 33.7500 | MISMATCH |
| FIL_USDT | ma50 | - | 1.7300 | MISMATCH |
| FIL_USDT | ma200 | - | 1.9300 | MISMATCH |
| FIL_USDT | ema10 | - | 1.6400 | MISMATCH |
| FIL_USDT | atr | - | - | EXACT_MATCH |
| FIL_USDT | buy_target | - | - | EXACT_MATCH |
| FIL_USDT | take_profit | - | - | EXACT_MATCH |
| FIL_USDT | stop_loss | - | - | EXACT_MATCH |
| FIL_USDT | sl_price | - | - | EXACT_MATCH |
| FIL_USDT | tp_price | - | - | EXACT_MATCH |
| FIL_USDT | sl_percentage | - | - | EXACT_MATCH |
| FIL_USDT | tp_percentage | - | - | EXACT_MATCH |
| FIL_USDT | min_price_change_pct | - | - | EXACT_MATCH |
| FIL_USDT | alert_cooldown_minutes | - | - | EXACT_MATCH |
| FIL_USDT | trade_amount_usd | - | - | EXACT_MATCH |
| FIL_USDT | alert_enabled | - | - | EXACT_MATCH |
| FIL_USDT | buy_alert_enabled | - | - | EXACT_MATCH |
| FIL_USDT | sell_alert_enabled | - | - | EXACT_MATCH |
| FIL_USDT | trade_enabled | - | 0 | EXACT_MATCH |
| FIL_USDT | trade_on_margin | - | 0 | EXACT_MATCH |
| FIL_USDT | sold | - | 0 | EXACT_MATCH |
| FIL_USDT | is_deleted | - | - | EXACT_MATCH |
| FIL_USDT | skip_sl_tp_reminder | - | - | EXACT_MATCH |
| FIL_USDT | sl_tp_mode | - | conservative | MISMATCH |
| FIL_USDT | order_status | - | PENDING | MISMATCH |
| FIL_USDT | exchange | - | CRYPTO_COM | MISMATCH |
| FIL_USDT | throttle_buy | - | - | BACKEND_ONLY |
| FIL_USDT | throttle_sell | - | - | BACKEND_ONLY |
| FIL_USDT | alert_enabled | - | - | MATCH |
| FIL_USDT | buy_alert_enabled | - | - | MATCH |
| FIL_USDT | sell_alert_enabled | - | - | MATCH |

| APT_USDT | price | - | 2.3165 | MISMATCH |
| APT_USDT | rsi | - | 27.8300 | MISMATCH |
| APT_USDT | ma50 | - | 2.6400 | MISMATCH |
| APT_USDT | ma200 | - | 2.8300 | MISMATCH |
| APT_USDT | ema10 | - | 2.3600 | MISMATCH |
| APT_USDT | atr | - | - | EXACT_MATCH |
| APT_USDT | buy_target | - | - | EXACT_MATCH |
| APT_USDT | take_profit | - | - | EXACT_MATCH |
| APT_USDT | stop_loss | - | - | EXACT_MATCH |
| APT_USDT | sl_price | - | - | EXACT_MATCH |
| APT_USDT | tp_price | - | - | EXACT_MATCH |
| APT_USDT | sl_percentage | - | - | EXACT_MATCH |
| APT_USDT | tp_percentage | - | - | EXACT_MATCH |
| APT_USDT | min_price_change_pct | - | - | EXACT_MATCH |
| APT_USDT | alert_cooldown_minutes | - | - | EXACT_MATCH |
| APT_USDT | trade_amount_usd | - | - | EXACT_MATCH |
| APT_USDT | alert_enabled | - | - | EXACT_MATCH |
| APT_USDT | buy_alert_enabled | - | - | EXACT_MATCH |
| APT_USDT | sell_alert_enabled | - | - | EXACT_MATCH |
| APT_USDT | trade_enabled | - | 0 | EXACT_MATCH |
| APT_USDT | trade_on_margin | - | 0 | EXACT_MATCH |
| APT_USDT | sold | - | 0 | EXACT_MATCH |
| APT_USDT | is_deleted | - | - | EXACT_MATCH |
| APT_USDT | skip_sl_tp_reminder | - | - | EXACT_MATCH |
| APT_USDT | sl_tp_mode | - | conservative | MISMATCH |
| APT_USDT | order_status | - | PENDING | MISMATCH |
| APT_USDT | exchange | - | CRYPTO_COM | MISMATCH |
| APT_USDT | throttle_buy | - | - | BACKEND_ONLY |
| APT_USDT | throttle_sell | - | - | BACKEND_ONLY |
| APT_USDT | alert_enabled | - | - | MATCH |
| APT_USDT | buy_alert_enabled | - | - | MATCH |
| APT_USDT | sell_alert_enabled | - | - | MATCH |

| BTC_USD | price | - | 84110.0000 | MISMATCH |
| BTC_USD | rsi | - | 45.9300 | MISMATCH |
| BTC_USD | ma50 | - | 86269.4000 | MISMATCH |
| BTC_USD | ma200 | - | 92099.5500 | MISMATCH |
| BTC_USD | ema10 | - | 84467.8200 | MISMATCH |
| BTC_USD | atr | - | - | EXACT_MATCH |
| BTC_USD | buy_target | - | - | EXACT_MATCH |
| BTC_USD | take_profit | - | - | EXACT_MATCH |
| BTC_USD | stop_loss | - | - | EXACT_MATCH |
| BTC_USD | sl_price | - | - | EXACT_MATCH |
| BTC_USD | tp_price | - | - | EXACT_MATCH |
| BTC_USD | sl_percentage | - | - | EXACT_MATCH |
| BTC_USD | tp_percentage | - | - | EXACT_MATCH |
| BTC_USD | min_price_change_pct | - | - | EXACT_MATCH |
| BTC_USD | alert_cooldown_minutes | - | - | EXACT_MATCH |
| BTC_USD | trade_amount_usd | - | - | EXACT_MATCH |
| BTC_USD | alert_enabled | - | - | EXACT_MATCH |
| BTC_USD | buy_alert_enabled | - | - | EXACT_MATCH |
| BTC_USD | sell_alert_enabled | - | - | EXACT_MATCH |
| BTC_USD | trade_enabled | - | 1 | MISMATCH |
| BTC_USD | trade_on_margin | - | 0 | EXACT_MATCH |
| BTC_USD | sold | - | 0 | EXACT_MATCH |
| BTC_USD | is_deleted | - | - | EXACT_MATCH |
| BTC_USD | skip_sl_tp_reminder | - | - | EXACT_MATCH |
| BTC_USD | sl_tp_mode | - | conservative | MISMATCH |
| BTC_USD | order_status | - | PENDING | MISMATCH |
| BTC_USD | exchange | - | CRYPTO_COM | MISMATCH |
| BTC_USD | alert_enabled | - | - | MATCH |
| BTC_USD | buy_alert_enabled | - | - | MATCH |
| BTC_USD | sell_alert_enabled | - | - | MATCH |

| BONK_USD | price | - | 0.000010 | MISMATCH |
| BONK_USD | rsi | - | 32.1000 | MISMATCH |
| BONK_USD | ma50 | - | 0.000009 | MISMATCH |
| BONK_USD | ma200 | - | 0.000010 | MISMATCH |
| BONK_USD | ema10 | - | 0.000009 | MISMATCH |
| BONK_USD | atr | - | - | EXACT_MATCH |
| BONK_USD | buy_target | - | - | EXACT_MATCH |
| BONK_USD | take_profit | - | - | EXACT_MATCH |
| BONK_USD | stop_loss | - | - | EXACT_MATCH |
| BONK_USD | sl_price | - | - | EXACT_MATCH |
| BONK_USD | tp_price | - | - | EXACT_MATCH |
| BONK_USD | sl_percentage | - | - | EXACT_MATCH |
| BONK_USD | tp_percentage | - | - | EXACT_MATCH |
| BONK_USD | min_price_change_pct | - | - | EXACT_MATCH |
| BONK_USD | alert_cooldown_minutes | - | - | EXACT_MATCH |
| BONK_USD | trade_amount_usd | - | - | EXACT_MATCH |
| BONK_USD | alert_enabled | - | - | EXACT_MATCH |
| BONK_USD | buy_alert_enabled | - | - | EXACT_MATCH |
| BONK_USD | sell_alert_enabled | - | - | EXACT_MATCH |
| BONK_USD | trade_enabled | - | - | EXACT_MATCH |
| BONK_USD | trade_on_margin | - | - | EXACT_MATCH |
| BONK_USD | sold | - | - | EXACT_MATCH |
| BONK_USD | is_deleted | - | - | EXACT_MATCH |
| BONK_USD | skip_sl_tp_reminder | - | - | EXACT_MATCH |
| BONK_USD | sl_tp_mode | - | - | EXACT_MATCH |
| BONK_USD | order_status | - | - | EXACT_MATCH |
| BONK_USD | exchange | - | CRYPTO_COM | MISMATCH |
| BONK_USD | throttle_buy | - | - | BACKEND_ONLY |
| BONK_USD | throttle_sell | - | - | BACKEND_ONLY |
| BONK_USD | alert_enabled | - | - | MATCH |
| BONK_USD | buy_alert_enabled | - | - | MATCH |
| BONK_USD | sell_alert_enabled | - | - | MATCH |


## Detailed Results (Expanded)

### BTC_USDT

**Status:** HAS_ISSUES

**Backend Query Time:** 0.007s

| Field | DB | API | Computed | Classification |
|-------|----|-----|----------|----------------|
| price | None | None | 103069.2000 | MISMATCH |
| rsi | None | None | 41.3400 | MISMATCH |
| ma50 | None | None | 102742.1300 | MISMATCH |
| ma200 | None | None | 107787.9700 | MISMATCH |
| ema10 | None | None | 103230.2800 | MISMATCH |
| atr | None | None | None | EXACT_MATCH |
| buy_target | None | None | None | EXACT_MATCH |
| take_profit | None | None | None | EXACT_MATCH |
| stop_loss | None | None | None | EXACT_MATCH |
| sl_price | None | None | None | EXACT_MATCH |
| tp_price | None | None | None | EXACT_MATCH |
| sl_percentage | None | None | None | EXACT_MATCH |
| tp_percentage | None | None | None | EXACT_MATCH |
| min_price_change_pct | None | None | None | EXACT_MATCH |
| alert_cooldown_minutes | None | None | None | EXACT_MATCH |
| trade_amount_usd | None | None | None | EXACT_MATCH |
| alert_enabled | None | None | None | EXACT_MATCH |
| buy_alert_enabled | None | None | None | EXACT_MATCH |
| sell_alert_enabled | None | None | None | EXACT_MATCH |
| trade_enabled | 0 | None | None | EXACT_MATCH |
| trade_on_margin | 0 | None | None | EXACT_MATCH |
| sold | 0 | None | None | EXACT_MATCH |
| is_deleted | None | None | None | EXACT_MATCH |
| skip_sl_tp_reminder | None | None | None | EXACT_MATCH |
| sl_tp_mode | conservative | None | None | MISMATCH |
| order_status | PENDING | None | None | MISMATCH |
| exchange | CRYPTO_COM | None | None | MISMATCH |
| throttle_buy | None | None | None | BACKEND_ONLY |
| throttle_sell | None | None | None | BACKEND_ONLY |
| alert_enabled | None | None | None | MATCH |
| buy_alert_enabled | None | None | None | MATCH |
| sell_alert_enabled | None | None | None | MATCH |

**Computed Strategy Info:**
- Preset: swing-Conservative
- Strategy Key: swing:conservative
- Decision: WAIT
- Index: None
- Buy Signal: False
- Sell Signal: False

### ETH_USDT

**Status:** HAS_ISSUES

**Backend Query Time:** 0.002s

| Field | DB | API | Computed | Classification |
|-------|----|-----|----------|----------------|
| price | None | None | 3396.1700 | MISMATCH |
| rsi | None | None | 37.1600 | MISMATCH |
| ma50 | None | None | 3377.7300 | MISMATCH |
| ma200 | None | None | 3716.1600 | MISMATCH |
| ema10 | None | None | 3397.7200 | MISMATCH |
| atr | None | None | None | EXACT_MATCH |
| buy_target | None | None | None | EXACT_MATCH |
| take_profit | None | None | None | EXACT_MATCH |
| stop_loss | None | None | None | EXACT_MATCH |
| sl_price | None | None | None | EXACT_MATCH |
| tp_price | None | None | None | EXACT_MATCH |
| sl_percentage | None | None | None | EXACT_MATCH |
| tp_percentage | None | None | None | EXACT_MATCH |
| min_price_change_pct | None | None | None | EXACT_MATCH |
| alert_cooldown_minutes | None | None | None | EXACT_MATCH |
| trade_amount_usd | None | None | None | EXACT_MATCH |
| alert_enabled | None | None | None | EXACT_MATCH |
| buy_alert_enabled | None | None | None | EXACT_MATCH |
| sell_alert_enabled | None | None | None | EXACT_MATCH |
| trade_enabled | 0 | None | None | EXACT_MATCH |
| trade_on_margin | 0 | None | None | EXACT_MATCH |
| sold | 0 | None | None | EXACT_MATCH |
| is_deleted | None | None | None | EXACT_MATCH |
| skip_sl_tp_reminder | None | None | None | EXACT_MATCH |
| sl_tp_mode | conservative | None | None | MISMATCH |
| order_status | PENDING | None | None | MISMATCH |
| exchange | CRYPTO_COM | None | None | MISMATCH |
| throttle_buy | None | None | None | BACKEND_ONLY |
| throttle_sell | None | None | None | BACKEND_ONLY |
| alert_enabled | None | None | None | MATCH |
| buy_alert_enabled | None | None | None | MATCH |
| sell_alert_enabled | None | None | None | MATCH |

**Computed Strategy Info:**
- Preset: intraday-Conservative
- Strategy Key: intraday:conservative
- Decision: WAIT
- Index: None
- Buy Signal: False
- Sell Signal: False

### SOL_USDT

**Status:** HAS_ISSUES

**Backend Query Time:** 0.001s

| Field | DB | API | Computed | Classification |
|-------|----|-----|----------|----------------|
| price | None | None | 158.8100 | MISMATCH |
| rsi | None | None | 34.2300 | MISMATCH |
| ma50 | None | None | 158.8300 | MISMATCH |
| ma200 | None | None | 178.0200 | MISMATCH |
| ema10 | None | None | 159.6400 | MISMATCH |
| atr | None | None | None | EXACT_MATCH |
| buy_target | None | None | None | EXACT_MATCH |
| take_profit | None | None | None | EXACT_MATCH |
| stop_loss | None | None | None | EXACT_MATCH |
| sl_price | None | None | None | EXACT_MATCH |
| tp_price | None | None | None | EXACT_MATCH |
| sl_percentage | None | None | None | EXACT_MATCH |
| tp_percentage | None | None | None | EXACT_MATCH |
| min_price_change_pct | None | None | None | EXACT_MATCH |
| alert_cooldown_minutes | None | None | None | EXACT_MATCH |
| trade_amount_usd | None | None | None | EXACT_MATCH |
| alert_enabled | None | None | None | EXACT_MATCH |
| buy_alert_enabled | None | None | None | EXACT_MATCH |
| sell_alert_enabled | None | None | None | EXACT_MATCH |
| trade_enabled | 0 | None | None | EXACT_MATCH |
| trade_on_margin | 0 | None | None | EXACT_MATCH |
| sold | 0 | None | None | EXACT_MATCH |
| is_deleted | None | None | None | EXACT_MATCH |
| skip_sl_tp_reminder | None | None | None | EXACT_MATCH |
| sl_tp_mode | conservative | None | None | MISMATCH |
| order_status | PENDING | None | None | MISMATCH |
| exchange | CRYPTO_COM | None | None | MISMATCH |
| throttle_buy | None | None | None | BACKEND_ONLY |
| throttle_sell | None | None | None | BACKEND_ONLY |
| alert_enabled | None | None | None | MATCH |
| buy_alert_enabled | None | None | None | MATCH |
| sell_alert_enabled | None | None | None | MATCH |

**Computed Strategy Info:**
- Preset: swing-Conservative
- Strategy Key: swing:conservative
- Decision: WAIT
- Index: None
- Buy Signal: False
- Sell Signal: False

### DOGE_USDT

**Status:** HAS_ISSUES

**Backend Query Time:** 0.002s

| Field | DB | API | Computed | Classification |
|-------|----|-----|----------|----------------|
| price | None | None | 0.162844 | MISMATCH |
| rsi | None | None | 42.4500 | MISMATCH |
| ma50 | 0.146287 | None | 0.146287 | MISMATCH |
| ma200 | 0.156277 | None | 0.156277 | MISMATCH |
| ema10 | 0.138924 | None | 0.138924 | MISMATCH |
| atr | None | None | None | EXACT_MATCH |
| buy_target | None | None | None | EXACT_MATCH |
| take_profit | None | None | None | EXACT_MATCH |
| stop_loss | None | None | None | EXACT_MATCH |
| sl_price | None | None | None | EXACT_MATCH |
| tp_price | None | None | None | EXACT_MATCH |
| sl_percentage | None | None | None | EXACT_MATCH |
| tp_percentage | None | None | None | EXACT_MATCH |
| min_price_change_pct | None | None | None | EXACT_MATCH |
| alert_cooldown_minutes | None | None | None | EXACT_MATCH |
| trade_amount_usd | None | None | None | EXACT_MATCH |
| alert_enabled | None | None | None | EXACT_MATCH |
| buy_alert_enabled | None | None | None | EXACT_MATCH |
| sell_alert_enabled | None | None | None | EXACT_MATCH |
| trade_enabled | 0 | None | None | EXACT_MATCH |
| trade_on_margin | 0 | None | None | EXACT_MATCH |
| sold | 0 | None | None | EXACT_MATCH |
| is_deleted | None | None | None | EXACT_MATCH |
| skip_sl_tp_reminder | None | None | None | EXACT_MATCH |
| sl_tp_mode | conservative | None | None | MISMATCH |
| order_status | PENDING | None | None | MISMATCH |
| exchange | CRYPTO_COM | None | None | MISMATCH |
| throttle_buy | None | None | None | BACKEND_ONLY |
| throttle_sell | None | None | None | BACKEND_ONLY |
| alert_enabled | None | None | None | MATCH |
| buy_alert_enabled | None | None | None | MATCH |
| sell_alert_enabled | None | None | None | MATCH |

**Computed Strategy Info:**
- Preset: swing-Conservative
- Strategy Key: swing:conservative
- Decision: WAIT
- Index: None
- Buy Signal: False
- Sell Signal: False

### ADA_USDT

**Status:** HAS_ISSUES

**Backend Query Time:** 0.001s

| Field | DB | API | Computed | Classification |
|-------|----|-----|----------|----------------|
| price | None | None | 0.534540 | MISMATCH |
| rsi | None | None | 35.5200 | MISMATCH |
| ma50 | None | None | 0.540000 | MISMATCH |
| ma200 | None | None | 0.590000 | MISMATCH |
| ema10 | None | None | 0.540000 | MISMATCH |
| atr | None | None | None | EXACT_MATCH |
| buy_target | None | None | None | EXACT_MATCH |
| take_profit | None | None | None | EXACT_MATCH |
| stop_loss | None | None | None | EXACT_MATCH |
| sl_price | None | None | None | EXACT_MATCH |
| tp_price | None | None | None | EXACT_MATCH |
| sl_percentage | None | None | None | EXACT_MATCH |
| tp_percentage | None | None | None | EXACT_MATCH |
| min_price_change_pct | None | None | None | EXACT_MATCH |
| alert_cooldown_minutes | None | None | None | EXACT_MATCH |
| trade_amount_usd | None | None | None | EXACT_MATCH |
| alert_enabled | None | None | None | EXACT_MATCH |
| buy_alert_enabled | None | None | None | EXACT_MATCH |
| sell_alert_enabled | None | None | None | EXACT_MATCH |
| trade_enabled | 0 | None | None | EXACT_MATCH |
| trade_on_margin | 0 | None | None | EXACT_MATCH |
| sold | 0 | None | None | EXACT_MATCH |
| is_deleted | None | None | None | EXACT_MATCH |
| skip_sl_tp_reminder | None | None | None | EXACT_MATCH |
| sl_tp_mode | conservative | None | None | MISMATCH |
| order_status | PENDING | None | None | MISMATCH |
| exchange | CRYPTO_COM | None | None | MISMATCH |
| throttle_buy | None | None | None | BACKEND_ONLY |
| throttle_sell | None | None | None | BACKEND_ONLY |
| alert_enabled | None | None | None | MATCH |
| buy_alert_enabled | None | None | None | MATCH |
| sell_alert_enabled | None | None | None | MATCH |

**Computed Strategy Info:**
- Preset: swing-Conservative
- Strategy Key: swing:conservative
- Decision: WAIT
- Index: None
- Buy Signal: False
- Sell Signal: False

### BNB_USDT

**Status:** HAS_ISSUES

**Backend Query Time:** 0.001s

| Field | DB | API | Computed | Classification |
|-------|----|-----|----------|----------------|
| price | None | None | 815.2900 | MISMATCH |
| rsi | None | None | 50.0000 | MISMATCH |
| ma50 | None | None | 815.2900 | MISMATCH |
| ma200 | None | None | 815.2900 | MISMATCH |
| ema10 | None | None | 815.2900 | MISMATCH |
| atr | None | None | None | EXACT_MATCH |
| buy_target | None | None | None | EXACT_MATCH |
| take_profit | None | None | None | EXACT_MATCH |
| stop_loss | None | None | None | EXACT_MATCH |
| sl_price | None | None | None | EXACT_MATCH |
| tp_price | None | None | None | EXACT_MATCH |
| sl_percentage | None | None | None | EXACT_MATCH |
| tp_percentage | None | None | None | EXACT_MATCH |
| min_price_change_pct | None | None | None | EXACT_MATCH |
| alert_cooldown_minutes | None | None | None | EXACT_MATCH |
| trade_amount_usd | None | None | None | EXACT_MATCH |
| alert_enabled | None | None | None | EXACT_MATCH |
| buy_alert_enabled | None | None | None | EXACT_MATCH |
| sell_alert_enabled | None | None | None | EXACT_MATCH |
| trade_enabled | 0 | None | None | EXACT_MATCH |
| trade_on_margin | 0 | None | None | EXACT_MATCH |
| sold | 0 | None | None | EXACT_MATCH |
| is_deleted | None | None | None | EXACT_MATCH |
| skip_sl_tp_reminder | None | None | None | EXACT_MATCH |
| sl_tp_mode | conservative | None | None | MISMATCH |
| order_status | PENDING | None | None | MISMATCH |
| exchange | CRYPTO_COM | None | None | MISMATCH |
| throttle_buy | None | None | None | BACKEND_ONLY |
| throttle_sell | None | None | None | BACKEND_ONLY |
| alert_enabled | None | None | None | MATCH |
| buy_alert_enabled | None | None | None | MATCH |
| sell_alert_enabled | None | None | None | MATCH |

**Computed Strategy Info:**
- Preset: swing-Conservative
- Strategy Key: swing:conservative
- Decision: WAIT
- Index: None
- Buy Signal: False
- Sell Signal: False

### XRP_USDT

**Status:** HAS_ISSUES

**Backend Query Time:** 0.001s

| Field | DB | API | Computed | Classification |
|-------|----|-----|----------|----------------|
| price | None | None | 2.2931 | MISMATCH |
| rsi | None | None | 38.2300 | MISMATCH |
| ma50 | None | None | 2.2700 | MISMATCH |
| ma200 | None | None | 2.4300 | MISMATCH |
| ema10 | None | None | 2.3200 | MISMATCH |
| atr | None | None | None | EXACT_MATCH |
| buy_target | None | None | None | EXACT_MATCH |
| take_profit | None | None | None | EXACT_MATCH |
| stop_loss | None | None | None | EXACT_MATCH |
| sl_price | None | None | None | EXACT_MATCH |
| tp_price | None | None | None | EXACT_MATCH |
| sl_percentage | None | None | None | EXACT_MATCH |
| tp_percentage | None | None | None | EXACT_MATCH |
| min_price_change_pct | None | None | None | EXACT_MATCH |
| alert_cooldown_minutes | None | None | None | EXACT_MATCH |
| trade_amount_usd | None | None | None | EXACT_MATCH |
| alert_enabled | None | None | None | EXACT_MATCH |
| buy_alert_enabled | None | None | None | EXACT_MATCH |
| sell_alert_enabled | None | None | None | EXACT_MATCH |
| trade_enabled | 0 | None | None | EXACT_MATCH |
| trade_on_margin | 0 | None | None | EXACT_MATCH |
| sold | 0 | None | None | EXACT_MATCH |
| is_deleted | None | None | None | EXACT_MATCH |
| skip_sl_tp_reminder | None | None | None | EXACT_MATCH |
| sl_tp_mode | conservative | None | None | MISMATCH |
| order_status | PENDING | None | None | MISMATCH |
| exchange | CRYPTO_COM | None | None | MISMATCH |
| throttle_buy | None | None | None | BACKEND_ONLY |
| throttle_sell | None | None | None | BACKEND_ONLY |
| alert_enabled | None | None | None | MATCH |
| buy_alert_enabled | None | None | None | MATCH |
| sell_alert_enabled | None | None | None | MATCH |

**Computed Strategy Info:**
- Preset: swing-Conservative
- Strategy Key: swing:conservative
- Decision: WAIT
- Index: None
- Buy Signal: False
- Sell Signal: False

### MATIC_USDT

**Status:** HAS_ISSUES

**Backend Query Time:** 0.002s

| Field | DB | API | Computed | Classification |
|-------|----|-----|----------|----------------|
| price | None | None | 0.130488 | MISMATCH |
| rsi | None | None | 50.0000 | MISMATCH |
| ma50 | None | None | 0.130488 | MISMATCH |
| ma200 | None | None | 0.130488 | MISMATCH |
| ema10 | None | None | 0.130488 | MISMATCH |
| atr | None | None | None | EXACT_MATCH |
| buy_target | None | None | None | EXACT_MATCH |
| take_profit | None | None | None | EXACT_MATCH |
| stop_loss | None | None | None | EXACT_MATCH |
| sl_price | None | None | None | EXACT_MATCH |
| tp_price | None | None | None | EXACT_MATCH |
| sl_percentage | None | None | None | EXACT_MATCH |
| tp_percentage | None | None | None | EXACT_MATCH |
| min_price_change_pct | None | None | None | EXACT_MATCH |
| alert_cooldown_minutes | None | None | None | EXACT_MATCH |
| trade_amount_usd | None | None | None | EXACT_MATCH |
| alert_enabled | None | None | None | EXACT_MATCH |
| buy_alert_enabled | None | None | None | EXACT_MATCH |
| sell_alert_enabled | None | None | None | EXACT_MATCH |
| trade_enabled | 0 | None | None | EXACT_MATCH |
| trade_on_margin | 0 | None | None | EXACT_MATCH |
| sold | 0 | None | None | EXACT_MATCH |
| is_deleted | None | None | None | EXACT_MATCH |
| skip_sl_tp_reminder | None | None | None | EXACT_MATCH |
| sl_tp_mode | conservative | None | None | MISMATCH |
| order_status | PENDING | None | None | MISMATCH |
| exchange | CRYPTO_COM | None | None | MISMATCH |
| throttle_buy | None | None | None | BACKEND_ONLY |
| throttle_sell | None | None | None | BACKEND_ONLY |
| alert_enabled | None | None | None | MATCH |
| buy_alert_enabled | None | None | None | MATCH |
| sell_alert_enabled | None | None | None | MATCH |

**Computed Strategy Info:**
- Preset: swing-Conservative
- Strategy Key: swing:conservative
- Decision: WAIT
- Index: None
- Buy Signal: False
- Sell Signal: False

### AVAX_USDT

**Status:** HAS_ISSUES

**Backend Query Time:** 0.001s

| Field | DB | API | Computed | Classification |
|-------|----|-----|----------|----------------|
| price | None | None | 16.2980 | MISMATCH |
| rsi | None | None | 31.0700 | MISMATCH |
| ma50 | None | None | 16.4100 | MISMATCH |
| ma200 | None | None | 17.8900 | MISMATCH |
| ema10 | None | None | 16.3900 | MISMATCH |
| atr | None | None | None | EXACT_MATCH |
| buy_target | None | None | None | EXACT_MATCH |
| take_profit | None | None | None | EXACT_MATCH |
| stop_loss | None | None | None | EXACT_MATCH |
| sl_price | None | None | None | EXACT_MATCH |
| tp_price | None | None | None | EXACT_MATCH |
| sl_percentage | None | None | None | EXACT_MATCH |
| tp_percentage | None | None | None | EXACT_MATCH |
| min_price_change_pct | None | None | None | EXACT_MATCH |
| alert_cooldown_minutes | None | None | None | EXACT_MATCH |
| trade_amount_usd | None | None | None | EXACT_MATCH |
| alert_enabled | None | None | None | EXACT_MATCH |
| buy_alert_enabled | None | None | None | EXACT_MATCH |
| sell_alert_enabled | None | None | None | EXACT_MATCH |
| trade_enabled | 0 | None | None | EXACT_MATCH |
| trade_on_margin | 0 | None | None | EXACT_MATCH |
| sold | 0 | None | None | EXACT_MATCH |
| is_deleted | None | None | None | EXACT_MATCH |
| skip_sl_tp_reminder | None | None | None | EXACT_MATCH |
| sl_tp_mode | conservative | None | None | MISMATCH |
| order_status | PENDING | None | None | MISMATCH |
| exchange | CRYPTO_COM | None | None | MISMATCH |
| throttle_buy | None | None | None | BACKEND_ONLY |
| throttle_sell | None | None | None | BACKEND_ONLY |
| alert_enabled | None | None | None | MATCH |
| buy_alert_enabled | None | None | None | MATCH |
| sell_alert_enabled | None | None | None | MATCH |

**Computed Strategy Info:**
- Preset: swing-Conservative
- Strategy Key: swing:conservative
- Decision: WAIT
- Index: None
- Buy Signal: False
- Sell Signal: False

### DOT_USDT

**Status:** HAS_ISSUES

**Backend Query Time:** 0.020s

| Field | DB | API | Computed | Classification |
|-------|----|-----|----------|----------------|
| price | None | None | 2.6074 | MISMATCH |
| rsi | None | None | 33.9400 | MISMATCH |
| ma50 | None | None | 2.5900 | MISMATCH |
| ma200 | None | None | 2.8200 | MISMATCH |
| ema10 | None | None | 2.6200 | MISMATCH |
| atr | None | None | None | EXACT_MATCH |
| buy_target | None | None | None | EXACT_MATCH |
| take_profit | None | None | None | EXACT_MATCH |
| stop_loss | None | None | None | EXACT_MATCH |
| sl_price | None | None | None | EXACT_MATCH |
| tp_price | None | None | None | EXACT_MATCH |
| sl_percentage | None | None | None | EXACT_MATCH |
| tp_percentage | None | None | None | EXACT_MATCH |
| min_price_change_pct | None | None | None | EXACT_MATCH |
| alert_cooldown_minutes | None | None | None | EXACT_MATCH |
| trade_amount_usd | None | None | None | EXACT_MATCH |
| alert_enabled | None | None | None | EXACT_MATCH |
| buy_alert_enabled | None | None | None | EXACT_MATCH |
| sell_alert_enabled | None | None | None | EXACT_MATCH |
| trade_enabled | 0 | None | None | EXACT_MATCH |
| trade_on_margin | 0 | None | None | EXACT_MATCH |
| sold | 0 | None | None | EXACT_MATCH |
| is_deleted | None | None | None | EXACT_MATCH |
| skip_sl_tp_reminder | None | None | None | EXACT_MATCH |
| sl_tp_mode | conservative | None | None | MISMATCH |
| order_status | PENDING | None | None | MISMATCH |
| exchange | CRYPTO_COM | None | None | MISMATCH |
| alert_enabled | None | None | None | MATCH |
| buy_alert_enabled | None | None | None | MATCH |
| sell_alert_enabled | None | None | None | MATCH |

### LINK_USDT

**Status:** HAS_ISSUES

**Backend Query Time:** 0.003s

| Field | DB | API | Computed | Classification |
|-------|----|-----|----------|----------------|
| price | None | None | 11.8240 | MISMATCH |
| rsi | None | None | 36.6100 | MISMATCH |
| ma50 | None | None | 12.6400 | MISMATCH |
| ma200 | None | None | 13.5300 | MISMATCH |
| ema10 | None | None | 12.0100 | MISMATCH |
| atr | None | None | None | EXACT_MATCH |
| buy_target | None | None | None | EXACT_MATCH |
| take_profit | None | None | None | EXACT_MATCH |
| stop_loss | None | None | None | EXACT_MATCH |
| sl_price | None | None | None | EXACT_MATCH |
| tp_price | None | None | None | EXACT_MATCH |
| sl_percentage | None | None | None | EXACT_MATCH |
| tp_percentage | None | None | None | EXACT_MATCH |
| min_price_change_pct | None | None | None | EXACT_MATCH |
| alert_cooldown_minutes | None | None | None | EXACT_MATCH |
| trade_amount_usd | None | None | None | EXACT_MATCH |
| alert_enabled | None | None | None | EXACT_MATCH |
| buy_alert_enabled | None | None | None | EXACT_MATCH |
| sell_alert_enabled | None | None | None | EXACT_MATCH |
| trade_enabled | 0 | None | None | EXACT_MATCH |
| trade_on_margin | 0 | None | None | EXACT_MATCH |
| sold | 0 | None | None | EXACT_MATCH |
| is_deleted | None | None | None | EXACT_MATCH |
| skip_sl_tp_reminder | None | None | None | EXACT_MATCH |
| sl_tp_mode | conservative | None | None | MISMATCH |
| order_status | PENDING | None | None | MISMATCH |
| exchange | CRYPTO_COM | None | None | MISMATCH |
| alert_enabled | None | None | None | MATCH |
| buy_alert_enabled | None | None | None | MATCH |
| sell_alert_enabled | None | None | None | MATCH |

### UNI_USDT

**Status:** HAS_ISSUES

**Backend Query Time:** 0.002s

| Field | DB | API | Computed | Classification |
|-------|----|-----|----------|----------------|
| price | None | None | 6.2154 | MISMATCH |
| rsi | None | None | 39.8300 | MISMATCH |
| ma50 | None | None | 6.5900 | MISMATCH |
| ma200 | None | None | 7.1800 | MISMATCH |
| ema10 | None | None | 6.3800 | MISMATCH |
| atr | None | None | None | EXACT_MATCH |
| buy_target | None | None | None | EXACT_MATCH |
| take_profit | None | None | None | EXACT_MATCH |
| stop_loss | None | None | None | EXACT_MATCH |
| sl_price | None | None | None | EXACT_MATCH |
| tp_price | None | None | None | EXACT_MATCH |
| sl_percentage | None | None | None | EXACT_MATCH |
| tp_percentage | None | None | None | EXACT_MATCH |
| min_price_change_pct | None | None | None | EXACT_MATCH |
| alert_cooldown_minutes | None | None | None | EXACT_MATCH |
| trade_amount_usd | None | None | None | EXACT_MATCH |
| alert_enabled | None | None | None | EXACT_MATCH |
| buy_alert_enabled | None | None | None | EXACT_MATCH |
| sell_alert_enabled | None | None | None | EXACT_MATCH |
| trade_enabled | 0 | None | None | EXACT_MATCH |
| trade_on_margin | 0 | None | None | EXACT_MATCH |
| sold | 0 | None | None | EXACT_MATCH |
| is_deleted | None | None | None | EXACT_MATCH |
| skip_sl_tp_reminder | None | None | None | EXACT_MATCH |
| sl_tp_mode | conservative | None | None | MISMATCH |
| order_status | PENDING | None | None | MISMATCH |
| exchange | CRYPTO_COM | None | None | MISMATCH |
| throttle_buy | None | None | None | BACKEND_ONLY |
| throttle_sell | None | None | None | BACKEND_ONLY |
| alert_enabled | None | None | None | MATCH |
| buy_alert_enabled | None | None | None | MATCH |
| sell_alert_enabled | None | None | None | MATCH |

**Computed Strategy Info:**
- Preset: swing-Conservative
- Strategy Key: swing:conservative
- Decision: WAIT
- Index: None
- Buy Signal: False
- Sell Signal: False

### ATOM_USDT

**Status:** HAS_ISSUES

**Backend Query Time:** 0.004s

| Field | DB | API | Computed | Classification |
|-------|----|-----|----------|----------------|
| price | None | None | 2.4590 | MISMATCH |
| rsi | None | None | 33.3300 | MISMATCH |
| ma50 | None | None | 2.7000 | MISMATCH |
| ma200 | None | None | 2.7800 | MISMATCH |
| ema10 | None | None | 2.4900 | MISMATCH |
| atr | None | None | None | EXACT_MATCH |
| buy_target | None | None | None | EXACT_MATCH |
| take_profit | None | None | None | EXACT_MATCH |
| stop_loss | None | None | None | EXACT_MATCH |
| sl_price | None | None | None | EXACT_MATCH |
| tp_price | None | None | None | EXACT_MATCH |
| sl_percentage | None | None | None | EXACT_MATCH |
| tp_percentage | None | None | None | EXACT_MATCH |
| min_price_change_pct | None | None | None | EXACT_MATCH |
| alert_cooldown_minutes | None | None | None | EXACT_MATCH |
| trade_amount_usd | None | None | None | EXACT_MATCH |
| alert_enabled | None | None | None | EXACT_MATCH |
| buy_alert_enabled | None | None | None | EXACT_MATCH |
| sell_alert_enabled | None | None | None | EXACT_MATCH |
| trade_enabled | 0 | None | None | EXACT_MATCH |
| trade_on_margin | 0 | None | None | EXACT_MATCH |
| sold | 0 | None | None | EXACT_MATCH |
| is_deleted | None | None | None | EXACT_MATCH |
| skip_sl_tp_reminder | None | None | None | EXACT_MATCH |
| sl_tp_mode | conservative | None | None | MISMATCH |
| order_status | PENDING | None | None | MISMATCH |
| exchange | CRYPTO_COM | None | None | MISMATCH |
| throttle_buy | None | None | None | BACKEND_ONLY |
| throttle_sell | None | None | None | BACKEND_ONLY |
| alert_enabled | None | None | None | MATCH |
| buy_alert_enabled | None | None | None | MATCH |
| sell_alert_enabled | None | None | None | MATCH |

**Computed Strategy Info:**
- Preset: swing-Conservative
- Strategy Key: swing:conservative
- Decision: WAIT
- Index: None
- Buy Signal: False
- Sell Signal: False

### ALGO_USDT

**Status:** HAS_ISSUES

**Backend Query Time:** 0.002s

| Field | DB | API | Computed | Classification |
|-------|----|-----|----------|----------------|
| price | None | None | 0.134750 | MISMATCH |
| rsi | None | None | 38.7400 | MISMATCH |
| ma50 | None | None | 0.140000 | MISMATCH |
| ma200 | None | None | 0.150000 | MISMATCH |
| ema10 | None | None | 0.140000 | MISMATCH |
| atr | None | None | None | EXACT_MATCH |
| buy_target | None | None | None | EXACT_MATCH |
| take_profit | None | None | None | EXACT_MATCH |
| stop_loss | None | None | None | EXACT_MATCH |
| sl_price | None | None | None | EXACT_MATCH |
| tp_price | None | None | None | EXACT_MATCH |
| sl_percentage | None | None | None | EXACT_MATCH |
| tp_percentage | None | None | None | EXACT_MATCH |
| min_price_change_pct | None | None | None | EXACT_MATCH |
| alert_cooldown_minutes | None | None | None | EXACT_MATCH |
| trade_amount_usd | None | None | None | EXACT_MATCH |
| alert_enabled | None | None | None | EXACT_MATCH |
| buy_alert_enabled | None | None | None | EXACT_MATCH |
| sell_alert_enabled | None | None | None | EXACT_MATCH |
| trade_enabled | 0 | None | None | EXACT_MATCH |
| trade_on_margin | 0 | None | None | EXACT_MATCH |
| sold | 0 | None | None | EXACT_MATCH |
| is_deleted | None | None | None | EXACT_MATCH |
| skip_sl_tp_reminder | None | None | None | EXACT_MATCH |
| sl_tp_mode | conservative | None | None | MISMATCH |
| order_status | PENDING | None | None | MISMATCH |
| exchange | CRYPTO_COM | None | None | MISMATCH |
| alert_enabled | None | None | None | MATCH |
| buy_alert_enabled | None | None | None | MATCH |
| sell_alert_enabled | None | None | None | MATCH |

### NEAR_USDT

**Status:** HAS_ISSUES

**Backend Query Time:** 0.002s

| Field | DB | API | Computed | Classification |
|-------|----|-----|----------|----------------|
| price | None | None | 1.8214 | MISMATCH |
| rsi | None | None | 36.1000 | MISMATCH |
| ma50 | None | None | 2.0300 | MISMATCH |
| ma200 | None | None | 2.2700 | MISMATCH |
| ema10 | None | None | 1.8600 | MISMATCH |
| atr | None | None | None | EXACT_MATCH |
| buy_target | None | None | None | EXACT_MATCH |
| take_profit | None | None | None | EXACT_MATCH |
| stop_loss | None | None | None | EXACT_MATCH |
| sl_price | None | None | None | EXACT_MATCH |
| tp_price | None | None | None | EXACT_MATCH |
| sl_percentage | None | None | None | EXACT_MATCH |
| tp_percentage | None | None | None | EXACT_MATCH |
| min_price_change_pct | None | None | None | EXACT_MATCH |
| alert_cooldown_minutes | None | None | None | EXACT_MATCH |
| trade_amount_usd | None | None | None | EXACT_MATCH |
| alert_enabled | None | None | None | EXACT_MATCH |
| buy_alert_enabled | None | None | None | EXACT_MATCH |
| sell_alert_enabled | None | None | None | EXACT_MATCH |
| trade_enabled | 0 | None | None | EXACT_MATCH |
| trade_on_margin | 0 | None | None | EXACT_MATCH |
| sold | 0 | None | None | EXACT_MATCH |
| is_deleted | None | None | None | EXACT_MATCH |
| skip_sl_tp_reminder | None | None | None | EXACT_MATCH |
| sl_tp_mode | conservative | None | None | MISMATCH |
| order_status | PENDING | None | None | MISMATCH |
| exchange | CRYPTO_COM | None | None | MISMATCH |
| throttle_buy | None | None | None | BACKEND_ONLY |
| throttle_sell | None | None | None | BACKEND_ONLY |
| alert_enabled | None | None | None | MATCH |
| buy_alert_enabled | None | None | None | MATCH |
| sell_alert_enabled | None | None | None | MATCH |

**Computed Strategy Info:**
- Preset: swing-Conservative
- Strategy Key: swing:conservative
- Decision: WAIT
- Index: None
- Buy Signal: False
- Sell Signal: False

### ICP_USDT

**Status:** HAS_ISSUES

**Backend Query Time:** 0.002s

| Field | DB | API | Computed | Classification |
|-------|----|-----|----------|----------------|
| price | None | None | 4.1124 | MISMATCH |
| rsi | None | None | 31.4000 | MISMATCH |
| ma50 | None | None | 4.5300 | MISMATCH |
| ma200 | None | None | 5.0800 | MISMATCH |
| ema10 | None | None | 4.2100 | MISMATCH |
| atr | None | None | None | EXACT_MATCH |
| buy_target | None | None | None | EXACT_MATCH |
| take_profit | None | None | None | EXACT_MATCH |
| stop_loss | None | None | None | EXACT_MATCH |
| sl_price | None | None | None | EXACT_MATCH |
| tp_price | None | None | None | EXACT_MATCH |
| sl_percentage | None | None | None | EXACT_MATCH |
| tp_percentage | None | None | None | EXACT_MATCH |
| min_price_change_pct | None | None | None | EXACT_MATCH |
| alert_cooldown_minutes | None | None | None | EXACT_MATCH |
| trade_amount_usd | None | None | None | EXACT_MATCH |
| alert_enabled | None | None | None | EXACT_MATCH |
| buy_alert_enabled | None | None | None | EXACT_MATCH |
| sell_alert_enabled | None | None | None | EXACT_MATCH |
| trade_enabled | 0 | None | None | EXACT_MATCH |
| trade_on_margin | 0 | None | None | EXACT_MATCH |
| sold | 0 | None | None | EXACT_MATCH |
| is_deleted | None | None | None | EXACT_MATCH |
| skip_sl_tp_reminder | None | None | None | EXACT_MATCH |
| sl_tp_mode | conservative | None | None | MISMATCH |
| order_status | PENDING | None | None | MISMATCH |
| exchange | CRYPTO_COM | None | None | MISMATCH |
| throttle_buy | None | None | None | BACKEND_ONLY |
| throttle_sell | None | None | None | BACKEND_ONLY |
| alert_enabled | None | None | None | MATCH |
| buy_alert_enabled | None | None | None | MATCH |
| sell_alert_enabled | None | None | None | MATCH |

**Computed Strategy Info:**
- Preset: swing-Conservative
- Strategy Key: swing:conservative
- Decision: WAIT
- Index: None
- Buy Signal: False
- Sell Signal: False

### FIL_USDT

**Status:** HAS_ISSUES

**Backend Query Time:** 0.001s

| Field | DB | API | Computed | Classification |
|-------|----|-----|----------|----------------|
| price | None | None | 1.6114 | MISMATCH |
| rsi | None | None | 33.7500 | MISMATCH |
| ma50 | None | None | 1.7300 | MISMATCH |
| ma200 | None | None | 1.9300 | MISMATCH |
| ema10 | None | None | 1.6400 | MISMATCH |
| atr | None | None | None | EXACT_MATCH |
| buy_target | None | None | None | EXACT_MATCH |
| take_profit | None | None | None | EXACT_MATCH |
| stop_loss | None | None | None | EXACT_MATCH |
| sl_price | None | None | None | EXACT_MATCH |
| tp_price | None | None | None | EXACT_MATCH |
| sl_percentage | None | None | None | EXACT_MATCH |
| tp_percentage | None | None | None | EXACT_MATCH |
| min_price_change_pct | None | None | None | EXACT_MATCH |
| alert_cooldown_minutes | None | None | None | EXACT_MATCH |
| trade_amount_usd | None | None | None | EXACT_MATCH |
| alert_enabled | None | None | None | EXACT_MATCH |
| buy_alert_enabled | None | None | None | EXACT_MATCH |
| sell_alert_enabled | None | None | None | EXACT_MATCH |
| trade_enabled | 0 | None | None | EXACT_MATCH |
| trade_on_margin | 0 | None | None | EXACT_MATCH |
| sold | 0 | None | None | EXACT_MATCH |
| is_deleted | None | None | None | EXACT_MATCH |
| skip_sl_tp_reminder | None | None | None | EXACT_MATCH |
| sl_tp_mode | conservative | None | None | MISMATCH |
| order_status | PENDING | None | None | MISMATCH |
| exchange | CRYPTO_COM | None | None | MISMATCH |
| throttle_buy | None | None | None | BACKEND_ONLY |
| throttle_sell | None | None | None | BACKEND_ONLY |
| alert_enabled | None | None | None | MATCH |
| buy_alert_enabled | None | None | None | MATCH |
| sell_alert_enabled | None | None | None | MATCH |

**Computed Strategy Info:**
- Preset: swing-Conservative
- Strategy Key: swing:conservative
- Decision: WAIT
- Index: None
- Buy Signal: False
- Sell Signal: False

### APT_USDT

**Status:** HAS_ISSUES

**Backend Query Time:** 0.002s

| Field | DB | API | Computed | Classification |
|-------|----|-----|----------|----------------|
| price | None | None | 2.3165 | MISMATCH |
| rsi | None | None | 27.8300 | MISMATCH |
| ma50 | None | None | 2.6400 | MISMATCH |
| ma200 | None | None | 2.8300 | MISMATCH |
| ema10 | None | None | 2.3600 | MISMATCH |
| atr | None | None | None | EXACT_MATCH |
| buy_target | None | None | None | EXACT_MATCH |
| take_profit | None | None | None | EXACT_MATCH |
| stop_loss | None | None | None | EXACT_MATCH |
| sl_price | None | None | None | EXACT_MATCH |
| tp_price | None | None | None | EXACT_MATCH |
| sl_percentage | None | None | None | EXACT_MATCH |
| tp_percentage | None | None | None | EXACT_MATCH |
| min_price_change_pct | None | None | None | EXACT_MATCH |
| alert_cooldown_minutes | None | None | None | EXACT_MATCH |
| trade_amount_usd | None | None | None | EXACT_MATCH |
| alert_enabled | None | None | None | EXACT_MATCH |
| buy_alert_enabled | None | None | None | EXACT_MATCH |
| sell_alert_enabled | None | None | None | EXACT_MATCH |
| trade_enabled | 0 | None | None | EXACT_MATCH |
| trade_on_margin | 0 | None | None | EXACT_MATCH |
| sold | 0 | None | None | EXACT_MATCH |
| is_deleted | None | None | None | EXACT_MATCH |
| skip_sl_tp_reminder | None | None | None | EXACT_MATCH |
| sl_tp_mode | conservative | None | None | MISMATCH |
| order_status | PENDING | None | None | MISMATCH |
| exchange | CRYPTO_COM | None | None | MISMATCH |
| throttle_buy | None | None | None | BACKEND_ONLY |
| throttle_sell | None | None | None | BACKEND_ONLY |
| alert_enabled | None | None | None | MATCH |
| buy_alert_enabled | None | None | None | MATCH |
| sell_alert_enabled | None | None | None | MATCH |

**Computed Strategy Info:**
- Preset: swing-Conservative
- Strategy Key: swing:conservative
- Decision: WAIT
- Index: None
- Buy Signal: False
- Sell Signal: False

### BTC_USD

**Status:** HAS_ISSUES

**Backend Query Time:** 0.002s

| Field | DB | API | Computed | Classification |
|-------|----|-----|----------|----------------|
| price | None | None | 84110.0000 | MISMATCH |
| rsi | None | None | 45.9300 | MISMATCH |
| ma50 | None | None | 86269.4000 | MISMATCH |
| ma200 | None | None | 92099.5500 | MISMATCH |
| ema10 | None | None | 84467.8200 | MISMATCH |
| atr | None | None | None | EXACT_MATCH |
| buy_target | None | None | None | EXACT_MATCH |
| take_profit | None | None | None | EXACT_MATCH |
| stop_loss | None | None | None | EXACT_MATCH |
| sl_price | None | None | None | EXACT_MATCH |
| tp_price | None | None | None | EXACT_MATCH |
| sl_percentage | None | None | None | EXACT_MATCH |
| tp_percentage | None | None | None | EXACT_MATCH |
| min_price_change_pct | None | None | None | EXACT_MATCH |
| alert_cooldown_minutes | None | None | None | EXACT_MATCH |
| trade_amount_usd | None | None | None | EXACT_MATCH |
| alert_enabled | None | None | None | EXACT_MATCH |
| buy_alert_enabled | None | None | None | EXACT_MATCH |
| sell_alert_enabled | None | None | None | EXACT_MATCH |
| trade_enabled | 1 | None | None | MISMATCH |
| trade_on_margin | 0 | None | None | EXACT_MATCH |
| sold | 0 | None | None | EXACT_MATCH |
| is_deleted | None | None | None | EXACT_MATCH |
| skip_sl_tp_reminder | None | None | None | EXACT_MATCH |
| sl_tp_mode | conservative | None | None | MISMATCH |
| order_status | PENDING | None | None | MISMATCH |
| exchange | CRYPTO_COM | None | None | MISMATCH |
| alert_enabled | None | None | None | MATCH |
| buy_alert_enabled | None | None | None | MATCH |
| sell_alert_enabled | None | None | None | MATCH |

### BONK_USD

**Status:** HAS_ISSUES

**Backend Query Time:** 1.444s

| Field | DB | API | Computed | Classification |
|-------|----|-----|----------|----------------|
| price | None | None | 0.000010 | MISMATCH |
| rsi | None | None | 32.1000 | MISMATCH |
| ma50 | None | None | 0.000009 | MISMATCH |
| ma200 | None | None | 0.000010 | MISMATCH |
| ema10 | None | None | 0.000009 | MISMATCH |
| atr | None | None | None | EXACT_MATCH |
| buy_target | None | None | None | EXACT_MATCH |
| take_profit | None | None | None | EXACT_MATCH |
| stop_loss | None | None | None | EXACT_MATCH |
| sl_price | None | None | None | EXACT_MATCH |
| tp_price | None | None | None | EXACT_MATCH |
| sl_percentage | None | None | None | EXACT_MATCH |
| tp_percentage | None | None | None | EXACT_MATCH |
| min_price_change_pct | None | None | None | EXACT_MATCH |
| alert_cooldown_minutes | None | None | None | EXACT_MATCH |
| trade_amount_usd | None | None | None | EXACT_MATCH |
| alert_enabled | None | None | None | EXACT_MATCH |
| buy_alert_enabled | None | None | None | EXACT_MATCH |
| sell_alert_enabled | None | None | None | EXACT_MATCH |
| trade_enabled | None | None | None | EXACT_MATCH |
| trade_on_margin | None | None | None | EXACT_MATCH |
| sold | None | None | None | EXACT_MATCH |
| is_deleted | None | None | None | EXACT_MATCH |
| skip_sl_tp_reminder | None | None | None | EXACT_MATCH |
| sl_tp_mode | None | None | None | EXACT_MATCH |
| order_status | None | None | None | EXACT_MATCH |
| exchange | CRYPTO_COM | None | None | MISMATCH |
| throttle_buy | None | None | None | BACKEND_ONLY |
| throttle_sell | None | None | None | BACKEND_ONLY |
| alert_enabled | None | None | None | MATCH |
| buy_alert_enabled | None | None | None | MATCH |
| sell_alert_enabled | None | None | None | MATCH |

**Computed Strategy Info:**
- Preset: swing-Aggressive
- Strategy Key: swing:aggressive
- Decision: WAIT
- Index: None
- Buy Signal: False
- Sell Signal: False


## Logs Used

- **Run timestamp:** 2025-12-03T12:57:44.271596+00:00
- **Backend query time:** 0.075s (average)

