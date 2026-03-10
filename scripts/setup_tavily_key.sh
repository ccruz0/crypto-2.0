#!/usr/bin/env bash
# Store Tavily API key in secrets/runtime.env for OpenClaw web search.
# Run once (or to rotate the key). Key is prompted via hidden input; never hardcoded.
# Requires: secrets/runtime.env so docker-compose.openclaw.yml can load it.
set -e

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$REPO_ROOT"

echo "Tavily API key is used by OpenClaw for web search. Get a key at https://tavily.com"
echo ""
read -s -p "Paste your Tavily API key (Enter to skip/leave empty): " TAVILY_API_KEY
echo ""

mkdir -p secrets
RUNTIME_ENV="secrets/runtime.env"

# Ensure file exists (Docker Compose requires it when listed in env_file)
touch "$RUNTIME_ENV"

# Update or append TAVILY_API_KEY (use printf so key is not interpreted)
if grep -q "^TAVILY_API_KEY=" "$RUNTIME_ENV" 2>/dev/null; then
  tmp=$(mktemp)
  grep -v "^TAVILY_API_KEY=" "$RUNTIME_ENV" > "$tmp" || true
  printf 'TAVILY_API_KEY=%s\n' "$TAVILY_API_KEY" >> "$tmp"
  mv "$tmp" "$RUNTIME_ENV"
else
  printf 'TAVILY_API_KEY=%s\n' "$TAVILY_API_KEY" >> "$RUNTIME_ENV"
fi

# Set default search provider to tavily
if grep -q "^SEARCH_PROVIDER=" "$RUNTIME_ENV" 2>/dev/null; then
  tmp=$(mktemp)
  grep -v "^SEARCH_PROVIDER=" "$RUNTIME_ENV" > "$tmp" || true
  echo "SEARCH_PROVIDER=tavily" >> "$tmp"
  mv "$tmp" "$RUNTIME_ENV"
else
  echo "SEARCH_PROVIDER=tavily" >> "$RUNTIME_ENV"
fi

echo ""
echo "Saved to $RUNTIME_ENV (TAVILY_API_KEY and SEARCH_PROVIDER=tavily)."
echo "Restart OpenClaw to apply: docker compose -f docker-compose.openclaw.yml restart openclaw"
echo "Verify: docker compose -f docker-compose.openclaw.yml exec openclaw printenv | grep -E 'TAVILY|SEARCH'"
