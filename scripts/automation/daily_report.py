#!/usr/bin/env python3
"""Jarvis daily production report — runs once per day (read-only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import os

from scripts.automation.common import (  # noqa: E402
    automations_enabled,
    backend_base,
    check_websocket_prices,
    classify_exchange_credential_issue,
    dashboard_url,
    docker_container_running,
    ensure_backend_on_path,
    exchange_integration_optional,
    http_fetch,
    http_get,
    load_runtime_env,
    scan_docker_logs,
    setup_logging,
    utc_now_iso,
    ws_prices_url,
)
from scripts.automation.telegram_helper import send_telegram_alert  # noqa: E402


def _query_jarvis_stats() -> dict[str, Any]:
    ensure_backend_on_path()
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return {"error": "DATABASE_URL not set"}

    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        return {"error": "sqlalchemy not installed"}

    try:
        engine = create_engine(db_url, connect_args={"connect_timeout": 8})
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT
                      COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '24 hours') AS total_24h,
                      COUNT(*) FILTER (
                        WHERE status = 'failed' AND created_at >= NOW() - INTERVAL '24 hours'
                      ) AS failed_24h,
                      COUNT(*) FILTER (
                        WHERE status = 'running'
                          AND created_at < NOW() - INTERVAL '30 minutes'
                      ) AS running_stale,
                      COUNT(*) FILTER (
                        WHERE status = 'pending'
                          AND created_at < NOW() - INTERVAL '30 minutes'
                      ) AS pending_stale
                    FROM jarvis_task_runs
                    """
                )
            ).fetchone()
            if not row:
                return {}
            return {
                "total_24h": int(row[0] or 0),
                "failed_24h": int(row[1] or 0),
                "running_stale": int(row[2] or 0),
                "pending_stale": int(row[3] or 0),
            }
    except Exception as exc:
        return {"error": f"db query failed: {type(exc).__name__}"}


def _trading_mode() -> str:
    base = backend_base()
    ok, _, _, body = http_fetch(f"{base}/api/trading/live-status")
    if not ok or not body:
        return "unknown"
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return "unknown"
    mode = data.get("mode")
    if mode:
        return str(mode)
    if data.get("live_trading_enabled") is True:
        return "LIVE"
    if data.get("live_trading_enabled") is False:
        return "DRY_RUN"
    return "unknown"


def _aws_cost_hint() -> str:
    ensure_backend_on_path()
    try:
        from app.jarvis.mvp.aws_auditor_tools import get_cost_summary

        summary = get_cost_summary()
        if not summary.get("success", True):
            return f"n/a ({summary.get('error', 'unavailable')[:80]})"
        total = summary.get("total_unblended_usd")
        if total is not None:
            return f"~${float(total):.2f} (30d)"
        return "available (see jarvis metrics)"
    except Exception as exc:
        return f"n/a ({type(exc).__name__})"


def build_report() -> str:
    ts = utc_now_iso()
    base = backend_base()
    dash = dashboard_url()

    ping_ok, _, _ = http_get(f"{base}/ping_fast")
    fe_ok, _, _ = http_get(dash)
    ws_ok, ws_detail = check_websocket_prices(ws_prices_url())

    containers = [
        "postgres_hardened",
        "backend-aws",
        "market-updater",
        "atp-telegram-alerts",
        "frontend-aws",
    ]
    container_lines: list[str] = []
    for name in containers:
        ok, detail = docker_container_running(name)
        container_lines.append(f"  {name}: {'up' if ok else 'down'} ({detail[:60]})")

    jarvis = _query_jarvis_stats()
    errors = scan_docker_logs("backend-aws", tail=200, pattern=r"critical|fatal|traceback")
    error_snip = errors[0][:120] if errors else "none"
    exchange_severity, exchange_detail = classify_exchange_credential_issue()
    exchange_optional = exchange_integration_optional()

    lines = [
        f"📊 Jarvis Daily Production Report ({ts})",
        f"Backend: {'OK' if ping_ok else 'FAIL'}",
        f"Frontend: {'OK' if fe_ok else 'FAIL'}",
        f"WebSocket prices: {'OK' if ws_ok else 'FAIL'} ({ws_detail[:60]})",
    ]

    if exchange_severity == "ok":
        lines.append("Crypto.com integration: OK")
    elif exchange_severity == "warning":
        lines.append(f"⚠️ Crypto.com integration: WARNING ({exchange_detail[:120]})")
    elif exchange_severity == "error":
        lines.append(f"❌ Crypto.com integration: ERROR ({exchange_detail[:120]})")
    else:
        lines.append(f"Crypto.com integration: INFO ({exchange_detail[:120]})")

    if exchange_optional and exchange_severity != "ok":
        lines.append("Exchange integration optional in current trading mode")

    if "error" in jarvis:
        lines.append(f"Jarvis tasks (24h): {jarvis['error']}")
    else:
        lines.append(
            "Jarvis tasks (24h): "
            f"total={jarvis.get('total_24h', 0)} failed={jarvis.get('failed_24h', 0)} "
            f"stale_running={jarvis.get('running_stale', 0)} stale_pending={jarvis.get('pending_stale', 0)}"
        )

    lines.append("Docker:")
    lines.extend(container_lines)
    lines.append(f"Critical errors: {error_snip}")
    lines.append(f"AWS cost (est.): {_aws_cost_hint()}")
    lines.append(f"Trading mode: {_trading_mode()}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Jarvis daily production report")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--print-only", action="store_true", help="Print report to stdout only")
    args = parser.parse_args()

    load_runtime_env()
    log = setup_logging("jarvis.daily_report", verbose=args.verbose)

    if not automations_enabled() and not args.print_only:
        log.info("JARVIS_AUTOMATIONS_ENABLED is false; exiting")
        return 0

    report = build_report()
    log.info("report built (%s chars)", len(report))
    if args.print_only:
        print(report)
        return 0

    sent = send_telegram_alert(report, dry_run=args.dry_run)
    return 0 if sent or args.dry_run else 1


if __name__ == "__main__":
    sys.exit(main())
