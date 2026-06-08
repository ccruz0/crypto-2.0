"""Read-only Crypto.com wallet vs internal dashboard reconciliation for Jarvis MVP."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.services.brokers.crypto_com_trade import trade_client
from app.services.portfolio_cache import (
    _normalize_currency_name,
    get_crypto_prices,
    get_portfolio_summary,
    trade_client as portfolio_trade_client,
)
from app.utils.credential_resolver import ensure_trade_client_crypto_credentials
from app.services.portfolio_reconciliation import reconcile_portfolio_balances

logger = logging.getLogger(__name__)

_VALUE_TOLERANCE_USD = 1.0
_VALUE_TOLERANCE_PCT = 0.01
_BALANCE_TOLERANCE = 1e-6

_WALLET_RECONCILE_KEYWORDS = (
    "wallet mismatch",
    "dashboard balance wrong",
    "reconcile wallet",
    "crypto.com balance",
    "portfolio mismatch",
    "dashboard not matching wallet",
    "reconcile crypto",
    "wallet balance",
    "portfolio balance",
)


def is_wallet_reconcile_task(task: str) -> bool:
    """Return True when the task should route to wallet reconciliation."""
    text = (task or "").lower()
    return any(k in text for k in _WALLET_RECONCILE_KEYWORDS)


def _fetch_live_account_summary() -> tuple[dict[str, Any], str | None]:
    """Return account summary and optional error message."""
    ensure_trade_client_crypto_credentials()
    try:
        summary = portfolio_trade_client.get_account_summary() or {}
    except Exception as exc:
        return {}, str(exc)
    if summary.get("skipped"):
        return summary, str(summary.get("reason") or "Crypto.com API skipped")
    if summary.get("error") and not summary.get("accounts"):
        return summary, str(summary.get("error"))
    return summary, None


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _scan_exchange_equity(data: Any, prefix: str = "") -> dict[str, float]:
    """Recursively collect equity/balance numeric fields from Crypto.com API payload."""
    found: dict[str, float] = {}
    if not isinstance(data, dict):
        return found

    candidates = (
        "wallet_balance_after_haircut",
        "wallet_balance_af_haircut",
        "balance_after_haircut",
        "wallet_balance",
        "account_balance",
        "total_balance",
        "equity",
        "net_equity",
        "margin_equity",
        "market_value",
        "usd_value",
    )

    for key, value in data.items():
        key_lower = str(key).lower()
        path = f"{prefix}.{key}" if prefix else str(key)
        if key_lower in candidates or any(c in key_lower for c in ("wallet_balance", "equity", "after_haircut")):
            num = _to_float(value)
            if num != 0.0:
                found[path] = num
        if isinstance(value, dict):
            found.update(_scan_exchange_equity(value, path))
        elif isinstance(value, list):
            for idx, item in enumerate(value[:5]):
                if isinstance(item, dict):
                    found.update(_scan_exchange_equity(item, f"{path}[{idx}]"))
    return found


def _pick_exchange_total(equity_fields: dict[str, float], accounts: list[dict]) -> tuple[float, str]:
    """Choose Crypto.com wallet total using the same priority as portfolio_cache."""
    priority_patterns = [
        ("after_haircut", "wallet_balance_after_haircut"),
        ("wallet_balance", "wallet_balance"),
        ("account_balance", "account_balance"),
        ("equity", "equity"),
        ("margin_equity", "margin_equity"),
    ]
    for pattern, label in priority_patterns:
        for path, value in equity_fields.items():
            path_lower = path.lower().replace("-", "_")
            if pattern in path_lower:
                return value, label

    market_total = 0.0
    for account in accounts:
        mv = _to_float(account.get("market_value") or account.get("usd_value"))
        if mv > 0:
            market_total += mv
    if market_total > 0:
        return market_total, "sum_market_value"

    prices = get_crypto_prices()
    derived = 0.0
    for account in accounts:
        coin = _normalize_currency_name(
            account.get("currency") or account.get("instrument_name") or account.get("symbol")
        )
        if not coin:
            continue
        balance = _to_float(account.get("balance") or account.get("quantity") or account.get("available"))
        if balance <= 0:
            continue
        if coin in ("USD", "USDT", "USDC"):
            derived += balance
        elif coin in prices:
            derived += balance * prices[coin]
    if derived > 0:
        return derived, "derived_balance_times_price"
    return 0.0, "unavailable"


def _collect_crypto_assets(account_summary: dict) -> dict[str, dict[str, float]]:
    """Aggregate live Crypto.com balances and USD values by normalized coin."""
    assets: dict[str, dict[str, float]] = {}
    prices = get_crypto_prices()

    for account in account_summary.get("accounts") or []:
        coin = _normalize_currency_name(
            account.get("currency") or account.get("instrument_name") or account.get("symbol")
        )
        if not coin:
            continue
        balance = _to_float(account.get("balance") or account.get("quantity") or account.get("available"))
        if balance <= 0:
            continue

        value_usd = _to_float(account.get("market_value") or account.get("usd_value"))
        if value_usd <= 0 and coin in ("USD", "USDT", "USDC"):
            value_usd = balance
        elif value_usd <= 0 and coin in prices:
            value_usd = balance * prices[coin]

        haircut = _to_float(
            account.get("haircut")
            or account.get("collateral_ratio")
            or account.get("discount")
            or account.get("haircut_rate")
        )
        if coin in ("USD", "USDT", "USDC"):
            haircut = 0.0

        entry = assets.setdefault(coin, {"balance": 0.0, "value_usd": 0.0, "haircut": haircut})
        entry["balance"] += balance
        entry["value_usd"] += value_usd
        if haircut > entry["haircut"]:
            entry["haircut"] = haircut

    return assets


def _collect_dashboard_assets(portfolio_summary: dict) -> dict[str, dict[str, float]]:
    """Build dashboard asset map from get_portfolio_summary balances."""
    assets: dict[str, dict[str, float]] = {}
    for row in portfolio_summary.get("balances") or []:
        coin = _normalize_currency_name(row.get("currency"))
        if not coin:
            continue
        assets[coin] = {
            "balance": _to_float(row.get("balance")),
            "value_usd": _to_float(row.get("usd_value")),
        }
    return assets


def _classify_asset_issue(
    coin: str,
    cc_balance: float,
    dash_balance: float,
    cc_value: float,
    dash_value: float,
    cc_haircut: float,
    total_collateral_usd: float,
    total_borrowed_usd: float,
) -> str:
    if dash_balance <= _BALANCE_TOLERANCE and cc_balance > _BALANCE_TOLERANCE:
        return "missing_in_dashboard"
    if abs(cc_balance - dash_balance) > _BALANCE_TOLERANCE:
        return "balance_mismatch"
    if cc_balance > 0 and dash_balance > 0:
        cc_implied_price = cc_value / cc_balance if cc_balance else 0.0
        dash_implied_price = dash_value / dash_balance if dash_balance else 0.0
        if cc_implied_price > 0 and dash_implied_price > 0:
            price_delta_pct = abs(cc_implied_price - dash_implied_price) / cc_implied_price
            if price_delta_pct > _VALUE_TOLERANCE_PCT and abs(cc_value - dash_value) > _VALUE_TOLERANCE_USD:
                return "price_mismatch"
        if cc_haircut > 0 and dash_value > 0:
            expected_collateral = cc_value * (1 - cc_haircut)
            if abs(dash_value - expected_collateral) > _VALUE_TOLERANCE_USD and abs(cc_value - dash_value) > _VALUE_TOLERANCE_USD:
                return "haircut_mismatch"
    if abs(cc_value - dash_value) > _VALUE_TOLERANCE_USD:
        if dash_value <= _VALUE_TOLERANCE_USD and cc_value > _VALUE_TOLERANCE_USD:
            return "missing_in_dashboard"
        return "balance_mismatch"
    return "ok"


def _infer_root_causes(
    *,
    crypto_total: float,
    dashboard_total: float,
    portfolio_summary: dict,
    quantity_report: dict,
    asset_comparison: list[dict],
    exchange_source: str,
    live_api_error: str | None = None,
) -> tuple[list[str], list[str]]:
    causes: list[str] = []
    steps: list[str] = []

    portfolio_source = str(portfolio_summary.get("portfolio_value_source") or "unknown")
    total_assets = _to_float(portfolio_summary.get("total_assets_usd"))
    total_collateral = _to_float(portfolio_summary.get("total_collateral_usd"))
    total_borrowed = _to_float(portfolio_summary.get("total_borrowed_usd"))

    missing = [a for a in asset_comparison if a.get("issue") == "missing_in_dashboard"]
    price_issues = [a for a in asset_comparison if a.get("issue") == "price_mismatch"]
    balance_issues = [a for a in asset_comparison if a.get("issue") == "balance_mismatch"]
    haircut_issues = [a for a in asset_comparison if a.get("issue") == "haircut_mismatch"]

    if missing:
        symbols = ", ".join(a["coin"] for a in missing[:5])
        causes.append(f"Assets present on Crypto.com but missing or zero-valued in dashboard cache: {symbols}.")
        steps.append("Run portfolio cache refresh (exchange_sync) and verify portfolio_balances rows for missing symbols.")

    if price_issues:
        symbols = ", ".join(a["coin"] for a in price_issues[:5])
        causes.append(f"USD valuation mismatch — dashboard price feed may differ from Crypto.com market_value: {symbols}.")
        steps.append("Compare get_crypto_prices() tickers vs Crypto.com market_value per asset; check for stale/missing tickers.")

    if balance_issues:
        causes.append("Quantity mismatch between live Crypto.com balances and cached portfolio_balances.")
        steps.append("Inspect GET /api/diagnostics/portfolio-reconciliation for per-symbol quantity deltas.")

    if haircut_issues:
        causes.append("Haircut/collateral calculation may not match exchange-reported collateral.")
        steps.append("Enable reconcile_debug on dashboard state and compare exchange after-haircut fields vs derived collateral.")

    if portfolio_source.startswith("derived:") and crypto_total > dashboard_total * 1.5:
        causes.append(
            f"Dashboard NET uses derived source ({portfolio_source}) instead of exchange-reported wallet balance."
        )
        steps.append(
            "Verify Crypto.com API returns wallet_balance_after_haircut; set PORTFOLIO_EQUITY_FIELD_OVERRIDE if needed."
        )

    if total_assets > dashboard_total * 2 and total_collateral < total_assets * 0.5:
        causes.append(
            f"Large gross assets (${total_assets:,.2f}) with heavy haircuts (collateral ${total_collateral:,.2f})."
        )

    if total_borrowed > 0 and dashboard_total < total_collateral - total_borrowed * 0.5:
        causes.append(f"Active borrowed loans (${total_borrowed:,.2f}) reduce NET wallet balance on dashboard.")

    qty_missing = quantity_report.get("missing_in_portfolio") or []
    if qty_missing:
        causes.append(f"Live Crypto.com symbols not in portfolio_balances cache: {len(qty_missing)} symbol(s).")

    if exchange_source in ("unavailable", "derived_balance_times_price", "cache_collateral_estimate"):
        causes.append("Could not read exchange-reported wallet total; used fallback valuation from balances/prices.")

    if live_api_error:
        causes.append(f"Live Crypto.com API unavailable: {live_api_error}")

    if portfolio_source.startswith("derived:"):
        causes.append(
            f"Dashboard NET (${dashboard_total:,.2f}) uses derived collateral-minus-borrowed "
            f"instead of exchange wallet_balance_after_haircut."
        )
        steps.append(
            "Configure EXCHANGE_CUSTOM_API_KEY/SECRET (or crypto proxy) so dashboard can read exchange-reported wallet balance."
        )

    if total_assets > dashboard_total + _VALUE_TOLERANCE_USD and total_borrowed > 0:
        causes.append(
            f"Gross cached assets (${total_assets:,.2f}) exceed displayed NET (${dashboard_total:,.2f}); "
            f"borrowed loans (${total_borrowed:,.2f}) may explain part of the gap."
        )

    if not causes and abs(crypto_total - dashboard_total) <= _VALUE_TOLERANCE_USD:
        causes.append("Totals align within tolerance; any residual differences are rounding or timing.")

    if not steps:
        steps.append("Review asset_comparison for per-coin deltas and confirm dashboard uses portfolio.total_value_usd.")
    steps.append("Re-run this Jarvis tool after cache refresh; no trading or balance writes are required.")

    return causes, steps


def reconcile_crypto_wallet_vs_dashboard() -> dict[str, Any]:
    """
    Read-only diagnostic: compare Crypto.com Exchange wallet vs internal dashboard portfolio.
    Does not place orders, modify balances, or write to Crypto.com.
    """
    checked_at = datetime.now(timezone.utc).isoformat()
    base: dict[str, Any] = {
        "tool": "reconcile_crypto_wallet_vs_dashboard",
        "checked_at": checked_at,
        "read_only": True,
        "dry_run_safe": True,
    }

    try:
        from app.database import SessionLocal

        db = SessionLocal()
        try:
            client_meta = ensure_trade_client_crypto_credentials()
            portfolio_summary = get_portfolio_summary(
                db, request_context={"reconcile_debug": True}
            )
            dashboard_total = _to_float(portfolio_summary.get("total_usd"))
            dashboard_assets = _collect_dashboard_assets(portfolio_summary)
            total_collateral = _to_float(portfolio_summary.get("total_collateral_usd"))
            total_borrowed = _to_float(portfolio_summary.get("total_borrowed_usd"))
            total_assets = _to_float(portfolio_summary.get("total_assets_usd"))

            account_summary, live_api_error = _fetch_live_account_summary()
            accounts = account_summary.get("accounts") or []
            live_api_available = bool(accounts) and not account_summary.get("skipped")

            if live_api_available:
                equity_fields = _scan_exchange_equity(account_summary)
                crypto_com_total, exchange_source = _pick_exchange_total(equity_fields, accounts)
                crypto_assets = _collect_crypto_assets(account_summary)
                try:
                    quantity_report = reconcile_portfolio_balances(db)
                except Exception as qty_exc:
                    logger.warning("quantity reconciliation skipped: %s", qty_exc)
                    quantity_report = {
                        "missing_in_portfolio": [],
                        "missing_in_live": [],
                        "mismatched_quantities": [],
                    }
            else:
                exchange_source = "cache_collateral_estimate"
                crypto_com_total = total_collateral if total_collateral > 0 else total_assets
                crypto_assets = {
                    coin: {
                        "balance": data["balance"],
                        "value_usd": data["value_usd"],
                        "haircut": 0.0,
                    }
                    for coin, data in dashboard_assets.items()
                }
                quantity_report = {
                    "missing_in_portfolio": [],
                    "missing_in_live": [],
                    "mismatched_quantities": [],
                }

            all_coins = sorted(set(crypto_assets.keys()) | set(dashboard_assets.keys()))
            asset_comparison: list[dict[str, Any]] = []

            for coin in all_coins:
                cc = crypto_assets.get(coin, {"balance": 0.0, "value_usd": 0.0, "haircut": 0.0})
                dash = dashboard_assets.get(coin, {"balance": 0.0, "value_usd": 0.0})
                cc_balance = cc["balance"]
                dash_balance = dash["balance"]
                cc_value = cc["value_usd"]
                dash_value = dash["value_usd"]
                diff_usd = round(cc_value - dash_value, 2)
                issue = _classify_asset_issue(
                    coin,
                    cc_balance,
                    dash_balance,
                    cc_value,
                    dash_value,
                    cc.get("haircut", 0.0),
                    total_collateral,
                    total_borrowed,
                )
                if cc_balance <= _BALANCE_TOLERANCE and dash_balance <= _BALANCE_TOLERANCE and cc_value <= 0 and dash_value <= 0:
                    continue
                asset_comparison.append(
                    {
                        "coin": coin,
                        "crypto_com_balance": round(cc_balance, 8),
                        "dashboard_balance": round(dash_balance, 8),
                        "crypto_com_value_usd": round(cc_value, 2),
                        "dashboard_value_usd": round(dash_value, 2),
                        "difference_usd": diff_usd,
                        "issue": issue,
                    }
                )

            asset_comparison.sort(key=lambda row: abs(row.get("difference_usd") or 0), reverse=True)

            difference_usd = round(crypto_com_total - dashboard_total, 2)
            difference_pct = (
                round(abs(difference_usd) / crypto_com_total * 100, 2) if crypto_com_total > 0 else 0.0
            )

            if not live_api_available and live_api_error:
                status = "failed" if dashboard_total <= 0 else "mismatch"
            elif crypto_com_total <= 0 and dashboard_total <= 0:
                status = "failed"
            elif abs(difference_usd) <= _VALUE_TOLERANCE_USD:
                status = "pass"
            else:
                status = "mismatch"

            probable_root_causes, recommended_next_steps = _infer_root_causes(
                crypto_total=crypto_com_total,
                dashboard_total=dashboard_total,
                portfolio_summary=portfolio_summary,
                quantity_report=quantity_report,
                asset_comparison=asset_comparison,
                exchange_source=exchange_source,
                live_api_error=live_api_error,
            )

            prices = get_crypto_prices()
            payload: dict[str, Any] = {
                **base,
                "status": status,
                "crypto_com_total_usd": round(crypto_com_total, 2),
                "dashboard_total_usd": round(dashboard_total, 2),
                "difference_usd": difference_usd,
                "difference_pct": difference_pct,
                "crypto_com_total_source": exchange_source,
                "dashboard_value_source": portfolio_summary.get("portfolio_value_source"),
                "dashboard_total_assets_usd": round(total_assets, 2),
                "dashboard_total_collateral_usd": round(total_collateral, 2),
                "dashboard_total_borrowed_usd": round(total_borrowed, 2),
                "live_api_available": live_api_available,
                "price_feed": "crypto_com_public_get_tickers",
                "price_feed_symbols": len(prices),
                "quantity_reconciliation": {
                    "missing_in_portfolio": len(quantity_report.get("missing_in_portfolio") or []),
                    "missing_in_live": len(quantity_report.get("missing_in_live") or []),
                    "mismatched_quantities": len(quantity_report.get("mismatched_quantities") or []),
                },
                "asset_comparison": asset_comparison,
                "probable_root_causes": probable_root_causes,
                "recommended_next_steps": recommended_next_steps,
                "client_meta": {
                    "credentials_loaded": client_meta.get("credentials_loaded"),
                    "proxy_enabled": client_meta.get("proxy_enabled"),
                },
            }
            if live_api_error and not live_api_available:
                payload["error"] = live_api_error
                payload["note"] = (
                    "Live Crypto.com fetch failed; crypto_com_total_usd uses cached collateral estimate. "
                    "Configure API credentials or crypto proxy for exchange-reported totals."
                )
            return payload
        finally:
            if db is not None:
                db.close()
    except Exception as exc:
        logger.exception("reconcile_crypto_wallet_vs_dashboard failed")
        return {
            **base,
            "status": "failed",
            "success": False,
            "error": str(exc),
            "crypto_com_total_usd": 0.0,
            "dashboard_total_usd": 0.0,
            "difference_usd": 0.0,
            "difference_pct": 0.0,
            "asset_comparison": [],
            "probable_root_causes": [f"Diagnostic failed: {exc}"],
            "recommended_next_steps": ["Check backend logs and Crypto.com API connectivity."],
        }
