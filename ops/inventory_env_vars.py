#!/usr/bin/env python3
"""
Inventory of required runtime env vars for ATP AWS deployment (docker-compose --profile aws).
Used for post-compromise secret rotation and rebuild. Output: table + optional template.
Run from repo root: python3 ops/inventory_env_vars.py
"""

import os
import sys
from pathlib import Path

# Canonical list: (ENV_VAR, Purpose, Where_used, Rotate?, How_to_obtain)
ENV_INVENTORY = [
    # Database (db, backend-aws, market-updater-aws)
    ("POSTGRES_DB", "PostgreSQL database name", "docker-compose.yml (db, aws-backup)", "NO", "Reuse: atp (identifier only)"),
    ("POSTGRES_USER", "PostgreSQL username", "docker-compose.yml (db, aws-backup)", "OPTIONAL", "Reuse 'trader' or new user"),
    ("POSTGRES_PASSWORD", "PostgreSQL password", "docker-compose.yml; backend config", "YES", "Generate: openssl rand -hex 32"),
    ("DATABASE_URL", "Full DB connection string", "backend/app/core/config.py, environment", "YES", "Build from POSTGRES_USER/PASSWORD/DB and host db:5432"),
    # Security / backend
    ("SECRET_KEY", "Backend session/signing key (JWT etc.)", "backend/app/core/config.py", "YES", "Generate: openssl rand -hex 32"),
    ("ADMIN_ACTIONS_KEY", "Admin/protected actions (portfolio whoami, etc.)", "backend/app/api/routes_portfolio.py; routes_monitoring.py; render_runtime_env.sh", "YES", "Generate: openssl rand -hex 32"),
    ("DIAGNOSTICS_API_KEY", "X-Diagnostics-Key for monitoring endpoints", "backend/app/api/routes_monitoring.py; routes_diag.py; render_runtime_env.sh", "YES", "Generate: openssl rand -hex 32 (or same as ADMIN_ACTIONS_KEY)"),
    ("ENABLE_DIAGNOSTICS_ENDPOINTS", "Enable diagnostics routes (0/1)", "backend/app/api/routes_monitoring.py", "NO", "Set 1 in production with key"),
    # Telegram (backend-aws, market-updater-aws). Deprecated: TELEGRAM_BOT_TOKEN (plaintext) not supported.
    ("TELEGRAM_BOT_TOKEN_ENCRYPTED", "Telegram bot token encrypted (AWS prod)", "backend services; telegram_secrets.py; render_runtime_env.sh", "YES", "Run scripts/setup_telegram_token.py; use TELEGRAM_KEY_FILE for decrypt"),
    ("TELEGRAM_CHAT_ID", "Telegram channel/chat ID (AWS prod)", "backend services; telegram_commands.py; render_runtime_env.sh", "NO", "Reuse same chat_id (identifier); rotate if channel compromised"),
    ("TELEGRAM_AUTH_USER_ID", "Optional: allowed user ID(s) for bot commands", "backend/app/services/telegram_commands.py", "NO", "Reuse or leave empty"),
    ("TELEGRAM_ALERT_BOT_TOKEN", "Telegram for Alertmanager (Prometheus alerts)", "scripts/aws/observability/telegram-alerts/server.py", "YES", "Separate bot or same as prod (encrypted)"),
    ("TELEGRAM_ALERT_CHAT_ID", "Chat ID for Alertmanager alerts", "scripts/aws/observability/telegram-alerts/server.py", "NO", "Reuse same TELEGRAM_CHAT_ID or separate channel"),
    ("TELEGRAM_ATP_CONTROL_BOT_TOKEN", "ATP Control bot (@ATP_control_bot): tasks, approvals, investigations", "backend/app/services/claw_telegram.py", "NO", "ATP Control bot token; fallback TELEGRAM_CLAW_BOT_TOKEN"),
    ("TELEGRAM_ATP_CONTROL_CHAT_ID", "ATP Control channel for tasks, approvals, needs revision", "backend/app/services/claw_telegram.py", "NO", "ATP Control channel; fallback TELEGRAM_CLAW_CHAT_ID"),
    ("TELEGRAM_CLAW_BOT_TOKEN", "Claw bot (@Claw_cruz_bot): control plane, /task /help (fallback for ATP)", "backend/app/services/claw_telegram.py", "NO", "Claw bot token; used when ATP_CONTROL_* unset"),
    ("TELEGRAM_CLAW_CHAT_ID", "Claw channel (fallback for ATP Control)", "backend/app/services/claw_telegram.py", "NO", "Claw channel; used when ATP_CONTROL_* unset"),
    # Crypto.com Exchange
    ("EXCHANGE_CUSTOM_API_KEY", "Crypto.com Exchange API key", "backend routes_internal, portfolio, diag, verify_credentials, etc.", "YES", "Rotate in Crypto.com Exchange UI; create new API key"),
    ("EXCHANGE_CUSTOM_API_SECRET", "Crypto.com Exchange API secret", "backend routes_internal, portfolio, diag, verify_credentials", "YES", "From Exchange when creating new API key"),
    ("EXCHANGE_CUSTOM_BASE_URL", "Crypto.com API base URL", "backend multiple", "NO", "Reuse: https://api.crypto.com/exchange/v1"),
    ("AWS_INSTANCE_IP", "Elastic IP for Crypto.com IP whitelist", "backend diagnose_auth_issue; .env.aws", "NO", "Set to new EC2 Elastic IP after deploy"),
    # URLs (non-secret)
    ("API_BASE_URL", "Backend API URL (internal)", "docker-compose backend-aws: http://backend-aws:8002", "NO", "Set http://backend-aws:8002 for compose"),
    ("FRONTEND_URL", "Public frontend URL for CORS", "backend/core/environment.py; docker-compose", "NO", "e.g. https://dashboard.hilovivo.com"),
    ("NEXT_PUBLIC_API_URL", "Frontend API path (build-time)", "frontend; docker-compose frontend-aws: /api", "NO", "Set /api for production"),
    ("NEXT_PUBLIC_ENVIRONMENT", "Frontend env label", "frontend; docker-compose", "NO", "Set aws"),
    # Optional / feature flags
    ("GRAFANA_ADMIN_USER", "Grafana admin username", "docker-compose grafana", "OPTIONAL", "Reuse or new; set password via GF_SECURITY_ADMIN_PASSWORD if desired"),
    ("GITHUB_TOKEN", "Optional: for monitoring/deploy workflows", "backend/app/api/routes_monitoring.py", "OPTIONAL", "Only if using GitHub deploy checks; rotate if was on host"),
    ("RUN_TELEGRAM", "Enable Telegram sending", "backend, render_runtime_env", "NO", "true for AWS"),
    ("ENVIRONMENT", "Environment name", "backend; compose", "NO", "aws"),
    ("APP_ENV", "App environment for alert routing", "backend; compose", "NO", "aws"),
]

def main():
    repo_root = Path(__file__).resolve().parent.parent
    os.chdir(repo_root)

    if len(sys.argv) > 1 and sys.argv[1] == "--template":
        # Emit template lines only (for ops/atp.env.template refresh)
        for var, _purpose, _where, _rot, how in ENV_INVENTORY:
            if how.startswith("Generate"):
                val = "__GENERATE__"
            elif "BotFather" in how or "bot" in how.lower():
                val = "__FROM_BOTFATHER__"
            elif "Exchange" in how or "Crypto.com" in how:
                val = "__ROTATE_IN_EXCHANGE__"
            elif "Reuse" in how and "chat" in how.lower():
                val = "__REUSE_CHAT_ID__"
            elif "Reuse" in how and "atp" in how:
                val = "atp"
            elif "Reuse" in how and "trader" in how:
                val = "trader"
            elif "Elastic IP" in how:
                val = "__NEW_EC2_ELASTIC_IP__"
            elif "http" in how or "URL" in var:
                val = "__SET_PUBLIC_URL__"
            elif var in ("ENABLE_DIAGNOSTICS_ENDPOINTS", "RUN_TELEGRAM", "ENVIRONMENT", "APP_ENV", "NEXT_PUBLIC_API_URL", "NEXT_PUBLIC_ENVIRONMENT"):
                val = "1" if "ENABLE" in var or "RUN" in var else ("aws" if "ENV" in var or "ENVIRONMENT" in var else "/api")
            else:
                val = "__SET_OR_GENERATE__"
            print(f"{var}={val}")
        return

    # Table output
    col_var = 24
    col_purpose = 42
    col_where = 50
    col_rotate = 8
    col_how = 44
    sep = "|"
    print("Required runtime env vars for ATP AWS profile (post-compromise rotation)")
    print("=" * (col_var + col_purpose + col_where + col_rotate + col_how + 4 * len(sep)))
    print(f"{'ENV var':<{col_var}} {sep} {'Purpose':<{col_purpose}} {sep} {'Where used':<{col_where}} {sep} {'Rotate?':<{col_rotate}} {sep} {'How to obtain':<{col_how}}")
    print("-" * (col_var + col_purpose + col_where + col_rotate + col_how + 4 * len(sep)))
    for var, purpose, where_used, rotate, how in ENV_INVENTORY:
        print(f"{var:<{col_var}} {sep} {purpose[:col_purpose-1]:<{col_purpose}} {sep} {where_used[:col_where-1]:<{col_where}} {sep} {rotate:<{col_rotate}} {sep} {how[:col_how-1]:<{col_how}}")
    print("=" * (col_var + col_purpose + col_where + col_rotate + col_how + 4 * len(sep)))
    print("\nSecrets: store in /opt/atp/atp.env on new EC2 (chmod 600). Never paste secrets in chat.")


if __name__ == "__main__":
    main()
