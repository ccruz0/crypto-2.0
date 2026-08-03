#!/usr/bin/env python3
"""Fetch HILOVIVO morning-brief feeds and POST a summary to /api/brief/send.

Credentials (never commit):
  BRIEF_API_KEY via env, or file ~/secrets/brief-agent.env (KEY=value lines).

Usage:
  python3 scripts/brief/run_morning_brief.py
  BRIEF_BASE_URL=https://dashboard.hilovivo.com/api/brief python3 scripts/brief/run_morning_brief.py --dry-run
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_BASE = "https://dashboard.hilovivo.com/api/brief"
ENV_FILE_CANDIDATES = (
    Path.home() / "secrets" / "brief-agent.env",
    Path("/app/secrets/brief-agent.env"),
)


def _load_env_file() -> None:
    for path in ENV_FILE_CANDIDATES:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = val.strip()
        break


def _request(method: str, url: str, key: str, body: dict[str, Any] | None = None) -> Any:
    data = None
    headers = {"X-Brief-Key": key, "Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise SystemExit(f"HTTP {exc.code} {url}: {detail}") from exc


def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=False)


def _fmt_mail(payload: dict[str, Any]) -> str:
    lines = ["<b>📬 Mail</b>"]
    accounts = payload.get("accounts") or []
    if not accounts:
        lines.append("<i>No messages in window.</i>")
    for acc in accounts:
        label = _esc(acc.get("label") or acc.get("id"))
        msgs = acc.get("messages") or []
        lines.append(f"\n<b>{label}</b> ({len(msgs)})")
        for m in msgs[:8]:
            subj = _esc(m.get("subject") or "(no subject)")
            frm = _esc(m.get("from_name") or m.get("from") or "?")
            unread = "● " if m.get("unread") else ""
            lines.append(f"• {unread}<b>{subj}</b> — {frm}")
    errs = payload.get("errors") or []
    if errs:
        lines.append("\n<i>Mail errors: " + ", ".join(_esc(e.get("id")) for e in errs) + "</i>")
    return "\n".join(lines)


def _fmt_calendar(payload: dict[str, Any]) -> str:
    lines = ["<b>📅 Calendar</b>"]
    events = payload.get("events") or []
    if payload.get("errors"):
        err = payload["errors"][0].get("error")
        if err == "ics_urls_missing":
            lines.append("<i>ICS not configured (BRIEF_ICS_URLS).</i>")
            return "\n".join(lines)
    if not events:
        lines.append("<i>No upcoming events.</i>")
        return "\n".join(lines)
    for ev in events[:12]:
        when = _esc(ev.get("start") or ev.get("when") or "")
        title = _esc(ev.get("summary") or ev.get("title") or "(event)")
        lines.append(f"• {when} — <b>{title}</b>")
    return "\n".join(lines)


def _fmt_telegram(payload: dict[str, Any]) -> str:
    lines = ["<b>💬 Telegram</b>"]
    chats = payload.get("chats") or []
    if not chats:
        lines.append("<i>No recent chats.</i>")
        return "\n".join(lines)
    for chat in chats[:10]:
        name = _esc(chat.get("chat") or "?")
        unread = chat.get("unread") or 0
        msgs = chat.get("messages") or []
        lines.append(f"\n<b>{name}</b> (unread {unread}, {len(msgs)} shown)")
        for m in msgs[:4]:
            who = _esc(m.get("from") or "?")
            text = _esc((m.get("text") or "")[:160])
            lines.append(f"• {who}: {text}")
    if payload.get("truncated"):
        lines.append("\n<i>(truncated)</i>")
    return "\n".join(lines)


def build_brief(mail: dict[str, Any], calendar: dict[str, Any], telegram: dict[str, Any]) -> str:
    parts = [
        "<b>☀️ HILOVIVO Morning Brief</b>",
        _fmt_calendar(calendar),
        "",
        _fmt_mail(mail),
        "",
        _fmt_telegram(telegram),
    ]
    return "\n".join(parts).strip()


def main() -> int:
    _load_env_file()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("BRIEF_BASE_URL") or DEFAULT_BASE)
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    key = (os.getenv("BRIEF_API_KEY") or "").strip()
    if not key:
        print("BRIEF_API_KEY missing (env or ~/secrets/brief-agent.env)", file=sys.stderr)
        return 2

    base = args.base_url.rstrip("/")
    mail = _request("GET", f"{base}/mail?hours={args.hours}", key)
    calendar = _request("GET", f"{base}/calendar?days={args.days}", key)
    telegram = _request("GET", f"{base}/telegram?hours={args.hours}", key)
    text = build_brief(mail, calendar, telegram)

    if args.dry_run:
        print(text)
        return 0

    result = _request("POST", f"{base}/send", key, {"text": text, "parse_mode": "HTML"})
    print(json.dumps(result))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
