#!/bin/sh
# OpenClaw wrapper entrypoint: ensure gateway.controlUi.allowedOrigins is set
# so the gateway starts when running behind a reverse proxy (non-loopback).
# Creates ~/.openclaw/openclaw.json if missing; OPENCLAW_ALLOWED_ORIGINS overrides.
# Do not disable security; do not use dangerouslyAllowHostHeaderOriginFallback.

set -e

# python3 exists but many scripts expect "python"; create symlink in writable tmpfs
if command -v python3 >/dev/null 2>&1 && ! command -v python >/dev/null 2>&1; then
  ln -sf "$(command -v python3)" /tmp/python
  export PATH="/tmp:$PATH"
fi

# Default origins (used when env is not set)
DEFAULT_ORIGINS='["https://dashboard.hilovivo.com","http://localhost:18789","http://127.0.0.1:18789"]'

# Config dir: OPENCLAW_CONFIG_HOME (default /tmp/.openclaw for tmpfs) or HOME/.openclaw
OPENCLAW_DIR="${OPENCLAW_CONFIG_HOME:-$HOME/.openclaw}"
mkdir -p "$OPENCLAW_DIR"
# So gateway reads from same path, set for child process
export OPENCLAW_CONFIG_HOME="$OPENCLAW_DIR"
export HOME="${HOME:-/tmp}"

# Build allowedOrigins: from env (comma-separated) or default
if [ -n "$OPENCLAW_ALLOWED_ORIGINS" ]; then
  # Build JSON array from comma-separated list (no spaces in origins assumed)
  ORIGINS_JSON="["
  FIRST=1
  IFS=','
  for o in $OPENCLAW_ALLOWED_ORIGINS; do
    trim=$(echo "$o" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    [ -z "$trim" ] && continue
    [ $FIRST -eq 1 ] && FIRST=0 || ORIGINS_JSON="$ORIGINS_JSON,"
    ORIGINS_JSON="$ORIGINS_JSON\"$trim\""
  done
  ORIGINS_JSON="$ORIGINS_JSON]"
else
  ORIGINS_JSON="$DEFAULT_ORIGINS"
fi

# Write config file (merge with existing if present to avoid wiping other keys)
CONFIG_FILE="$OPENCLAW_DIR/openclaw.json"
ORIGINS_FILE="${TMPDIR:-/tmp}/openclaw-origins.$$.json"
echo "$ORIGINS_JSON" > "$ORIGINS_FILE"

PROXIES_JSON="[]"
if [ -n "$OPENCLAW_TRUSTED_PROXIES" ]; then
  PROXIES_JSON="["
  PF=1
  IFS=','
  for p in $OPENCLAW_TRUSTED_PROXIES; do
    tp=$(echo "$p" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    [ -z "$tp" ] && continue
    [ $PF -eq 1 ] && PF=0 || PROXIES_JSON="$PROXIES_JSON,"
    PROXIES_JSON="$PROXIES_JSON\"$tp\""
  done
  PROXIES_JSON="$PROXIES_JSON]"
fi

ENABLE_HTTP_RESPONSES="${OPENCLAW_HTTP_RESPONSES:-true}"

# ACP default agent for Cursor/Codex integration (sessions_spawn needs agentId or acp.defaultAgent)
ACP_DEFAULT_AGENT="${OPENCLAW_ACP_DEFAULT_AGENT:-codex}"

# Cheap-first during stabilization. Gateway must honor request-body "model"; see docs/GATEWAY_MODEL_ROUTING_AND_FAILOVER_COMPATIBILITY.md
MODEL_PRIMARY="${OPENCLAW_MODEL_PRIMARY:-openai/gpt-4o-mini}"
MODEL_FALLBACKS="${OPENCLAW_MODEL_FALLBACKS:-anthropic/claude-3-5-haiku-20241022,anthropic/claude-3-5-sonnet-20241022,openai/gpt-4o,anthropic/claude-sonnet-4-20250514}"
FALLBACKS_JSON="["
FF=1
OLDIFS="$IFS"; IFS=','
for fb in $MODEL_FALLBACKS; do
  tfb=$(echo "$fb" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
  [ -z "$tfb" ] && continue
  [ $FF -eq 1 ] && FF=0 || FALLBACKS_JSON="$FALLBACKS_JSON,"
  FALLBACKS_JSON="$FALLBACKS_JSON\"$tfb\""
done
IFS="$OLDIFS"
FALLBACKS_JSON="$FALLBACKS_JSON]"

if [ -f "$CONFIG_FILE" ]; then
  if command -v node >/dev/null 2>&1; then
    node -e "
      const fs = require('fs');
      const cfgPath = process.argv[1];
      const originsPath = process.argv[2];
      const proxies = JSON.parse(process.argv[3]);
      const primary = process.argv[4];
      const fallbacks = JSON.parse(process.argv[5]);
      const enableHttpResponses = process.argv[6] === 'true';
      const acpDefaultAgent = process.argv[7];
      const orig = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
      const origins = JSON.parse(fs.readFileSync(originsPath, 'utf8'));
      if (!orig.gateway) orig.gateway = {};
      if (!orig.gateway.controlUi) orig.gateway.controlUi = {};
      orig.gateway.controlUi.allowedOrigins = origins;
      if (proxies.length > 0) orig.gateway.trustedProxies = proxies;
      if (enableHttpResponses) {
        if (!orig.gateway.http) orig.gateway.http = {};
        if (!orig.gateway.http.endpoints) orig.gateway.http.endpoints = {};
        if (!orig.gateway.http.endpoints.responses) orig.gateway.http.endpoints.responses = {};
        orig.gateway.http.endpoints.responses.enabled = true;
      }
      if (!orig.agents) orig.agents = {};
      if (!orig.agents.defaults) orig.agents.defaults = {};
      orig.agents.defaults.model = { primary, fallbacks };
      if (acpDefaultAgent) {
        if (!orig.acp) orig.acp = {};
        orig.acp.defaultAgent = acpDefaultAgent;
      }
      fs.writeFileSync(cfgPath, JSON.stringify(orig, null, 2));
    " "$CONFIG_FILE" "$ORIGINS_FILE" "$PROXIES_JSON" "$MODEL_PRIMARY" "$FALLBACKS_JSON" "$ENABLE_HTTP_RESPONSES" "$ACP_DEFAULT_AGENT"
  else
    if [ "$ENABLE_HTTP_RESPONSES" = "true" ]; then
      printf '%s\n' "{\"gateway\":{\"controlUi\":{\"allowedOrigins\":$ORIGINS_JSON},\"trustedProxies\":$PROXIES_JSON,\"http\":{\"endpoints\":{\"responses\":{\"enabled\":true}}}},\"agents\":{\"defaults\":{\"model\":{\"primary\":\"$MODEL_PRIMARY\",\"fallbacks\":$FALLBACKS_JSON}}},\"acp\":{\"defaultAgent\":\"$ACP_DEFAULT_AGENT\"}}" > "$CONFIG_FILE"
    else
      printf '%s\n' "{\"gateway\":{\"controlUi\":{\"allowedOrigins\":$ORIGINS_JSON},\"trustedProxies\":$PROXIES_JSON},\"agents\":{\"defaults\":{\"model\":{\"primary\":\"$MODEL_PRIMARY\",\"fallbacks\":$FALLBACKS_JSON}}},\"acp\":{\"defaultAgent\":\"$ACP_DEFAULT_AGENT\"}}" > "$CONFIG_FILE"
    fi
  fi
else
  if [ "$ENABLE_HTTP_RESPONSES" = "true" ]; then
    printf '%s\n' "{\"gateway\":{\"controlUi\":{\"allowedOrigins\":$ORIGINS_JSON},\"trustedProxies\":$PROXIES_JSON,\"http\":{\"endpoints\":{\"responses\":{\"enabled\":true}}}},\"agents\":{\"defaults\":{\"model\":{\"primary\":\"$MODEL_PRIMARY\",\"fallbacks\":$FALLBACKS_JSON}}},\"acp\":{\"defaultAgent\":\"$ACP_DEFAULT_AGENT\"}}" > "$CONFIG_FILE"
  else
    printf '%s\n' "{\"gateway\":{\"controlUi\":{\"allowedOrigins\":$ORIGINS_JSON},\"trustedProxies\":$PROXIES_JSON},\"agents\":{\"defaults\":{\"model\":{\"primary\":\"$MODEL_PRIMARY\",\"fallbacks\":$FALLBACKS_JSON}}},\"acp\":{\"defaultAgent\":\"$ACP_DEFAULT_AGENT\"}}" > "$CONFIG_FILE"
  fi
fi
rm -f "$ORIGINS_FILE"

# Log that allowedOrigins was loaded (count only; no secrets)
if command -v node >/dev/null 2>&1; then
  COUNT=$(node -e "try { console.log(JSON.parse('$ORIGINS_JSON').length); } catch(e) { console.log(0); }" 2>/dev/null || echo "?")
else
  COUNT="?"
fi
echo "[openclaw-entrypoint] gateway.controlUi.allowedOrigins loaded ($COUNT origins)" 1>&2
echo "[openclaw-entrypoint] acp.defaultAgent=$ACP_DEFAULT_AGENT (Cursor/ACP integration)" 1>&2

exec "$@"
