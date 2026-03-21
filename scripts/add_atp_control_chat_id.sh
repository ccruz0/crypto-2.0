#!/usr/bin/env bash
# Add TELEGRAM_ATP_CONTROL_CHAT_ID to secrets/runtime.env for ATP Control channel authorization.
# Use the chat_id from [TG][AUTH][DENY] logs after sending /menu from the ATP Control Alerts channel.
#
# Usage: ./scripts/add_atp_control_chat_id.sh <chat_id>
# Example: ./scripts/add_atp_control_chat_id.sh -1001234567890

set -e
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/secrets/runtime.env"
CHAT_ID="${1:-}"

if [[ -z "$CHAT_ID" ]]; then
  echo "Usage: $0 <chat_id>" >&2
  echo "" >&2
  echo "Get chat_id from backend logs after sending /menu from ATP Control Alerts channel:" >&2
  echo "  Look for: [TG][AUTH][DENY] chat_id=... chat_type=... chat_title=..." >&2
  echo "" >&2
  echo "Example: $0 -1001234567890" >&2
  exit 1
fi

# Normalize: strip quotes/whitespace
CHAT_ID=$(echo "$CHAT_ID" | sed -e 's/^[[:space:]"'\'']*//' -e 's/[[:space:]"'\'']*$//')
[[ -z "$CHAT_ID" ]] && { echo "Empty chat_id. No change made." >&2; exit 1; }

mkdir -p "$(dirname "$ENV_FILE")"
if [[ -f "$ENV_FILE" ]]; then
  if grep -q "^[[:space:]]*TELEGRAM_ATP_CONTROL_CHAT_ID=" "$ENV_FILE" 2>/dev/null; then
    if [[ "$(uname)" == "Darwin" ]]; then
      sed -i '' "s|^[[:space:]]*TELEGRAM_ATP_CONTROL_CHAT_ID=.*|TELEGRAM_ATP_CONTROL_CHAT_ID=$CHAT_ID|" "$ENV_FILE"
    else
      sed -i "s|^[[:space:]]*TELEGRAM_ATP_CONTROL_CHAT_ID=.*|TELEGRAM_ATP_CONTROL_CHAT_ID=$CHAT_ID|" "$ENV_FILE"
    fi
  else
    echo "TELEGRAM_ATP_CONTROL_CHAT_ID=$CHAT_ID" >> "$ENV_FILE"
  fi
else
  echo "TELEGRAM_ATP_CONTROL_CHAT_ID=$CHAT_ID" >> "$ENV_FILE"
fi

echo "Updated secrets/runtime.env: TELEGRAM_ATP_CONTROL_CHAT_ID=$CHAT_ID"
echo ""
echo "Next steps:"
echo "  1. Restart backend: docker compose --profile aws restart backend-aws"
echo "     (or for local: docker compose --profile local restart backend-dev)"
echo "  2. Send /menu from ATP Control Alerts channel"
echo "  3. Confirm bot shows main menu (not 'Not authorized')"
echo ""
echo "For AWS (.env.aws): add TELEGRAM_ATP_CONTROL_CHAT_ID=$CHAT_ID to .env.aws on EC2,"
echo "then run: bash scripts/aws/render_runtime_env.sh && docker compose --profile aws restart backend-aws"
