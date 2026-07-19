# Strategy dropdown “changes by itself” — root cause (2026-07-17)

## Symptom

Watchlist Strategy values (Swing/Scalp/Intradia × Conservadora/Agresiva) revert
or flip without user action after deploys / backend recreates.

## Root cause

`docker-compose.yml` sets `TRADING_CONFIG_PATH=/data/trading_config.json` and
mounts volume `aws_trading_config_data:/data`, but `config_loader.py` **never
read that env var**. It always used `/app/trading_config.json` (image/container
writable layer).

Dashboard edits therefore persisted only until the next `backend-aws` recreate,
then fell back to the baked image config — looking like strategies “changed alone”.

Not caused by Jarvis auto-assigning strategies.

## Amplifiers (secondary)

- USD/USDT dual watchlist rows (BTC/ETH) with different presets + UI dedupe.
- Dual-source resolution: `trading_config.json` preset vs `WatchlistItem.sl_tp_mode`.

## Fix

Honor `TRADING_CONFIG_PATH` in `config_loader` / strategy profile cache; seed
`/data` from `/app` when the volume file is missing.

## Deploy migration / permissions

After #179, prod briefly returned
`Permission denied: '/data/trading_config.json'` because the Docker volume is
root-owned and the app runs as `appuser`. Follow-up: entrypoint `chown` +
read-only fallback to `/app` when `/data` is not writable.

On the host (if needed once):

```bash
docker exec -u 0 backend-aws sh -c \
  'mkdir -p /data && chown -R appuser:appuser /data && \
   if [ ! -f /data/trading_config.json ] && [ -f /app/trading_config.json ]; then \
     cp -a /app/trading_config.json /data/trading_config.json; \
   fi && ls -la /data/trading_config.json'
```

Verify:

```bash
docker exec backend-aws python -c "from app.services.config_loader import get_config_path; print(get_config_path())"
# expect: /data/trading_config.json
curl -sS http://127.0.0.1:8002/api/diagnostics/strategy-consistency | python3 -m json.tool | head -40
```

## Follow-up (2026-07-19) — read fallback race

Symptom returned: strategies looked wrong again. Prod evidence:

- `get_config_path()` used an `open(..., "a")` write probe on every resolve.
- When the probe failed (~1881× since last recreate), **reads** fell back to baked
  `/app/trading_config.json` even though `/data/trading_config.json` still existed.
- That can flip the Watchlist dropdown to image defaults without any user action.

Fix (branch `fix/strategy-config-read-fallback`): if the persistent file exists, always
read it; never fall back to `/app` for reads. Writes stay on `/data` and fail
loudly if unwritable. Also fixed `strategy-consistency` diagnostic to prefer the
exact symbol key over the USD/USDT sibling.
