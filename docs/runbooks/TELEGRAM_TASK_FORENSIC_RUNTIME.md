# Telegram /task Old Message – Forensic Runtime Investigation

## Goal

Find the exact source of the old Telegram response still appearing in ATP Control:

> "❌ Task creation failed: This task has low impact and was not created. If this is important, please clarify urgency or impact."

This string does **not** exist in the current source. The investigation must prove where it comes from at runtime.

## Quick Run

```bash
# 1. Commit and push forensic scripts
git add scripts/aws/forensic_telegram_task_runtime.sh scripts/aws/run_forensic_telegram_task_via_ssm.sh backend/scripts/diag/forensic_telegram_task_source.py
git commit -m "Add forensic scripts for Telegram /task old message"
git push origin main

# 2. Run forensic on PROD via SSM
./scripts/aws/run_forensic_telegram_task_via_ssm.sh
```

## What the Forensic Does

1. **Active Telegram runtime** – Container name, image, created time, `RUN_TELEGRAM_POLLER`, hostname, bind mounts
2. **Host filesystem search** – Grep for `low impact and was not created` and `clarify urgency or impact` in repo and alternate paths
3. **Container filesystem search** – Same grep inside `/app` of `backend-aws`
4. **Python runtime inspection** – `inspect.getsource()` for `_handle_task_command` and `create_task_from_telegram_intent`, search `/app` for old string, check `.pyc` for stale bytecode
5. **Image vs repo** – Compare first lines of `task_compiler.py` in repo vs container
6. **All containers with Telegram** – List containers that have `TELEGRAM_BOT_TOKEN` or `TELEGRAM_ATP_CONTROL` and their `RUN_TELEGRAM_POLLER` value

## Interpretation

| Finding | Implication |
|--------|-------------|
| Old string **in** container `/app` | Stale image or bind mount overriding image |
| Old string **not** in container, but message still appears | Different process/token responding (canary, another instance, another bot) |
| Old string in `inspect.getsource` | Stale `.pyc` or wrong module loaded |
| Bind mount of repo into `/app` | Host code overrides image; `git pull` + restart may not refresh if mount is stale |
| Multiple containers with Telegram env | Possible duplicate pollers; check `RUN_TELEGRAM_POLLER` |

## Remediation (after root cause is proven)

- **Stale image**: `NO_CACHE=1 ./scripts/deploy_production_via_ssm.sh`
- **Stale bind mount**: Remove mount or ensure host repo is up to date and restart
- **Duplicate poller**: Ensure only `backend-aws` has `RUN_TELEGRAM_POLLER` true; canary must have `false`
- **Wrong token**: Verify `TELEGRAM_ATP_CONTROL_*` points to the intended bot

## Verification After Fix

Send in ATP Control:

```
/task test deployment verification
```

Expected: Task created (backlog) or a different error message – **not** the old "low impact" string.
