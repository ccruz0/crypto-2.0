#!/usr/bin/env bash
# Generate values for ATP secrets (post-compromise rotation).
# Output: print to terminal only. Never commit; paste into /opt/atp/atp.env on EC2.
# Run locally: ./ops/generate_secrets.sh
set -euo pipefail

echo "=== ATP secret generation (paste into /opt/atp/atp.env on NEW EC2) ==="
echo ""
echo "# --- Generated values (copy lines below into /opt/atp/atp.env; do not paste in chat) ---"
echo "POSTGRES_PASSWORD=$(openssl rand -hex 32)"
echo "SECRET_KEY=$(openssl rand -hex 32)"
echo "ADMIN_ACTIONS_KEY=$(openssl rand -hex 32)"
echo "DIAGNOSTICS_API_KEY=$(openssl rand -hex 32)"
echo "GF_SECURITY_ADMIN_PASSWORD=$(openssl rand -hex 24)"
echo "# --- End generated; add TELEGRAM_* and EXCHANGE_* via BotFather / Crypto.com UI ---"
