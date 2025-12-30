# ENV-Based Telegram Kill Switch - Summary

## Problem
Multiple backend processes were sending Telegram alerts simultaneously, causing duplicate notifications.

## Solution
Implemented an environment-level kill switch that ensures Telegram messages are **ONLY** sent when `ENV=aws`. All other environments (local, test, etc.) are blocked at the central gatekeeper.

## Changes Made

### File: `backend/app/services/telegram_notifier.py`

1. **Simplified `__init__` method:**
   - Removed complex `RUN_TELEGRAM` and `RUNTIME_ORIGIN` checks
   - Simple check: `telegram_enabled = (env_value == "aws")`
   - `self.enabled = telegram_enabled AND credentials_present`
   - Added startup logging: `ENV`, `hostname`, `pid`, `telegram_enabled`

2. **Central guard in `send_message()`:**
   - Early return if `self.enabled == False`
   - Removed complex origin-based blocking logic
   - Single source of truth: `self.enabled` (set only when `ENV=aws`)

3. **Startup logging:**
   - Logs: `[TELEGRAM_STARTUP] ENV=... hostname=... pid=... telegram_enabled=...`
   - Makes it immediately clear if Telegram is enabled/disabled

## How It Works

1. **Initialization:**
   - Checks `ENVIRONMENT` or `APP_ENV` environment variable
   - If `ENV != "aws"` → `telegram_enabled = False`
   - If `ENV == "aws"` AND credentials present → `telegram_enabled = True`
   - Logs startup state

2. **Message sending:**
   - `send_message()` checks `self.enabled` FIRST
   - If `False` → log and return `False` (no Telegram API call)
   - If `True` → proceed with sending (ENV=aws guaranteed)

## Guarantees

- **Local/Test environments:** `ENV != "aws"` → `self.enabled = False` → NO Telegram messages sent
- **AWS environment:** `ENV == "aws"` AND credentials → `self.enabled = True` → Messages sent
- **Single execution gate:** All Telegram sends go through `send_message()` → one central check
- **Architecturally impossible to bypass:** `self.enabled` is set once at initialization, all sends check it

## Validation

- With `ENV=local` → `telegram_enabled=False` → zero Telegram messages
- With `ENV=aws` → `telegram_enabled=True` → messages sent (one per real fill)
- Restarting containers → same behavior (ENV variable persists)

## Deployment

Ensure `ENVIRONMENT=aws` (or `APP_ENV=aws`) is set in docker-compose.yml for the AWS backend service.

