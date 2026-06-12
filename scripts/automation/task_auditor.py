#!/usr/bin/env python3
"""Jarvis task auditor — runs hourly (read-only DB checks)."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.automation.common import (  # noqa: E402
    CooldownStore,
    automations_enabled,
    default_cooldown_minutes,
    ensure_backend_on_path,
    load_runtime_env,
    setup_logging,
    utc_now_iso,
)
from scripts.automation.remediation import (  # noqa: E402
    auto_remediation_enabled,
    remediate_audit_findings,
)
from scripts.automation.remediation_safety import auto_remediation_dry_run  # noqa: E402
from scripts.automation.telegram_helper import send_telegram_alert  # noqa: E402

STALE_MINUTES = 30


def _high_cost_usd() -> float:
    try:
        return float(os.getenv("JARVIS_TASK_HIGH_COST_USD", "5.0"))
    except ValueError:
        return 5.0


def _repeat_failure_threshold() -> int:
    try:
        return max(2, int(os.getenv("JARVIS_TASK_REPEAT_FAILURES", "3")))
    except ValueError:
        return 3


@dataclass
class AuditFinding:
    category: str
    detail: str


def _fetch_findings() -> list[AuditFinding]:
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return [AuditFinding("config", "DATABASE_URL not set")]

    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        return [AuditFinding("config", "sqlalchemy not installed")]

    findings: list[AuditFinding] = []
    try:
        engine = create_engine(db_url, connect_args={"connect_timeout": 8})
    except Exception as exc:
        return [AuditFinding("config", f"db engine error: {type(exc).__name__}")]

    try:
        conn_ctx = engine.connect()
    except Exception as exc:
        return [AuditFinding("config", f"db connect failed: {type(exc).__name__}")]

    with conn_ctx as conn:
        failed = conn.execute(
            text(
                """
                SELECT task_id, task, error, created_at
                FROM jarvis_task_runs
                WHERE status = 'failed'
                  AND created_at >= NOW() - INTERVAL '24 hours'
                ORDER BY created_at DESC
                LIMIT 10
                """
            )
        ).fetchall()
        for row in failed:
            findings.append(
                AuditFinding(
                    "failed",
                    f"{row[0]}: {(row[2] or 'no error')[:100]}",
                )
            )

        stale_running = conn.execute(
            text(
                f"""
                SELECT task_id, task, created_at
                FROM jarvis_task_runs
                WHERE status = 'running'
                  AND created_at < NOW() - INTERVAL '{STALE_MINUTES} minutes'
                ORDER BY created_at ASC
                LIMIT 10
                """
            )
        ).fetchall()
        for row in stale_running:
            findings.append(AuditFinding("running_stale", f"{row[0]} since {row[2]}"))

        stale_pending = conn.execute(
            text(
                f"""
                SELECT task_id, task, created_at
                FROM jarvis_task_runs
                WHERE status = 'pending'
                  AND created_at < NOW() - INTERVAL '{STALE_MINUTES} minutes'
                ORDER BY created_at ASC
                LIMIT 10
                """
            )
        ).fetchall()
        for row in stale_pending:
            findings.append(AuditFinding("pending_stale", f"{row[0]} since {row[2]}"))

        repeated = conn.execute(
            text(
                """
                SELECT task, COUNT(*) AS cnt
                FROM jarvis_task_runs
                WHERE status = 'failed'
                  AND created_at >= NOW() - INTERVAL '7 days'
                GROUP BY task
                HAVING COUNT(*) >= :threshold
                ORDER BY cnt DESC
                LIMIT 5
                """
            ),
            {"threshold": _repeat_failure_threshold()},
        ).fetchall()
        for row in repeated:
            findings.append(AuditFinding("repeated_failure", f"{row[0][:80]} x{row[1]}"))

        costly = conn.execute(
            text(
                """
                SELECT task_id, task, estimated_cost_usd, created_at
                FROM jarvis_task_runs
                WHERE estimated_cost_usd IS NOT NULL
                  AND estimated_cost_usd >= :min_cost
                  AND created_at >= NOW() - INTERVAL '24 hours'
                ORDER BY estimated_cost_usd DESC
                LIMIT 5
                """
            ),
            {"min_cost": _high_cost_usd()},
        ).fetchall()
        for row in costly:
            findings.append(
                AuditFinding(
                    "high_cost",
                    f"{row[0]} ${float(row[2]):.2f} — {(row[1] or '')[:60]}",
                )
            )

    return findings


def format_alert(findings: list[AuditFinding], ts: str) -> str:
    lines = [f"⚠️ Jarvis Task Auditor ({ts})"]
    by_cat: dict[str, list[str]] = {}
    for item in findings:
        by_cat.setdefault(item.category, []).append(item.detail)
    for cat, details in by_cat.items():
        lines.append(f"{cat}:")
        for detail in details[:5]:
            lines.append(f"  • {detail[:160]}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Jarvis task auditor")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--force-alert", action="store_true")
    args = parser.parse_args()

    load_runtime_env()
    ensure_backend_on_path()
    log = setup_logging("jarvis.task_auditor", verbose=args.verbose)

    if not automations_enabled():
        log.info("JARVIS_AUTOMATIONS_ENABLED is false; exiting")
        return 0

    findings = _fetch_findings()

    for item in findings:
        log.info("finding category=%s detail=%s", item.category, item.detail[:200])

    if not findings:
        log.info("no issues found")
        return 0

    if auto_remediation_enabled():
        remediation_dry_run = args.dry_run or auto_remediation_dry_run()
        remediation = remediate_audit_findings(findings, dry_run=remediation_dry_run, log=log)
        log.info(
            "task_auditor remediation dispatched=%s",
            remediation.get("dispatched", 0),
        )

    ts = utc_now_iso()
    cooldown = CooldownStore()
    alert_key = "task_auditor:" + "|".join(sorted(f"{f.category}:{f.detail[:40]}" for f in findings[:5]))
    cooldown_mins = default_cooldown_minutes()

    if not args.force_alert and not cooldown.should_send(alert_key, cooldown_mins):
        log.info("cooldown active; skip Telegram")
        return 0

    message = format_alert(findings, ts)
    sent = send_telegram_alert(message, dry_run=args.dry_run)
    if sent and not args.dry_run:
        cooldown.mark_sent(alert_key)
    return 0 if sent or args.dry_run else 1


if __name__ == "__main__":
    sys.exit(main())
