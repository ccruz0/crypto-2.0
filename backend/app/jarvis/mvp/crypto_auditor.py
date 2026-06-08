"""Compile Crypto Auditor findings from read-only portfolio tools."""

from __future__ import annotations

from typing import Any

from app.jarvis.mvp.crypto_auditor_tools import CRYPTO_AUDITOR_TOOLS, run_crypto_auditor_tool

_AUDIT_TOOL_ORDER = (
    "get_exchange_wallet",
    "get_dashboard_portfolio",
    "get_open_positions",
    "get_portfolio_cache",
    "get_trade_history_summary",
    "get_price_feed_status",
)

_PORTFOLIO_DIFF_ALERT_PCT = 5.0
_VALUE_TOLERANCE_USD = 1.0
_BALANCE_TOLERANCE = 1e-6


def is_crypto_audit_task(task: str) -> bool:
    """Return True when the task requests a crypto portfolio audit."""
    text = (task or "").lower()
    triggers = (
        "run crypto audit",
        "crypto audit",
        "audit portfolio",
        "reconcile wallet",
        "check portfolio consistency",
        "compare exchange and dashboard",
        "portfolio consistency",
        "audit crypto",
    )
    return any(t in text for t in triggers)


def run_crypto_audit() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run all crypto auditor tools and compile structured findings."""
    tool_results: list[dict[str, Any]] = []
    for tool in _AUDIT_TOOL_ORDER:
        tool_results.append(run_crypto_auditor_tool(tool))
    findings = compile_crypto_audit_findings(tool_results)
    return tool_results, findings


def _severity_for_finding(finding_type: str) -> str:
    critical = {"missing_asset", "balance_mismatch", "valuation_mismatch"}
    high = {"stale_cache", "stale_price_feed", "orphan_trade", "missing_position", "duplicate_position"}
    if finding_type in critical:
        return "critical"
    if finding_type in high:
        return "high"
    return "medium"


def compile_crypto_audit_findings(tool_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Build structured crypto audit output from tool results."""
    wallet_findings: list[dict[str, Any]] = []
    position_findings: list[dict[str, Any]] = []
    valuation_findings: list[dict[str, Any]] = []
    price_feed_findings: list[dict[str, Any]] = []
    recommendations: list[str] = []

    by_tool = {r.get("tool"): r for r in tool_results if isinstance(r, dict)}

    exchange = by_tool.get("get_exchange_wallet") or {}
    dashboard = by_tool.get("get_dashboard_portfolio") or {}
    positions = by_tool.get("get_open_positions") or {}
    cache = by_tool.get("get_portfolio_cache") or {}
    trades = by_tool.get("get_trade_history_summary") or {}
    price_feed = by_tool.get("get_price_feed_status") or {}

    exchange_total = float(exchange.get("total_usd") or 0) if exchange.get("success") else 0.0
    dashboard_total = float(dashboard.get("total_usd") or 0) if dashboard.get("success") else 0.0
    portfolio_difference_usd = round(exchange_total - dashboard_total, 2)
    portfolio_difference_pct = (
        round(abs(portfolio_difference_usd) / exchange_total * 100, 2) if exchange_total > 0 else 0.0
    )

    if not exchange.get("success"):
        wallet_findings.append(
            {
                "type": "unknown_asset",
                "severity": "high",
                "finding": "Could not fetch live Crypto.com exchange wallet",
                "error": exchange.get("error"),
            }
        )
        recommendations.append("Verify Crypto.com API credentials and proxy configuration.")

    if not dashboard.get("success"):
        wallet_findings.append(
            {
                "type": "stale_cache",
                "severity": "high",
                "finding": "Could not fetch dashboard portfolio summary",
                "error": dashboard.get("error"),
            }
        )

    if exchange.get("success") and dashboard.get("success"):
        exchange_assets = {
            a.get("currency"): a for a in (exchange.get("assets") or []) if a.get("currency")
        }
        dashboard_assets = {
            a.get("currency"): a for a in (dashboard.get("balances") or []) if a.get("currency")
        }
        all_coins = sorted(set(exchange_assets.keys()) | set(dashboard_assets.keys()))
        for coin in all_coins:
            ex = exchange_assets.get(coin, {"balance": 0.0, "value_usd": 0.0})
            dash = dashboard_assets.get(coin, {"balance": 0.0, "value_usd": 0.0})
            ex_bal = float(ex.get("balance") or 0)
            dash_bal = float(dash.get("balance") or 0)
            ex_val = float(ex.get("value_usd") or 0)
            dash_val = float(dash.get("value_usd") or 0)
            if ex_bal <= _BALANCE_TOLERANCE and dash_bal <= _BALANCE_TOLERANCE:
                continue
            if ex_bal > _BALANCE_TOLERANCE and dash_bal <= _BALANCE_TOLERANCE:
                wallet_findings.append(
                    {
                        "type": "missing_asset",
                        "severity": "critical",
                        "currency": coin,
                        "finding": f"{coin} present on exchange but missing in dashboard cache",
                        "exchange_balance": ex_bal,
                        "dashboard_balance": dash_bal,
                    }
                )
            elif abs(ex_bal - dash_bal) > _BALANCE_TOLERANCE:
                wallet_findings.append(
                    {
                        "type": "balance_mismatch",
                        "severity": "critical",
                        "currency": coin,
                        "finding": f"{coin} balance mismatch between exchange and dashboard",
                        "exchange_balance": ex_bal,
                        "dashboard_balance": dash_bal,
                        "difference_usd": round(ex_val - dash_val, 2),
                    }
                )
            elif abs(ex_val - dash_val) > _VALUE_TOLERANCE_USD:
                valuation_findings.append(
                    {
                        "type": "valuation_mismatch",
                        "severity": "critical",
                        "currency": coin,
                        "finding": f"{coin} USD valuation mismatch",
                        "exchange_value_usd": ex_val,
                        "dashboard_value_usd": dash_val,
                        "difference_usd": round(ex_val - dash_val, 2),
                    }
                )

        if abs(portfolio_difference_usd) > _VALUE_TOLERANCE_USD:
            wallet_findings.append(
                {
                    "type": "balance_mismatch",
                    "severity": "critical" if portfolio_difference_pct > _PORTFOLIO_DIFF_ALERT_PCT else "high",
                    "finding": (
                        f"Portfolio total mismatch: exchange ${exchange_total:,.2f} vs "
                        f"dashboard ${dashboard_total:,.2f}"
                    ),
                    "exchange_total_usd": exchange_total,
                    "dashboard_total_usd": dashboard_total,
                    "difference_usd": portfolio_difference_usd,
                    "difference_pct": portfolio_difference_pct,
                }
            )
            recommendations.append(
                "Run portfolio cache refresh and compare per-asset balances before any trading action."
            )

    if cache.get("success") and cache.get("potentially_stale"):
        wallet_findings.append(
            {
                "type": "stale_cache",
                "severity": "high",
                "finding": "Portfolio cache may be stale",
                "cache_age_seconds": cache.get("cache_age_seconds"),
                "row_count": cache.get("row_count"),
            }
        )
        recommendations.append("Refresh portfolio cache via exchange_sync to update stale balances.")

    if price_feed.get("success") and price_feed.get("potentially_stale"):
        price_feed_findings.append(
            {
                "type": "stale_price_feed",
                "severity": "high",
                "finding": "Crypto.com price feed may be stale or incomplete",
                "symbol_count": price_feed.get("symbol_count"),
                "latency_ms": price_feed.get("latency_ms"),
            }
        )
        recommendations.append("Check Crypto.com public ticker API connectivity and latency.")

    if positions.get("success"):
        open_count = int(positions.get("open_position_count") or 0)
        pending = int(positions.get("pending_order_count") or 0)
        if open_count == 0 and pending > 0 and trades.get("success"):
            filled_buy = int(trades.get("filled_buy_count") or 0)
            filled_sell = int(trades.get("filled_sell_count") or 0)
            if filled_buy > filled_sell:
                position_findings.append(
                    {
                        "type": "orphan_trade",
                        "severity": "high",
                        "finding": "Filled BUY orders exceed SELL closures but no open positions detected",
                        "filled_buy_count": filled_buy,
                        "filled_sell_count": filled_sell,
                        "pending_order_count": pending,
                    }
                )
        for pos in positions.get("positions") or []:
            if int(pos.get("open_commitments") or 0) > 3:
                position_findings.append(
                    {
                        "type": "duplicate_position",
                        "severity": "medium",
                        "symbol": pos.get("symbol"),
                        "finding": f"Multiple open commitments for {pos.get('symbol')}",
                        "open_commitments": pos.get("open_commitments"),
                    }
                )

    reconciliation_status = "pass"
    if wallet_findings or valuation_findings:
        reconciliation_status = "mismatch"
    if any(f.get("severity") == "critical" for f in wallet_findings + valuation_findings):
        reconciliation_status = "critical"

    total_findings = (
        len(wallet_findings)
        + len(position_findings)
        + len(valuation_findings)
        + len(price_feed_findings)
    )

    summary = {
        "tools_executed": len(tool_results),
        "tools_succeeded": sum(1 for r in tool_results if r.get("success")),
        "total_findings": total_findings,
        "wallet_findings_count": len(wallet_findings),
        "position_findings_count": len(position_findings),
        "valuation_findings_count": len(valuation_findings),
        "price_feed_findings_count": len(price_feed_findings),
        "exchange_total_usd": exchange_total,
        "dashboard_total_usd": dashboard_total,
        "reconciliation_status": reconciliation_status,
        "read_only": True,
    }

    if not recommendations:
        if reconciliation_status == "pass":
            recommendations.append("Portfolio is consistent within tolerance. No action required.")
        else:
            recommendations.append("Review findings manually; no automatic remediation will be applied.")

    return {
        "summary": summary,
        "wallet_findings": wallet_findings,
        "position_findings": position_findings,
        "valuation_findings": valuation_findings,
        "price_feed_findings": price_feed_findings,
        "recommendations": recommendations,
        "portfolio_difference_usd": portfolio_difference_usd,
        "portfolio_difference_pct": portfolio_difference_pct,
    }
