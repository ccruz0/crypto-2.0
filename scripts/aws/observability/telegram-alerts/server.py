"""Telegram webhook relay for Alertmanager (Phase 7.1). No secrets in git; use env TELEGRAM_ALERT_BOT_TOKEN, TELEGRAM_ALERT_CHAT_ID."""
import os
import requests
from flask import Flask, request, jsonify

BOT_TOKEN = os.getenv("TELEGRAM_ALERT_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_ALERT_CHAT_ID", "").strip()

app = Flask(__name__)


def send(msg: str):
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("TELEGRAM_ALERT_BOT_TOKEN/CHAT_ID not set")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    r = requests.post(url, json={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    r.raise_for_status()


@app.post("/alert")
def alert():
    payload = request.get_json(force=True, silent=False)
    alerts = payload.get("alerts", [])
    parts = []
    for a in alerts:
        status = a.get("status", "unknown").upper()
        labels = a.get("labels", {})
        ann = a.get("annotations", {})
        name = labels.get("alertname", "ALERT")
        job = labels.get("job", "unknown")
        sev = labels.get("severity", "warning")
        summary = ann.get("summary", "")
        desc = ann.get("description", "")
        parts.append(f"{status} [{sev}] {name} (job={job})\n{summary}\n{desc}".strip())
    msg = "\n\n".join(parts) if parts else "Alertmanager webhook received (no alerts)."
    send(msg)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9119)
