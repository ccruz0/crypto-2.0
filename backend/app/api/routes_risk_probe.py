"""
Dry-run risk guard probe: POST /api/risk/probe
Calls risk_guard.check_trade_allowed only. Does NOT place orders or sign requests.
No secrets in request/response or logs.
"""
import logging
from fastapi import APIRouter, HTTPException, Body
from fastapi.responses import JSONResponse

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_equity_from_exchange() -> tuple[float, float, float]:
    """
    Attempt to get account_equity, total_margin_exposure, daily_loss_pct from exchange.
    Returns (account_equity, total_margin_exposure, daily_loss_pct).
    Never logs or returns secrets. On failure raises ValueError.
    """
    try:
        from app.services.brokers.crypto_com_trade import CryptoComTradeClient
        client = CryptoComTradeClient()
        summary = client.get_account_summary()
        if not summary or isinstance(summary.get("skipped"), dict):
            raise ValueError("Exchange summary unavailable")
        equity = float(
            summary.get("margin_equity")
            or summary.get("account_equity")
            or summary.get("equity")
            or 0
        )
        exposure = float(summary.get("total_margin_exposure") or 0)
        daily_pct = float(summary.get("daily_loss_pct") or 0)
        if equity <= 0:
            raise ValueError("Account equity not available")
        return (equity, exposure, daily_pct)
    except Exception as e:
        logger.debug("Risk probe: could not get equity from exchange: %s", type(e).__name__)
        raise ValueError("Provide account_equity, total_margin_exposure, daily_loss_pct when exchange unavailable") from e


@router.post("/risk/probe")
def risk_probe(body: dict = Body(...)):
    """
    Dry-run risk guard probe. Runs check_trade_allowed only; does NOT place orders or sign.
    Optionally pass account_equity, total_margin_exposure, daily_loss_pct when exchange is unavailable.
    Returns 200 { "allowed": true } or 400 { "allowed": false, "reason": "...", "reason_code": "RISK_GUARD_BLOCKED" }.
    """
    try:
        symbol = str(body.get("symbol", "")).strip() or "UNKNOWN"
        side = str(body.get("side", "BUY")).upper()
        price = body.get("price")
        quantity = body.get("quantity")
        trade_value_usd = body.get("trade_value_usd")
        if trade_value_usd is not None:
            trade_value_usd = float(trade_value_usd)
        elif price is not None and quantity is not None:
            trade_value_usd = float(price) * float(quantity)
        else:
            trade_value_usd = 0.0
        entry_price = float(price) if price is not None else None
        is_margin = bool(body.get("is_margin", False))
        leverage = body.get("leverage")
        if leverage is not None:
            leverage = float(leverage)
        trade_on_margin_from_watchlist = bool(body.get("trade_on_margin_from_watchlist", True))

        account_equity = body.get("account_equity")
        total_margin_exposure = body.get("total_margin_exposure")
        daily_loss_pct = body.get("daily_loss_pct")
        if account_equity is not None:
            account_equity = float(account_equity)
        if total_margin_exposure is not None:
            total_margin_exposure = float(total_margin_exposure)
        if daily_loss_pct is not None:
            daily_loss_pct = float(daily_loss_pct)

        if account_equity is None or total_margin_exposure is None or daily_loss_pct is None:
            try:
                eq, exp, daily = _get_equity_from_exchange()
                if account_equity is None:
                    account_equity = eq
                if total_margin_exposure is None:
                    total_margin_exposure = exp
                if daily_loss_pct is None:
                    daily_loss_pct = daily
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={
                        "allowed": False,
                        "reason": "Provide account_equity, total_margin_exposure, daily_loss_pct for probe when exchange unavailable",
                        "reason_code": "RISK_GUARD_BLOCKED",
                    },
                )
        if total_margin_exposure is None:
            total_margin_exposure = 0.0
        if daily_loss_pct is None:
            daily_loss_pct = 0.0

        from app.services.risk_guard import check_trade_allowed, RiskViolationError

        check_trade_allowed(
            symbol=symbol,
            side=side,
            is_margin=is_margin,
            leverage=leverage,
            trade_value_usd=trade_value_usd,
            entry_price=entry_price,
            account_equity=account_equity,
            total_margin_exposure=total_margin_exposure,
            daily_loss_pct=daily_loss_pct,
            trade_on_margin_from_watchlist=trade_on_margin_from_watchlist,
        )
        return {"allowed": True}
    except RiskViolationError as e:
        return JSONResponse(
            status_code=400,
            content={
                "allowed": False,
                "reason": str(e),
                "reason_code": getattr(e, "reason_code", "RISK_GUARD_BLOCKED"),
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Risk probe error")
        return JSONResponse(
            status_code=500,
            content={
                "allowed": False,
                "reason": "Probe failed",
                "reason_code": "RISK_GUARD_BLOCKED",
            },
        )
