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

## Deploy migration (one-time, before recreate)

While the current container is still up (so `/app/trading_config.json` still has
live edits):

```bash
docker exec backend-aws sh -c \
  'mkdir -p /data && cp -a /app/trading_config.json /data/trading_config.json && ls -la /data/trading_config.json'
```

Then deploy/recreate backend. Verify:

```bash
docker exec backend-aws sh -c 'echo TRADING_CONFIG_PATH=$TRADING_CONFIG_PATH; python -c "from app.services.config_loader import get_config_path; print(get_config_path())"'
curl -sS http://127.0.0.1:8002/api/diagnostics/strategy-consistency | python3 -m json.tool | head -40
```
