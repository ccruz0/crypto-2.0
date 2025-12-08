# Trading Config - Deprecated

**This file has been deprecated.**

The authoritative trading configuration is located at:
- **`backend/trading_config.json`** - Used by the backend application

This root-level `trading_config.json` file is kept for backward compatibility but is **not actively used** by the system.

## Migration

If you need to reference trading pairs or configuration:
- Use `backend/trading_config.json` for backend configuration
- The backend service automatically loads from `backend/trading_config.json` or `/app/trading_config.json` in containers

## Audit

To verify no duplicate trading pairs exist:
```bash
python3 scripts/audit_pairs_focused.py
```
