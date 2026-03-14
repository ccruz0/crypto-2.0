# OpenClaw ACP / Cursor Connection Fix

When OpenClaw shows **"ACP target agent is not configured. Pass agentId in sessions_spawn or set acp.defaultAgent in config"**, the gateway cannot connect to Cursor for updates or agent sessions.

## Quick fix (redeploy)

Redeploy so the config is regenerated with `acp.defaultAgent`:

```bash
./scripts/openclaw/deploy_openclaw_lab_from_mac.sh deploy
```

The deploy script now adds `acp.defaultAgent: "codex"` to `openclaw.json` by default.

## Manual fix (no redeploy)

On the LAB host (via SSM or SSH), edit the config:

```bash
# Path on LAB (docker-compose mounts /opt/openclaw/home-data)
CONFIG=/opt/openclaw/home-data/openclaw.json
```

Add or merge the `acp` section:

```json
{
  "acp": {
    "defaultAgent": "codex"
  }
}
```

Example merge with `jq`:

```bash
jq '.acp = (.acp // {} | .defaultAgent = "codex")' "$CONFIG" > "$CONFIG.tmp" && mv "$CONFIG.tmp" "$CONFIG"
```

Then restart OpenClaw:

```bash
sudo docker restart openclaw
```

## Override agent

Built-in ACP agent names: `codex`, `claude`, `gemini`, `opencode`, `pi`. For Cursor, use `codex`.

Override via env before deploy:

```bash
OPENCLAW_ACP_DEFAULT_AGENT=codex ./scripts/openclaw/deploy_openclaw_lab_from_mac.sh deploy
```

Or in `docker-compose.openclaw.yml`:

```yaml
environment:
  - OPENCLAW_ACP_DEFAULT_AGENT=codex
```
