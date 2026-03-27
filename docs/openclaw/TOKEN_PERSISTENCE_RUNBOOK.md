# OpenClaw token persistence runbook

Use this to avoid pasting the gateway token after every restart/redeploy.

## Goal

Keep a stable `gateway.auth.token` in a persistent file on LAB so the UI token does not change unexpectedly.

## One-time setup (LAB host)

Run on LAB (`i-0d82c172235770a0d`):

```bash
cd /home/ubuntu/crypto-2.0
sudo bash scripts/openclaw/ensure_openclaw_gateway_token.sh
```

What it does:
- Keeps existing token if already present.
- Creates `/opt/openclaw/openclaw.json` and token if missing.
- Restarts `openclaw` only if token changed.
- Prints the active token.

## One-time UI step (per browser profile)

1. Open `https://dashboard.hilovivo.com/openclaw/`.
2. Go to Control UI settings.
3. Paste the token printed by the script.
4. Save.

After this, you should not need to re-paste unless token rotates or browser storage is cleared.

## Optional: rotate token intentionally

```bash
cd /home/ubuntu/crypto-2.0
sudo ROTATE=1 bash scripts/openclaw/ensure_openclaw_gateway_token.sh
```

Then paste the new token once in Control UI settings.

## Deploy safety rules

- Keep `/opt/openclaw/openclaw.json` mounted/preserved across container restarts.
- Do not auto-generate a new token on every deploy.
- Do not run deploy commands that overwrite `gateway.auth.token` unless you intend to rotate.

## If mismatch appears again

- Symptom: `unauthorized: gateway token mismatch`.
- Fix:
  1. Re-run `ensure_openclaw_gateway_token.sh` (without `ROTATE=1`) and copy token.
  2. Paste token in Control UI settings.
  3. Hard refresh browser.
- If still failing, clear site storage for `dashboard.hilovivo.com/openclaw` and paste token again.
