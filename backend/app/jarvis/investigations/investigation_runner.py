"""Investigation runner — multi-source evidence collection and orchestration."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.jarvis.execution_tools.registry import build_default_registry
from app.jarvis.investigations.evidence_model import (
    EvidenceItem,
    evidence_from_tool_output,
    merge_evidence,
)
from app.jarvis.investigations.investigation_report import (
    InvestigationReport,
    build_investigation_report,
    rank_root_causes,
)
from app.jarvis.investigations.investigation_types import (
    EvidenceCollector,
    InvestigationStatus,
    get_collectors_for_objective,
)
from app.jarvis.investigations.persistence import (
    get_investigation,
    list_investigations,
    save_investigation,
    search_investigations,
)

logger = logging.getLogger(__name__)

_READ_ONLY_TOOLS = frozenset(
    {
        "query_database",
        "search_logs",
        "search_repository",
        "diagnose_open_orders",
        "reconcile_crypto_com_open_orders",
        "read_logs",
        "inspect_health",
        "inspect_runtime",
        "inspect_container",
        "inspect_repository",
    }
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _invoke_collector(
    collector: EvidenceCollector,
    *,
    objective: str,
    registry: Any,
) -> dict[str, Any]:
    """Invoke a read-only evidence collector safely."""
    if collector.tool not in _READ_ONLY_TOOLS:
        return {"tool": collector.tool, "ok": False, "error": "write tool blocked"}

    action = collector.action or collector.tool
    kwargs: dict[str, Any] = {}
    if collector.tool in {
        "diagnose_open_orders",
        "reconcile_crypto_com_open_orders",
        "search_logs",
        "search_repository",
        "query_database",
        "read_logs",
    }:
        kwargs["objective"] = objective
        kwargs["action"] = action
    if collector.tool == "search_logs" and collector.params.get("keywords"):
        kwargs["keywords"] = collector.params["keywords"]
    if collector.tool == "search_repository" and collector.params.get("topic"):
        kwargs["topic"] = collector.params["topic"]

    result = registry.execute(collector.tool, **kwargs)
    output = dict(result.output or {})
    output["ok"] = result.ok and output.get("ok", True)
    if result.error:
        output["error"] = result.error
    return output


def _collect_portfolio_evidence() -> list[EvidenceItem]:
    """Supplement portfolio investigations with cache and equity diagnostics."""
    items: list[EvidenceItem] = []
    try:
        from app.jarvis.mvp.crypto_auditor_tools import get_portfolio_cache

        cache_result = get_portfolio_cache()
        if cache_result.get("ok"):
            from app.services.portfolio_cache import get_portfolio_summary

            last_updated = cache_result.get("last_updated")
            summary = get_portfolio_summary() or {}
            total = summary.get("total_usd")
            equity_source = summary.get("equity_source") or summary.get("total_usd_source")
            detail = f"Portfolio cache total_usd={total}; last_updated={last_updated}"
            if equity_source:
                detail += f"; equity_source={equity_source}"
            elif total is not None:
                detail += "; equity_source=derived_from_balances (exchange API omits equity field)"
            items.append(
                {
                    "source": "dashboard",
                    "reference": "portfolio_cache",
                    "detail": detail,
                    "confidence": "high",
                }
            )
    except Exception as exc:
        items.append(
            {
                "source": "dashboard",
                "reference": "portfolio_cache",
                "detail": f"Failed to read portfolio cache: {exc}",
                "confidence": "low",
            }
        )

    try:
        from app.jarvis.mvp.wallet_reconciliation import _fetch_live_account_summary, _scan_exchange_equity

        summary, err = _fetch_live_account_summary()
        if err:
            items.append(
                {
                    "source": "exchange",
                    "reference": "account_summary",
                    "detail": f"Exchange account summary error: {err}",
                    "confidence": "high",
                }
            )
            if "credential" in str(err).lower() or "not configured" in str(err).lower():
                items.append(
                    {
                        "source": "portfolio",
                        "reference": "equity_source",
                        "detail": "Exchange equity unavailable; portfolio total_usd is derived from cached balances instead of exchange-reported equity",
                        "confidence": "medium",
                    }
                )
        else:
            equity_fields = _scan_exchange_equity(summary)
            if equity_fields:
                top = list(equity_fields.items())[:3]
                items.append(
                    {
                        "source": "exchange",
                        "reference": "equity_fields",
                        "detail": f"Exchange equity fields found: {top}",
                        "confidence": "high",
                    }
                )
            else:
                items.append(
                    {
                        "source": "exchange",
                        "reference": "equity_fields",
                        "detail": "Exchange API response missing equity/net_equity field; portfolio total is derived from balances",
                        "confidence": "high",
                    }
                )
    except Exception as exc:
        items.append(
            {
                "source": "exchange",
                "reference": "account_summary",
                "detail": f"Failed to fetch exchange account summary: {exc}",
                "confidence": "low",
            }
        )

    return items


def _collect_auth_evidence() -> list[EvidenceItem]:
    """Supplement auth investigations with credential diagnostics."""
    items: list[EvidenceItem] = []
    try:
        from app.utils.credential_resolver import ensure_trade_client_crypto_credentials, CREDENTIAL_PAIRS
        import os

        meta = ensure_trade_client_crypto_credentials()
        diag = meta.get("credential_diagnostics") or {}
        present = [k for k, v in diag.items() if k.endswith("_PRESENT") and v]
        items.append(
            {
                "source": "authentication",
                "reference": "credential_diagnostics",
                "detail": f"Credential presence flags: {present}; used_pair={meta.get('used_pair_name')}",
                "confidence": "high",
            }
        )

        # Detect multiple credential pairs configured simultaneously.
        pairs_found = 0
        for key_name, secret_name in CREDENTIAL_PAIRS:
            if (os.getenv(key_name) or "").strip() and (os.getenv(secret_name) or "").strip():
                pairs_found += 1
        if pairs_found > 1:
            items.append(
                {
                    "source": "authentication",
                    "reference": "duplicated_secret",
                    "detail": (
                        f"Multiple credential pairs configured ({pairs_found} pairs). "
                        "Duplicated secret in runtime.env can cause Crypto.com auth failure (40101)."
                    ),
                    "confidence": "high",
                }
            )

        runtime_path = meta.get("runtime_env_path")
        if runtime_path:
            from pathlib import Path

            path = Path(runtime_path)
            if path.is_file():
                secret_lines = [
                    ln.strip()
                    for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines()
                    if "SECRET" in ln.upper() and "=" in ln and not ln.strip().startswith("#")
                ]
                if len(secret_lines) > 1:
                    items.append(
                        {
                            "source": "authentication",
                            "reference": "runtime_env",
                            "detail": (
                                f"runtime.env contains {len(secret_lines)} secret lines; "
                                "duplicate entries may override canonical credentials"
                            ),
                            "confidence": "high",
                        }
                    )
    except Exception as exc:
        items.append(
            {
                "source": "authentication",
                "reference": "credential_check",
                "detail": f"Credential diagnostic failed: {exc}",
                "confidence": "low",
            }
        )
    return items


def _count_recent_failures(tool_outputs: list[dict[str, Any]]) -> int:
    count = 0
    for output in tool_outputs:
        matches = output.get("matches") or []
        for match in matches:
            msg = str(match.get("message") or "").lower()
            if any(tok in msg for tok in ("error", "fail", "40101", "50001", "exception")):
                count += 1
        if output.get("error") or output.get("sync_status") in ("api_error", "failed_auth"):
            count += 1
    return count


def collect_evidence(
    objective: str,
    *,
    collectors: tuple[EvidenceCollector, ...] | None = None,
) -> tuple[list[EvidenceItem], list[dict[str, Any]], str, str]:
    """Collect multi-source evidence for an investigation objective."""
    category, template_id, resolved_collectors = get_collectors_for_objective(objective)
    use_collectors = collectors or resolved_collectors

    registry = build_default_registry()
    tool_outputs: list[dict[str, Any]] = []
    evidence_chunks: list[list[EvidenceItem]] = []

    for collector in use_collectors:
        try:
            output = _invoke_collector(collector, objective=objective, registry=registry)
            tool_outputs.append(output)
            evidence_chunks.append(evidence_from_tool_output(output))
        except Exception as exc:
            logger.warning("investigation collector %s failed: %s", collector.tool, exc)
            tool_outputs.append({"tool": collector.tool, "ok": False, "error": str(exc)})

    if category == "portfolio":
        evidence_chunks.append(_collect_portfolio_evidence())
    if category == "authentication":
        evidence_chunks.append(_collect_auth_evidence())

    evidence = merge_evidence(*evidence_chunks)
    return evidence, tool_outputs, category, template_id


def run_investigation(
    objective: str,
    *,
    investigation_id: str | None = None,
    persist: bool = True,
) -> InvestigationReport:
    """
    Run a full production diagnostic investigation end-to-end.

    Read-only: no writes, patches, orders, or GitHub actions.
    """
    inv_id = investigation_id or str(uuid.uuid4())
    objective_text = (objective or "").strip()
    if not objective_text:
        raise ValueError("investigation objective is required")

    evidence, tool_outputs, category, template_id = collect_evidence(objective_text)
    recent_failures = _count_recent_failures(tool_outputs)
    ranked = rank_root_causes(
        evidence=evidence,
        category=category,
        tool_outputs=tool_outputs,
        recent_failures=recent_failures,
    )

    report = build_investigation_report(
        investigation_id=inv_id,
        objective=objective_text,
        category=category,
        template_id=template_id,
        evidence=evidence,
        ranked_causes=ranked,
        tool_outputs=tool_outputs,
        created_at=_now_iso(),
    )

    if persist:
        save_investigation(report)

    return report


def search_prior_investigations(
    query: str,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search historical investigations by objective, root cause, or summary."""
    return search_investigations(query, limit=limit)


def get_investigation_detail(investigation_id: str) -> dict[str, Any] | None:
    row = get_investigation(investigation_id)
    return row


def list_investigation_history(*, limit: int = 20) -> list[dict[str, Any]]:
    return list_investigations(limit=limit)
