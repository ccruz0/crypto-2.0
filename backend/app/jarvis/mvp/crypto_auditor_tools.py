"""Read-only crypto portfolio tools for the Jarvis Crypto Auditor agent."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _tool_result(tool: str, *, success: bool = True, **payload: Any) -> dict[str, Any]:
    base = {
        "tool": tool,
        "success": success,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
    }
    base.update(payload)
    return base


def _safe_call(tool: str, fn) -> dict[str, Any]:
    try:
        return fn()
    except Exception as exc:
        logger.warning("crypto_auditor tool=%s error=%s", tool, exc)
        return _tool_result(tool, success=False, error=str(exc))


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def get_exchange_wallet() -> dict[str, Any]:
    """Fetch live Crypto.com Exchange wallet balances (read-only)."""

    def _run() -> dict[str, Any]:
        from app.services.brokers.crypto_com_trade import trade_client
        from app.services.portfolio_cache import _normalize_currency_name, get_crypto_prices
        from app.utils.credential_resolver import ensure_trade_client_crypto_credentials

        ensure_trade_client_crypto_credentials()
        summary = trade_client.get_account_summary() or {}
        if summary.get("skipped"):
            return _tool_result(
                "get_exchange_wallet",
                success=False,
                error=str(summary.get("reason") or "Crypto.com API skipped"),
            )
        accounts = summary.get("accounts") or []
        prices = get_crypto_prices()
        assets: list[dict[str, Any]] = []
        total_usd = 0.0
        for account in accounts:
            coin = _normalize_currency_name(
                account.get("currency") or account.get("instrument_name") or account.get("symbol")
            )
            if not coin:
                continue
            balance = _to_float(account.get("balance") or account.get("quantity") or account.get("available"))
            value_usd = _to_float(account.get("market_value") or account.get("usd_value"))
            if value_usd <= 0 and coin in ("USD", "USDT", "USDC"):
                value_usd = balance
            elif value_usd <= 0 and coin in prices:
                value_usd = balance * prices[coin]
            if balance <= 0 and value_usd <= 0:
                continue
            total_usd += value_usd
            assets.append(
                {
                    "currency": coin,
                    "balance": round(balance, 8),
                    "value_usd": round(value_usd, 2),
                }
            )
        return _tool_result(
            "get_exchange_wallet",
            total_usd=round(total_usd, 2),
            asset_count=len(assets),
            assets=assets[:100],
            live_api_available=bool(accounts),
        )

    return _safe_call("get_exchange_wallet", _run)


def get_dashboard_portfolio() -> dict[str, Any]:
    """Fetch internal dashboard portfolio valuation (read-only)."""

    def _run() -> dict[str, Any]:
        from app.database import SessionLocal
        from app.services.portfolio_cache import get_portfolio_summary

        db = SessionLocal()
        try:
            summary = get_portfolio_summary(db, request_context={"crypto_audit": True})
            balances = [
                {
                    "currency": row.get("currency"),
                    "balance": _to_float(row.get("balance")),
                    "value_usd": _to_float(row.get("usd_value")),
                }
                for row in (summary.get("balances") or [])
            ]
            return _tool_result(
                "get_dashboard_portfolio",
                total_usd=round(_to_float(summary.get("total_usd")), 2),
                total_assets_usd=round(_to_float(summary.get("total_assets_usd")), 2),
                total_collateral_usd=round(_to_float(summary.get("total_collateral_usd")), 2),
                total_borrowed_usd=round(_to_float(summary.get("total_borrowed_usd")), 2),
                portfolio_value_source=summary.get("portfolio_value_source"),
                open_positions_usd=round(_to_float(summary.get("open_positions_usd")), 2),
                open_orders_usd=round(_to_float(summary.get("open_orders_usd")), 2),
                last_updated=summary.get("last_updated"),
                balances=balances[:100],
            )
        finally:
            if db is not None:
                db.close()

    return _safe_call("get_dashboard_portfolio", _run)


def get_open_positions() -> dict[str, Any]:
    """List open positions from trade database (read-only)."""

    def _run() -> dict[str, Any]:
        from app.database import SessionLocal
        from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
        from app.services.order_position_service import count_open_positions_for_symbol
        from sqlalchemy import func

        db = SessionLocal()
        try:
            filled_statuses = [OrderStatusEnum.FILLED]
            symbols = (
                db.query(ExchangeOrder.symbol)
                .filter(
                    ExchangeOrder.side == OrderSideEnum.BUY,
                    ExchangeOrder.status.in_(filled_statuses),
                )
                .distinct()
                .all()
            )
            positions: list[dict[str, Any]] = []
            for (symbol,) in symbols:
                if not symbol:
                    continue
                count = count_open_positions_for_symbol(db, symbol)
                if count <= 0:
                    continue
                positions.append({"symbol": symbol, "open_commitments": count})

            pending_statuses = [
                OrderStatusEnum.NEW,
                OrderStatusEnum.ACTIVE,
                OrderStatusEnum.PARTIALLY_FILLED,
            ]
            pending_count = (
                db.query(func.count(ExchangeOrder.id))
                .filter(
                    ExchangeOrder.status.in_(pending_statuses),
                )
                .scalar()
                or 0
            )
            return _tool_result(
                "get_open_positions",
                open_position_count=len(positions),
                pending_order_count=int(pending_count),
                positions=positions[:100],
            )
        finally:
            if db is not None:
                db.close()

    return _safe_call("get_open_positions", _run)


def get_portfolio_cache() -> dict[str, Any]:
    """Inspect portfolio_balances cache freshness (read-only)."""

    def _run() -> dict[str, Any]:
        from app.database import SessionLocal
        from app.models.portfolio import PortfolioBalance
        from app.services.portfolio_cache import get_last_updated, get_portfolio_summary
        from sqlalchemy import func

        db = SessionLocal()
        try:
            row_count = db.query(func.count(PortfolioBalance.id)).scalar() or 0
            currency_count = db.query(func.count(func.distinct(PortfolioBalance.currency))).scalar() or 0
            latest = (
                db.query(func.max(PortfolioBalance.id))
                .scalar()
            )
            summary = get_portfolio_summary(db)
            cache_ts = get_last_updated(db)
            age_seconds = None
            if isinstance(cache_ts, (int, float)) and cache_ts > 0:
                age_seconds = round(time.time() - cache_ts, 1)
            return _tool_result(
                "get_portfolio_cache",
                row_count=int(row_count),
                currency_count=int(currency_count),
                latest_row_id=latest,
                cache_age_seconds=age_seconds,
                last_updated_iso=summary.get("last_updated"),
                stale_threshold_seconds=3600,
                potentially_stale=bool(age_seconds and age_seconds > 3600),
            )
        finally:
            if db is not None:
                db.close()

    return _safe_call("get_portfolio_cache", _run)


def get_trade_history_summary() -> dict[str, Any]:
    """Summarize recent trade history from exchange_orders (read-only)."""

    def _run() -> dict[str, Any]:
        from datetime import timedelta

        from app.database import SessionLocal
        from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
        from sqlalchemy import func

        db = SessionLocal()
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=30)
            total_orders = db.query(func.count(ExchangeOrder.id)).scalar() or 0
            filled_buy = (
                db.query(func.count(ExchangeOrder.id))
                .filter(
                    ExchangeOrder.side == OrderSideEnum.BUY,
                    ExchangeOrder.status == OrderStatusEnum.FILLED,
                )
                .scalar()
                or 0
            )
            filled_sell = (
                db.query(func.count(ExchangeOrder.id))
                .filter(
                    ExchangeOrder.side == OrderSideEnum.SELL,
                    ExchangeOrder.status == OrderStatusEnum.FILLED,
                )
                .scalar()
                or 0
            )
            recent_filled = (
                db.query(func.count(ExchangeOrder.id))
                .filter(
                    ExchangeOrder.status == OrderStatusEnum.FILLED,
                    ExchangeOrder.created_at >= cutoff,
                )
                .scalar()
                or 0
            )
            symbols_traded = (
                db.query(func.count(func.distinct(ExchangeOrder.symbol)))
                .filter(ExchangeOrder.status == OrderStatusEnum.FILLED)
                .scalar()
                or 0
            )
            return _tool_result(
                "get_trade_history_summary",
                total_orders=int(total_orders),
                filled_buy_count=int(filled_buy),
                filled_sell_count=int(filled_sell),
                recent_30d_filled=int(recent_filled),
                distinct_symbols_traded=int(symbols_traded),
                lookback_days=30,
            )
        finally:
            if db is not None:
                db.close()

    return _safe_call("get_trade_history_summary", _run)


def get_price_feed_status() -> dict[str, Any]:
    """Check Crypto.com public price feed health (read-only)."""

    def _run() -> dict[str, Any]:
        from app.services.portfolio_cache import get_crypto_prices

        started = time.time()
        prices = get_crypto_prices()
        elapsed_ms = round((time.time() - started) * 1000, 1)
        symbol_count = len(prices) if isinstance(prices, dict) else 0
        sample = sorted(prices.items(), key=lambda x: x[1], reverse=True)[:5] if prices else []
        stale = symbol_count < 10 or elapsed_ms > 5000
        return _tool_result(
            "get_price_feed_status",
            feed="crypto_com_public_get_tickers",
            symbol_count=symbol_count,
            latency_ms=elapsed_ms,
            sample_prices=[{"symbol": s, "price": p} for s, p in sample],
            potentially_stale=stale,
        )

    return _safe_call("get_price_feed_status", _run)


CRYPTO_AUDITOR_TOOLS: frozenset[str] = frozenset(
    {
        "get_exchange_wallet",
        "get_dashboard_portfolio",
        "get_open_positions",
        "get_portfolio_cache",
        "get_trade_history_summary",
        "get_price_feed_status",
    }
)

_CRYPTO_AUDITOR_HANDLERS = {
    "get_exchange_wallet": get_exchange_wallet,
    "get_dashboard_portfolio": get_dashboard_portfolio,
    "get_open_positions": get_open_positions,
    "get_portfolio_cache": get_portfolio_cache,
    "get_trade_history_summary": get_trade_history_summary,
    "get_price_feed_status": get_price_feed_status,
}


def run_crypto_auditor_tool(name: str) -> dict[str, Any]:
    """Execute one crypto auditor read-only tool."""
    tool = (name or "").strip()
    handler = _CRYPTO_AUDITOR_HANDLERS.get(tool)
    if handler is None:
        return _tool_result(tool, success=False, error=f"Unknown crypto auditor tool: {tool}")
    return handler()
