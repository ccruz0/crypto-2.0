#!/usr/bin/env bash
# Enable the Tavily plugin in OpenClaw so Lilo sees tavily_search and related tools.
# Run on the LAB host (where OpenClaw runs). Requires: TAVILY_API_KEY already in
# secrets/runtime.env (use scripts/setup_tavily_key.sh or setup_tavily_key_popup.py first).
#
# Usage (on LAB):
#   cd /home/ubuntu/crypto-2.0
#   sudo bash scripts/openclaw/enable_tavily_plugin.sh
#
# What this does:
#   1. Installs openclaw-tavily plugin inside the container (into mounted home-data).
#   2. Merges plugin enable + tools.allow into openclaw.json on the host.
#   3. Restarts OpenClaw.

set -e

REPO_ROOT="${REPO_ROOT:-/home/ubuntu/crypto-2.0}"
OPENCLAW_HOME="${OPENCLAW_HOME:-/opt/openclaw/home-data}"
CONFIG_FILE="${OPENCLAW_HOME}/openclaw.json"

cd "$REPO_ROOT"

echo "=== 1) Install openclaw-tavily plugin ==="
EXTENSIONS_DIR="${OPENCLAW_HOME}/extensions"
PLUGIN_DIR="${EXTENSIONS_DIR}/openclaw-tavily"
mkdir -p "$EXTENSIONS_DIR"

install_via_cli() {
  docker compose -f docker-compose.openclaw.yml exec -T openclaw sh -c "command -v openclaw >/dev/null 2>&1 && openclaw plugins install openclaw-tavily" 2>/dev/null
}

install_via_host_npm() {
  if ! command -v npm >/dev/null 2>&1; then return 1; fi
  local tmpdir
  tmpdir=$(mktemp -d)
  (cd "$tmpdir" && npm pack openclaw-tavily 2>/dev/null) || { rm -rf "$tmpdir"; return 1; }
  local tarball
  tarball=$(ls "$tmpdir"/openclaw-tavily-*.tgz 2>/dev/null | head -1)
  if [ -z "$tarball" ] || [ ! -f "$tarball" ]; then rm -rf "$tmpdir"; return 1; fi
  mkdir -p "$PLUGIN_DIR"
  tar -xzf "$tarball" -C "$PLUGIN_DIR" --strip-components=1
  (cd "$PLUGIN_DIR" && npm install --omit=dev 2>/dev/null) || true
  rm -rf "$tmpdir"
  # Container runs as 1000:1000; ensure plugin dir is readable
  if command -v chown >/dev/null 2>&1; then chown -R 1000:1000 "$PLUGIN_DIR" 2>/dev/null || true; fi
  return 0
}

if [ -d "$PLUGIN_DIR" ] && [ -f "$PLUGIN_DIR/package.json" ]; then
  echo "Plugin already present at $PLUGIN_DIR."
elif install_via_cli; then
  echo "Plugin installed via openclaw CLI."
elif install_via_host_npm; then
  echo "Plugin installed via host npm into $PLUGIN_DIR."
else
  echo "Could not install plugin. Try: (1) Ensure OpenClaw container is running, (2) Install node/npm on host and re-run."
  echo "See: docs/openclaw/TAVILY_PLUGIN_FIX.md"
  exit 1
fi

echo ""
echo "=== 2) Merge Tavily plugin config into openclaw.json ==="
mkdir -p "$OPENCLAW_HOME"

# Merge: plugins.entries["openclaw-tavily"] = { enabled: true }, tools.allow += tavily tools
merge_config() {
  local f="$1"
  if [ ! -f "$f" ]; then
    printf '%s\n' '{
  "plugins": { "entries": { "openclaw-tavily": { "enabled": true } } },
  "tools": { "allow": ["tavily_search", "tavily_extract", "tavily_crawl", "tavily_map", "tavily_research"] }
}' > "$f"
    echo "Created $f with Tavily plugin and tools.allow."
    return
  fi
  if command -v node >/dev/null 2>&1; then
    node -e "
      const fs = require('fs');
      const path = process.argv[1];
      let cfg = {};
      try { cfg = JSON.parse(fs.readFileSync(path, 'utf8')); } catch (e) {}
      if (!cfg.plugins) cfg.plugins = {};
      if (!cfg.plugins.entries) cfg.plugins.entries = {};
      cfg.plugins.entries['openclaw-tavily'] = { enabled: true };
      if (!cfg.tools) cfg.tools = {};
      const allow = new Set(Array.isArray(cfg.tools.allow) ? cfg.tools.allow : []);
      ['tavily_search','tavily_extract','tavily_crawl','tavily_map','tavily_research'].forEach(t => allow.add(t));
      cfg.tools.allow = Array.from(allow);
      fs.writeFileSync(path, JSON.stringify(cfg, null, 2));
      console.log('Merged Tavily plugin and tools.allow into', path);
    " "$f"
  else
    echo "Install node to auto-merge config. Or manually add to $f:"
    echo '  "plugins": { "entries": { "openclaw-tavily": { "enabled": true } } },'
    echo '  "tools": { "allow": ["tavily_search", "tavily_extract", ...] }'
    exit 1
  fi
}

merge_config "$CONFIG_FILE"
# So the container (user 1000:1000) can read the config
if command -v chown >/dev/null 2>&1; then chown 1000:1000 "$CONFIG_FILE" 2>/dev/null || true; fi

echo ""
echo "=== 3) Restart OpenClaw ==="
docker compose -f docker-compose.openclaw.yml restart openclaw

echo ""
echo "Done. In the Chat UI, Lilo should now see Tavily tools (tavily_search, etc.)."
echo "Verify: docker compose -f docker-compose.openclaw.yml exec openclaw printenv | grep TAVILY"
