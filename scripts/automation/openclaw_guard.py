#!/usr/bin/env python3
"""OpenClaw regression guard — runs every 6 hours (read-only)."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.automation.common import (  # noqa: E402
    CooldownStore,
    automations_enabled,
    dashboard_url,
    default_cooldown_minutes,
    http_fetch,
    load_runtime_env,
    openclaw_public_allowed,
    repo_root,
    setup_logging,
    utc_now_iso,
)
from scripts.automation.telegram_helper import send_telegram_alert  # noqa: E402


@dataclass
class OpenClawHit:
    location: str
    detail: str


def detect_openclaw_tab_in_source(source: str, *, path_label: str) -> list[OpenClawHit]:
    """Detect OpenClaw as a main visible dashboard tab in frontend source."""
    hits: list[OpenClawHit] = []
    tab_pattern = re.compile(
        r"\{\s*id:\s*['\"]openclaw['\"]\s*,\s*label:\s*['\"]OpenClaw['\"]\s*\}",
        re.IGNORECASE,
    )
    if tab_pattern.search(source):
        hits.append(OpenClawHit(path_label, "OpenClaw tab entry in tabs array"))
    elif re.search(r"id:\s*['\"]openclaw['\"]", source, re.IGNORECASE) and "OpenClaw" in source:
        hits.append(OpenClawHit(path_label, "openclaw tab id with OpenClaw label"))
    return hits


def detect_nginx_openclaw_exposure(config_text: str, *, path_label: str) -> list[OpenClawHit]:
    """Flag nginx routes that proxy/serve OpenClaw unless explicitly allowed."""
    if openclaw_public_allowed():
        return []

    hits: list[OpenClawHit] = []
    if "/openclaw" not in config_text.lower():
        return hits

    block_pattern = re.compile(
        r"location\s+(?:=\s+|\^~\s+)?(/openclaw\S*)\s*\{([^}]*)\}",
        re.IGNORECASE | re.DOTALL,
    )
    for match in block_pattern.finditer(config_text):
        path = match.group(1).strip()
        body = match.group(2)
        body_lower = body.lower()
        if "proxy_pass" in body_lower:
            hits.append(OpenClawHit(path_label, f"nginx proxies OpenClaw at {path}"))
        elif re.search(r"return\s+30[12]", body_lower):
            continue
        else:
            snippet = body.strip().splitlines()[0][:120] if body.strip() else "unknown handler"
            hits.append(OpenClawHit(path_label, f"nginx location {path} may expose OpenClaw: {snippet}"))
    return hits


def check_public_openclaw_route(dash_url: str) -> list[OpenClawHit]:
    if openclaw_public_allowed():
        return []

    url = f"{dash_url.rstrip('/')}/openclaw"
    ok, detail, code, body = http_fetch(url, timeout=12.0)
    if code in (301, 302, 307, 308):
        return []
    if ok and body and re.search(r"openclaw", body, re.IGNORECASE):
        return [OpenClawHit(url, f"public /openclaw returned content ({detail})")]
    if ok and code == 200:
        return [OpenClawHit(url, "public /openclaw returned HTTP 200 (expected redirect)")]
    return []


def run_checks() -> list[OpenClawHit]:
    root = repo_root()
    hits: list[OpenClawHit] = []

    page_tsx = root / "frontend" / "src" / "app" / "page.tsx"
    if page_tsx.is_file():
        hits.extend(detect_openclaw_tab_in_source(page_tsx.read_text(encoding="utf-8"), path_label=str(page_tsx)))

    nginx_conf = root / "nginx" / "dashboard.conf"
    if nginx_conf.is_file():
        hits.extend(
            detect_nginx_openclaw_exposure(
                nginx_conf.read_text(encoding="utf-8"),
                path_label=str(nginx_conf),
            )
        )

    standalone = root / "frontend" / "src" / "app" / "openclaw" / "page.tsx"
    if standalone.is_file() and not openclaw_public_allowed():
        hits.append(OpenClawHit(str(standalone), "standalone /openclaw Next.js page exists"))

    hits.extend(check_public_openclaw_route(dashboard_url()))
    return hits


def format_alert(hits: list[OpenClawHit], ts: str) -> str:
    lines = [f"🦀 OpenClaw Regression Guard ({ts})"]
    for item in hits:
        lines.append(f"• {item.location}")
        lines.append(f"  {item.detail[:180]}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenClaw regression guard")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--force-alert", action="store_true")
    parser.add_argument("--mock-source", help="Test detection against inline source text")
    args = parser.parse_args()

    load_runtime_env()
    log = setup_logging("jarvis.openclaw_guard", verbose=args.verbose)

    if not automations_enabled() and not args.mock_source:
        log.info("JARVIS_AUTOMATIONS_ENABLED is false; exiting")
        return 0

    if args.mock_source:
        hits = detect_openclaw_tab_in_source(args.mock_source, path_label="mock")
        for item in hits:
            print(f"HIT: {item.location} — {item.detail}")
        return 0 if not hits else 2

    hits = run_checks()
    for item in hits:
        log.warning("openclaw_hit location=%s detail=%s", item.location, item.detail[:200])

    if not hits:
        log.info("no OpenClaw regression detected")
        return 0

    ts = utc_now_iso()
    cooldown = CooldownStore()
    alert_key = "openclaw:" + "|".join(sorted(h.location for h in hits))
    cooldown_mins = default_cooldown_minutes()

    if not args.force_alert and not cooldown.should_send(alert_key, cooldown_mins):
        log.info("cooldown active; skip Telegram")
        return 2

    message = format_alert(hits, ts)
    sent = send_telegram_alert(message, dry_run=args.dry_run)
    if sent and not args.dry_run:
        cooldown.mark_sent(alert_key)
    return 2


if __name__ == "__main__":
    sys.exit(main())
