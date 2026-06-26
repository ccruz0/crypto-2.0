# Code vs Docs Audit — 2025-12-25

## Inconsistencies

1) **Env vars template omits runtime config (Blocking)**  
   - **Docs**: `README.md` points to `.env.example` as the env var template, but the file only listed ports/DB user fields.  
   - **Code**: `backend/app/core/config.py` and services require `SECRET_KEY`, `APP_ENV`, `RUN_TELEGRAM`, `RUNTIME_ORIGIN`, `LIVE_TRADING`, Telegram tokens, Redis URL, exchange credentials, and proxy settings.  
   - **Impact**: Production/local setups would miss mandatory secrets and runtime guards, leading to insecure defaults or broken Telegram/crypto connectivity.  
   - **Fix**: Expanded `.env.example` with the required runtime, security, exchange, Telegram, Redis, and proxy variables.  
   - **Files**: `.env.example`

2) **MA50/EMA10 gating for alerts vs orders (Risky)**  
   - **Docs**: `docs/ALERTAS_Y_ORDENES_NORMAS.md` stated alerts are sent even if MA50/EMA10 are missing, only blocking order creation.  
   - **Code**: `backend/app/services/signal_monitor.py` cancels the signal when MA50/EMA10 are missing (no alert, no order), logging a warning.  
   - **Impact**: Operators expect alerts to fire with missing MAs per docs; system actually suppresses them to avoid invalid signals.  
   - **Fix**: Updated the norms doc to describe the implemented behavior (signals aborted when MAs are missing).  
   - **Files**: `docs/ALERTAS_Y_ORDENES_NORMAS.md`

## Notes
- Tests not run (repo-wide suite is large; changes are documentation/template-only).
