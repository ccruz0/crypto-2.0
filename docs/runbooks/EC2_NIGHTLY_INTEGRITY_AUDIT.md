# EC2 Nightly Integrity Audit (Option A)

The full nightly integrity audit runs **on the EC2 instance** at 03:15 Europe/Madrid, not on GitHub-hosted runners. Each step outputs PASS or FAIL only. On any failure, one Telegram alert is sent with the failing step name and the repo git short hash. No secrets are ever printed or logged.

## What runs nightly

In order, the entrypoint `scripts/aws/nightly_integrity_audit.sh` runs:

1. **verify_no_public_ports.sh** – Ensures backend (8002) and frontend (3000) are bound to 127.0.0.1 in docker-compose.
2. **health_guard.sh** – Probes backend `/health` when docker and backend-aws are available.
3. **stability_check.sh** – Placeholder for stability checks (currently always PASS).
4. **reconcile_order_intents.sh** – Marks stale order intents (no exchange order) as FAILED via backend-aws container.
5. **portfolio_consistency_check.sh** – Compares portfolio vs exchange summary; fails if drift exceeds threshold.

If any step fails, the script sends a single Telegram message (via `_notify_telegram_fail.sh`), prints FAIL once, and exits 1. If all pass, it prints PASS and exits 0.

## Where logs are

- When run by systemd, stdout/stderr go to **journald**. Use:
  - `journalctl -u nightly-integrity-audit.service`
  - `journalctl -u nightly-integrity-audit.service -f` (follow)
  - `journalctl -t nightly-integrity-audit` (by SyslogIdentifier)

## How to manually run the script

From the repo root on EC2:

```bash
cd /home/ubuntu/automated-trading-platform
bash scripts/aws/nightly_integrity_audit.sh
```

Output is either PASS or FAIL. For step-level details when debugging, run individual scripts with `DEBUG=1`:

```bash
DEBUG=1 bash scripts/aws/reconcile_order_intents.sh
```

## How to check systemd timer status

```bash
# Timer status and next run
sudo systemctl status nightly-integrity-audit.timer
sudo systemctl list-timers nightly-integrity-audit.timer

# Enable timer (survives reboot)
sudo systemctl enable nightly-integrity-audit.timer
sudo systemctl start nightly-integrity-audit.timer

# Run the service once now (manual trigger)
sudo systemctl start nightly-integrity-audit.service
```

## Installing the systemd unit and timer on EC2

Copy the unit files from the repo into systemd and enable the timer:

```bash
sudo cp /home/ubuntu/automated-trading-platform/scripts/aws/systemd/nightly-integrity-audit.service /etc/systemd/system/
sudo cp /home/ubuntu/automated-trading-platform/scripts/aws/systemd/nightly-integrity-audit.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable nightly-integrity-audit.timer
sudo systemctl start nightly-integrity-audit.timer
```

Ensure `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set (e.g. in `secrets/runtime.env`) so failure alerts can be sent. The service uses `EnvironmentFile=-/home/ubuntu/automated-trading-platform/secrets/runtime.env` (the `-` means the file is optional).

## What a FAIL alert means

If you receive a Telegram message like:

`Nightly integrity FAIL: reconcile_order_intents | git: abc1234`

- The step **reconcile_order_intents** failed (non-zero exit).
- **git: abc1234** is the short commit hash of the repo on the EC2 host at run time.

Check journald for the run that failed and fix the underlying issue (e.g. backend-aws not running, DB issue, or real integrity failure). No secrets are included in the alert.

## No secrets policy

- Scripts never echo or log `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DATABASE_URL`, or API keys.
- The Telegram helper `_notify_telegram_fail.sh` uses env vars for the request only and does not print them.
- Set `DEBUG=1` only when debugging; default output remains PASS/FAIL only.
