#!/usr/bin/env python3
"""
Send a description message to each configured Telegram channel.
Verifies routing and explains what each channel is for.

Usage (from repo root):
  python scripts/send_channel_descriptions.py

Loads env from: .env, .env.aws, secrets/runtime.env
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
os.chdir(REPO_ROOT)

# Load env files (order matters - later overrides)
for f in [".env", ".env.aws", "secrets/runtime.env", "backend/.env"]:
    p = REPO_ROOT / f
    if p.exists():
        with open(p) as fp:
            for line in fp:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    k, v = k.strip(), v.strip().strip('"\'')
                    if k and v and k not in os.environ:
                        os.environ[k] = v

import json
import urllib.request
import urllib.error


def _mask_token(token: str) -> str:
    """Mask token for logging: show last 4 chars only."""
    if not token or len(token) < 4:
        return "****"
    return f"...{token[-4:]}"


def send_message(token: str, chat_id: str, text: str) -> tuple[bool, str]:
    """Send message via Telegram API. Returns (success, error_msg)."""
    if not token or not chat_id:
        return False, "token or chat_id empty"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        data = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode()
        req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            out = json.loads(r.read().decode())
            if out.get("ok"):
                return True, ""
            return False, out.get("description", "unknown")
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200] if e.fp else ""
        try:
            err = json.loads(body).get("description", body) if body else str(e)
        except Exception:
            err = body or str(e)
        return False, f"HTTP {e.code}: {err}"
    except Exception as e:
        return False, str(e)


# Explicit routing per logical channel. One message per channel, no grouping.
# ATP Control → TELEGRAM_ATP_CONTROL_CHAT_ID + TELEGRAM_ATP_CONTROL_BOT_TOKEN
# AWS Alerts → TELEGRAM_ALERT_CHAT_ID + TELEGRAM_ALERT_BOT_TOKEN
# Claw → TELEGRAM_CLAW_CHAT_ID + TELEGRAM_CLAW_BOT_TOKEN
# ATP Alerts → TELEGRAM_CHAT_ID_TRADING + TELEGRAM_BOT_TOKEN
CHANNELS = [
    {
        "name": "ATP Control",
        "bot": "@ATP_control_bot",
        "token_var": "TELEGRAM_ATP_CONTROL_BOT_TOKEN",
        "chat_var": "TELEGRAM_ATP_CONTROL_CHAT_ID",
        "fallback_token": "TELEGRAM_CLAW_BOT_TOKEN",
        "fallback_chat": "TELEGRAM_CLAW_CHAT_ID",
        "message": """📋 <b>ATP Control Alerts</b> — How this channel works

<b>Purpose:</b> Development, code, tasks, investigations, approvals, agent orchestration.

<b>You receive:</b>
• [TASK] — Notion/OpenClaw task updates, investigation results
• [INVESTIGATION] — Bug analysis, root cause reports
• [PATCH] — Approval requests, deploy confirmations
• [ERROR] — Agent failures, notion_env errors, task_health_monitor alerts

<b>Commands:</b> Send /menu here for the main menu. /investigate, /task, /agent, /help, /status, etc. are authorized in this channel.

<b>Source modules:</b> claw_telegram, agent_telegram_approval, agent_task_executor, notion_env, task_health_monitor""",
    },
    {
        "name": "AWS Alerts",
        "bot": "@AWS_alerts_hilovivo_bot",
        "token_var": "TELEGRAM_ALERT_BOT_TOKEN",
        "chat_var": "TELEGRAM_ALERT_CHAT_ID",
        "fallback_token": "TELEGRAM_BOT_TOKEN",
        "fallback_chat": "TELEGRAM_CHAT_ID_OPS",
        "message": """🔧 <b>AWS Alerts</b> — How this channel works

<b>Purpose:</b> Infrastructure and server monitoring only. No trading.

<b>You receive:</b>
• EC2/Docker health failures
• Stale market data, stalled scheduler
• System alerts (system_alerts.py)
• Prometheus/Alertmanager alerts
• Auto-healing notifications

<b>What you don't get:</b> No buy/sell, no orders, no trading signals. Those go to ATP Alerts.

<b>Source modules:</b> telegram_notifier (chat_destination=ops), infra/telegram_helper, scripts/aws/observability/telegram-alerts""",
    },
    {
        "name": "Claw",
        "bot": "@Claw_cruz_bot",
        "token_var": "TELEGRAM_CLAW_BOT_TOKEN",
        "chat_var": "TELEGRAM_CLAW_CHAT_ID",
        "fallback_token": "TELEGRAM_BOT_TOKEN",
        "fallback_chat": "TELEGRAM_CHAT_ID",
        "message": """🎮 <b>Claw</b> — How this channel works

<b>Purpose:</b> Control plane and user command responses.

<b>You receive:</b>
• Replies to /task, /help, /investigate, /agent
• OpenClaw interaction feedback
• Trigger system action confirmations
• Command acknowledgments

<b>How it works:</b> When you send a command to the bot, responses are sent back to the chat where you sent it (this channel or your private chat). Claw is the control-plane bot for user-initiated actions.

<b>Note:</b> If Claw chat_id equals ATP Control, you may receive both task-system messages and command replies here.""",
    },
    {
        "name": "ATP Alerts",
        "bot": "@HILOVIVO30_bot",
        "token_var": "TELEGRAM_BOT_TOKEN",
        "chat_var": "TELEGRAM_CHAT_ID_TRADING",
        "fallback_token": "TELEGRAM_BOT_TOKEN_AWS",
        "fallback_chat": "TELEGRAM_CHAT_ID_AWS",
        "message": """💰 <b>ATP Alerts</b> — How this channel works

<b>Purpose:</b> Live trading alerts only. Real money.

<b>You receive:</b>
• BUY/SELL signals (signal_monitor)
• Order created, executed, SL/TP
• Execution errors, exchange responses
• Daily/sell reports
• SL/TP reminders

<b>Commands:</b> This channel is alerts-only. Use /menu in ATP Control for commands.

<b>Source modules:</b> telegram_notifier (chat_destination=trading), signal_monitor, exchange_sync, crypto_com_trade, sl_tp_checker, tp_sl_order_creator""",
    },
]


def main():
    print("=== Sending channel description messages ===\n")

    # Resolve (token, chat_id) for each channel
    resolved = []
    for ch in CHANNELS:
        token = (os.environ.get(ch["token_var"]) or "").strip()
        chat = (os.environ.get(ch["chat_var"]) or "").strip()
        if not token and ch.get("fallback_token"):
            token = (os.environ.get(ch["fallback_token"]) or "").strip()
        if not chat and ch.get("fallback_chat"):
            chat = (os.environ.get(ch["fallback_chat"]) or "").strip()
        if not chat and ch.get("chat_var") == "TELEGRAM_CHAT_ID_TRADING":
            chat = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()

        if not token or not chat:
            print(f"⏭️  {ch['name']}: SKIP (token or chat_id not set)")
            continue

        resolved.append({"name": ch["name"], "bot": ch["bot"], "token": token, "chat": chat, "message": ch["message"]})

    # One message per logical channel. No grouping across channels.
    for r in resolved:
        token, chat, msg = r["token"], r["chat"], r["message"]
        print(f"[SEND] channel={r['name']} token={_mask_token(token)} chat_id={chat} msg_preview={msg[:60]}...")
        ok, err = send_message(token, chat, msg)
        if ok:
            print(f"✅ {r['name']}: sent")
        else:
            print(f"❌ {r['name']}: FAILED - {err}")

    print("\nDone.")


if __name__ == "__main__":
    main()
