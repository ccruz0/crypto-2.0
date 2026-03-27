# Fix: Lilo doesn't see a Tavily tool

If the OpenClaw Chat shows "I don't see a dedicated Tavily tool in my available functions", the **Tavily plugin** is not installed or not enabled. The env vars (`TAVILY_API_KEY`, `SEARCH_PROVIDER=tavily`) are only the first step; the OpenClaw app must load the **openclaw-tavily** plugin so the agent gets `tavily_search`, `tavily_extract`, etc.

## Quick fix (on LAB host)

Run the enable script from the repo root on the **OpenClaw/LAB** instance:

```bash
cd /home/ubuntu/crypto-2.0
sudo bash scripts/openclaw/enable_tavily_plugin.sh
```

This will:

1. Install the **openclaw-tavily** plugin (via OpenClaw CLI inside the container, or via host npm into `/opt/openclaw/home-data/extensions/openclaw-tavily`).
2. Merge into `openclaw.json`: `plugins.entries["openclaw-tavily"] = { enabled: true }` and add Tavily tools to `tools.allow`.
3. Restart the OpenClaw container.

Ensure **TAVILY_API_KEY** is already set (e.g. you ran `bash scripts/setup_tavily_key.sh` or `python3 scripts/setup_tavily_key_popup.py` and restarted OpenClaw so the container has the key).

## Verify

- In the Chat UI, ask Lilo to list its tools or run a web search; it should mention `tavily_search` or succeed at search.
- On the host: `docker compose -f docker-compose.openclaw.yml exec openclaw printenv | grep TAVILY` should show the key.

## If the script fails

1. **Plugin install fails**  
   The OpenClaw image may not include the CLI or npm. Then install the plugin **on the host** into the mounted config dir:
   - On LAB: `mkdir -p /opt/openclaw/home-data/extensions/openclaw-tavily`, then from a machine with node/npm run `npm pack openclaw-tavily`, copy the tarball to the host, extract it into `/opt/openclaw/home-data/extensions/openclaw-tavily`, run `npm install --omit=dev` there. Then merge config (step 2 below) and restart.

2. **Config merge**  
   Edit `/opt/openclaw/home-data/openclaw.json` on the LAB host and ensure:
   - `plugins.entries["openclaw-tavily"]` is present and `enabled: true`.
   - `tools.allow` includes at least `"tavily_search"` (or the full set: `tavily_search`, `tavily_extract`, `tavily_crawl`, `tavily_map`, `tavily_research`).

   Example snippet:

   ```json
   {
     "plugins": {
       "entries": {
         "openclaw-tavily": { "enabled": true }
       }
     },
     "tools": {
       "allow": ["tavily_search", "tavily_extract", "tavily_crawl", "tavily_map", "tavily_research"]
     }
   }
   ```

   (If you use a tool profile like `tools.profile: "coding"`, you must still add the Tavily tools to `tools.allow` so they are available.)

3. **Alternative: build Tavily into the image**  
   In the **OpenClaw repo** (ccruz0/openclaw): add `openclaw-tavily` as a dependency, enable it in config in the image or default openclaw.json, rebuild and push the image. Then on LAB use that image and set `TAVILY_API_KEY` in the environment (already done via ATP’s `secrets/runtime.env`).

## Reference

- Plugin: [openclaw-tavily on npm](https://www.npmjs.com/package/openclaw-tavily), [OpenClaw dir](https://openclawdir.com/plugins/tavily-7vwo37).
- OpenClaw web tools (built-in `web_search` uses Brave/Perplexity/Gemini etc., not Tavily): [docs.openclaw.ai/tools/web](https://docs.openclaw.ai/tools/web). For Tavily you need this plugin.
