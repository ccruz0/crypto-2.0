# Crypto.com Exchange API

How the platform connects to Crypto.com Exchange: configuration, modes, and production (AWS) setup.

---

## Overview

- The backend talks to **Crypto.com Exchange API v1** (`https://api.crypto.com/exchange/v1`).
- **Production (AWS)**: Direct connection from EC2; backend uses the instance’s **Elastic IP**, which must be **whitelisted** in the Crypto.com API key settings.
- No VPN or proxy is required in the standard AWS setup.

---

## Connection Modes

| Mode | Use | Config |
|------|-----|--------|
| **Direct** | Production (AWS) and local dev with whitelisted IP | `USE_CRYPTO_PROXY=false` |
| **Proxy** | Local dev through a proxy that holds credentials | `USE_CRYPTO_PROXY=true`, `CRYPTO_PROXY_URL`, `CRYPTO_PROXY_TOKEN` |
| **Dry-run** | Testing without real exchange | `LIVE_TRADING=false` |

---

## Production (AWS) — Standard configuration

On EC2, use **direct** connection and the **AWS Elastic IP** whitelisted in Crypto.com:

1. **Crypto.com Exchange** → API Keys → Whitelist the current **PROD** public IP (or Elastic IP). See [AWS_PROD_QUICK_REFERENCE.md](../aws/AWS_PROD_QUICK_REFERENCE.md) for instance details; IP can be found in EC2 console.

2. **Environment** (e.g. `.env.aws` / `secrets/runtime.env` on EC2):

   ```bash
   USE_CRYPTO_PROXY=false
   LIVE_TRADING=true
   EXCHANGE_CUSTOM_API_KEY=<your_api_key>
   EXCHANGE_CUSTOM_API_SECRET=<your_api_secret>
   EXCHANGE_CUSTOM_BASE_URL=https://api.crypto.com/exchange/v1
   ```

3. Backend reads these and uses them for all exchange calls (orders, balance, history).

Full AWS-specific steps and troubleshooting: [AWS_CRYPTO_COM_CONNECTION.md](../AWS_CRYPTO_COM_CONNECTION.md).

---

## API key permissions (Crypto.com)

- **Read** — Balances, orders, history.
- **Trade** — Place and cancel orders (required for live trading).
- **Transfer** — Optional; only if the app does transfers.

---

## Backend usage

- **CryptoComTrade** (`backend/app/services/brokers/crypto_com_trade.py`) is the exchange client used for order placement and sync.
- **ExchangeSyncService** uses the same credentials to sync open orders and order/trade history.

---

## Related

- [AWS → Crypto.com connection](../AWS_CRYPTO_COM_CONNECTION.md)
- [CRYPTO_COM_SETUP.md](../../CRYPTO_COM_SETUP.md) (root) — Detailed setup and proxy/dry-run
- [Infrastructure (AWS)](../infrastructure/aws-setup.md)
