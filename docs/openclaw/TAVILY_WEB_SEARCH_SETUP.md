# OpenClaw Tavily Web Search Setup

Enable web search in OpenClaw using [Tavily](https://tavily.com). The API key is stored in `secrets/runtime.env` via an interactive script; it is **never** hardcoded in the repo.

## 1. One-time setup (secure key entry)

From the repo root (e.g. on the OpenClaw/Lab host or locally):

```bash
cd ~/automated-trading-platform
bash scripts/setup_tavily_key.sh
```

- The script prompts for your Tavily API key with **hidden input** (`read -s`).
- It writes `TAVILY_API_KEY` and `SEARCH_PROVIDER=tavily` to `secrets/runtime.env` (creating or updating the file).
- Get a key at https://tavily.com if you don’t have one.

**If you don’t want web search:** create an empty env file so Docker Compose can start (it requires `secrets/runtime.env` to exist):

```bash
mkdir -p secrets && touch secrets/runtime.env
```

## 2. Apply the change

Restart the OpenClaw container so it loads the new env:

```bash
cd ~/automated-trading-platform
docker compose -f docker-compose.openclaw.yml restart openclaw
```

(Or start it if it isn’t running: `docker compose -f docker-compose.openclaw.yml up -d`.)

## 3. Verify

Confirm the container sees the variables (key value will be printed; run only in a safe environment):

```bash
docker compose -f docker-compose.openclaw.yml exec openclaw printenv | grep -E 'TAVILY|SEARCH'
```

You should see `TAVILY_API_KEY=...` and `SEARCH_PROVIDER=tavily` (or the same from env).

## Summary

| Step | Command |
|------|--------|
| Store key (once) | `cd ~/automated-trading-platform && bash scripts/setup_tavily_key.sh` |
| Restart OpenClaw | `docker compose -f docker-compose.openclaw.yml restart openclaw` |
| Verify | `docker compose -f docker-compose.openclaw.yml exec openclaw printenv \| grep TAVILY` |

OpenClaw will use Tavily for web search when `TAVILY_API_KEY` is set and `SEARCH_PROVIDER=tavily` (default).

**If Lilo says it doesn’t see a Tavily tool:** the OpenClaw **plugin** must be installed and enabled. On the LAB host run: `sudo bash scripts/openclaw/enable_tavily_plugin.sh`. See **[TAVILY_PLUGIN_FIX.md](TAVILY_PLUGIN_FIX.md)**.
