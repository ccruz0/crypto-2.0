# Telegram /task Production Verification Report

**Date:** 2026-03-19  
**Deploy:** e355c67 feat(telegram): /task audit - token_source logging, ATP Alerts deny msg, verification script

---

## 1. Deploy Status

| Step | Status |
|------|--------|
| Code pushed to main | ✅ e355c67 |
| Deploy via SSM | ✅ Success |
| backend-aws | ✅ Up (healthy) |
| API health | ✅ Responding |

---

## 2. Single Poller Verification

| Container | RUN_TELEGRAM_POLLER | Polls? |
|-----------|---------------------|--------|
| backend-aws | true | ✅ Yes (only poller) |
| backend-aws-canary | **false** | ❌ No |
| market-updater-aws | N/A | ❌ No |

**Result:** Only backend-aws polls. Canary correctly has RUN_TELEGRAM_POLLER=false.

---

## 3. Old Message Check

**"This task has low impact and was not created"** — Occurrences in last 500 log lines: **0**

**Result:** Old message no longer appears from active runtime.

---

## 4. Notion Config in Runtime

| Variable | Status |
|----------|--------|
| NOTION_API_KEY | ✅ present (50 chars) |
| NOTION_TASK_DB | ✅ eb90cfa139f94724a8b476315908510a |

**Result:** Notion is configured. If /task still fails with "Notion not configured", the env may not be reaching the process (e.g. secrets/runtime.env not loaded). Check that `secrets/runtime.env` is mounted and contains these vars.

---

## 5. Action Required: Test /task

**Send in ATP Control:**
```
/task test deployment verification
```

**Then run verification to capture logs:**
```bash
aws ssm send-command --instance-ids i-087953603011543c5 --document-name AWS-RunShellScript \
  --parameters 'commands=["cd /home/ubuntu/crypto-2.0 && docker compose --profile aws logs backend-aws --tail=100 | grep -E \"\\[TG\\]\\[UPDATE\\]|\\[TG\\]\\[ROUTER\\]|\\[TG\\]\\[TASK\\]|token_source\""]' \
  --region ap-southeast-1
```

---

## 6. Expected Log Output (after /task)

When you send `/task test deployment verification`, you should see:

- `[TG][UPDATE]` — update_id, chat_id, update_type, token_source
- `[TG][ROUTER]` — selected_handler=task, token_source
- `[TG][TASK]` — handler=task path=_handle_task_command, token_source
- `[TG][TASK][DEBUG]` — raw_text, normalized_cmd, handler=_handle_task_command, token_source

**token_source** will be one of: TELEGRAM_BOT_TOKEN, TELEGRAM_ATP_CONTROL_BOT_TOKEN, TELEGRAM_CLAW_BOT_TOKEN.

---

## 7. If Notion Is the Remaining Blocker

**Symptoms:** /task returns "Task could not be created because Notion is not configured" or similar.

**Verify env in container:**
```bash
docker compose --profile aws exec backend-aws printenv | grep NOTION
```

**If missing, set in:**

| Location | How |
|----------|-----|
| **secrets/runtime.env** | Add `NOTION_API_KEY=...` and `NOTION_TASK_DB=...` (rendered by `scripts/aws/render_runtime_env.sh`) |
| **SSM (PROD)** | `/automated-trading-platform/prod/notion/api_key` and `/automated-trading-platform/prod/notion/task_db` |
| **.env.aws** | Fallback when SSM not used |

**Render runtime.env:**
```bash
cd /home/ubuntu/crypto-2.0
bash scripts/aws/render_runtime_env.sh
docker compose --profile aws restart backend-aws
```

---

## 8. Verification Script

Run full verification anytime:
```bash
cd /home/ubuntu/crypto-2.0
bash scripts/aws/verify_telegram_task_production.sh
```

Or via SSM:
```bash
aws ssm send-command --instance-ids i-087953603011543c5 --document-name AWS-RunShellScript \
  --parameters 'commands=["cd /home/ubuntu/crypto-2.0 && bash scripts/aws/verify_telegram_task_production.sh"]' \
  --region ap-southeast-1
```
