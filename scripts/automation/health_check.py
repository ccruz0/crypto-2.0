#!/usr/bin/env python3
"""Jarvis health check automation — runs every 5 minutes with auto-remediation."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.automation.common import (  # noqa: E402
    CooldownStore,
    automations_enabled,
    backend_base,
    check_websocket_prices,
    classify_exchange_credential_issue,
    dashboard_url,
    default_cooldown_minutes,
    docker_container_running,
    http_get,
    load_runtime_env,
    scan_docker_health_errors,
    setup_logging,
    utc_now_iso,
    ws_prices_url,
)
from scripts.automation.remediation import (  # noqa: E402
    FailureItem,
    auto_remediation_enabled,
    clear_remediation_state,
    dispatch_agent_for_incident,
    filter_false_positive_failures,
    mark_remediation_attempt,
    remediate_health_failures,
    should_attempt_remediation,
    should_trigger_remediation,
)
from scripts.automation.remediation_safety import auto_remediation_dry_run  # noqa: E402
from scripts.automation.telegram_helper import send_telegram_alert  # noqa: E402


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def run_checks() -> list[CheckResult]:
    base = backend_base()
    dash = dashboard_url()
    results: list[CheckResult] = []

    ok, detail, _ = http_get(f"{base}/ping_fast")
    results.append(CheckResult("backend_ping_fast", ok, detail))

    ok, detail, _ = http_get(dash)
    results.append(CheckResult("frontend_dashboard", ok, detail))

    ok, detail, _ = http_get(f"{base}/api/jarvis/tasks?limit=1")
    results.append(CheckResult("jarvis_tasks_api", ok, detail))

    ok, detail = check_websocket_prices(ws_prices_url())
    results.append(CheckResult("websocket_prices", ok, detail))

    for container in ("postgres_hardened", "market-updater", "atp-telegram-alerts"):
        ok, detail = docker_container_running(container)
        results.append(CheckResult(f"docker_{container}", ok, detail))

    log_hits = scan_docker_health_errors("backend-aws", tail=120)
    if log_hits:
        results.append(
            CheckResult(
                "backend_recent_errors",
                False,
                "; ".join(log_hits[:3]),
            )
        )
    else:
        results.append(CheckResult("backend_recent_errors", True, "no recent errors"))

    return results


def collect_exchange_warnings() -> tuple[str, str]:
    """Return (severity, message) for optional exchange integration issues."""
    return classify_exchange_credential_issue()


def format_alert(
    failures: list[CheckResult],
    ts: str,
    *,
    remediated: bool = False,
    agent_dispatched: bool = False,
) -> str:
    lines = [f"🚨 Jarvis Health Check FAIL ({ts})"]
    for item in failures:
        lines.append(f"• {item.name}: {item.detail[:180]}")
    if remediated:
        lines.append("🔧 Auto-remediation attempted (safe restarts / health fix).")
    if agent_dispatched:
        lines.append("🤖 Agent dispatched — Notion task created and scheduler triggered.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Jarvis production health check")
    parser.add_argument("--dry-run", action="store_true", help="Do not send Telegram alerts")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--force-alert", action="store_true", help="Bypass cooldown (testing)")
    args = parser.parse_args()

    load_runtime_env()
    log = setup_logging("jarvis.health_check", verbose=args.verbose)

    if not automations_enabled():
        log.info("JARVIS_AUTOMATIONS_ENABLED is false; exiting")
        return 0

    ts = utc_now_iso()
    results = run_checks()
    failures = filter_false_positive_failures([r for r in results if not r.ok])
    warn_severity, warn_detail = collect_exchange_warnings()

    for item in results:
        status = "OK" if item.ok else "FAIL"
        log.info("check=%s status=%s detail=%s", item.name, status, item.detail[:200])

    if warn_severity in ("warning", "error", "info"):
        log.warning(
            "exchange_integration severity=%s detail=%s",
            warn_severity,
            warn_detail[:200],
        )

    if not failures:
        log.info("all checks passed")
        clear_remediation_state()
        return 0

    remediated = False
    agent_dispatched = False
    failure_items = [FailureItem.from_check(f) for f in failures]
    remediation_dry_run = args.dry_run or auto_remediation_dry_run()

    if (
        auto_remediation_enabled()
        and should_trigger_remediation(failure_items)
        and should_attempt_remediation(failure_items)
    ):
        attempt = mark_remediation_attempt(failure_items)
        log.info(
            "auto-remediation starting attempt=%s dry_run=%s checks=%s",
            attempt,
            remediation_dry_run,
            [f.name for f in failures],
        )
        remediate_health_failures(failure_items, dry_run=remediation_dry_run, log=log)
        remediated = True
        results = run_checks()
        failures = filter_false_positive_failures([r for r in results if not r.ok])
        failure_items = [FailureItem.from_check(f) for f in failures]
        if not failures:
            log.info("all checks passed after remediation")
            clear_remediation_state()
            send_telegram_alert(
                f"✅ Jarvis Health Check recovered ({ts})\nAuto-remediation succeeded.",
                dry_run=args.dry_run,
            )
            return 0

    if auto_remediation_enabled() and failure_items:
        dispatch = dispatch_agent_for_incident(
            failure_items,
            source="jarvis-health-check",
            category="health_check",
            dry_run=remediation_dry_run,
            log=log,
        )
        agent_dispatched = bool(dispatch.get("ok"))

    cooldown = CooldownStore()
    alert_key = "health_check:" + "|".join(sorted(f.name for f in failures))
    cooldown_mins = default_cooldown_minutes()

    if not args.force_alert and not cooldown.should_send(alert_key, cooldown_mins):
        log.info("cooldown active for key=%s (%s min); skip Telegram", alert_key, cooldown_mins)
        return 1

    message = format_alert(
        failures,
        ts,
        remediated=remediated,
        agent_dispatched=agent_dispatched,
    )
    sent = send_telegram_alert(message, dry_run=args.dry_run)
    if sent and not args.dry_run:
        cooldown.mark_sent(alert_key)
    elif args.dry_run:
        log.info("dry-run: would mark cooldown for %s", alert_key)

    return 1


if __name__ == "__main__":
    sys.exit(main())
