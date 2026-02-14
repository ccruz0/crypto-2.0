#!/usr/bin/env python3
"""
Portfolio consistency check: compare sum(open positions value) + free balance
vs exchange account summary. If drift > DRIFT_THRESHOLD_PCT (default 1%): FAIL.
Output: PASS or FAIL only. No secrets.
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logger = logging.getLogger(__name__)


def main() -> int:
    threshold_pct = float(os.environ.get("DRIFT_THRESHOLD_PCT", "1.0"))
    from app.database import SessionLocal
    from app.services.portfolio_cache import get_portfolio_summary
    from app.services.brokers.crypto_com_trade import trade_client

    if SessionLocal is None:
        print("FAIL")
        return 1
    db = SessionLocal()
    try:
        summary = get_portfolio_summary(db)
        dashboard_net = float(summary.get("total_usd") or 0.0)
        # Detect when equity is missing/unusable (derived path or non-positive)
        portfolio_value_source = summary.get("portfolio_value_source") or ""
        equity_missing = (
            portfolio_value_source == "derived:collateral_minus_borrowed"
            or (dashboard_net is not None and dashboard_net <= 0)
        )
        # Exposure = positions + open orders only (do not count borrowed/loans as exposure)
        open_pos = float(summary.get("open_positions_usd", 0) or 0)
        open_orders = float(summary.get("open_orders_usd", 0) or 0)
        has_exposure = (open_pos > 0) or (open_orders > 0)
        if equity_missing:
            if not has_exposure:
                logger.warning("equity_missing_but_no_positions_or_orders_skip_drift")
                print("PASS")
                return 0
            logger.error("equity_missing_with_positions_or_orders_fail")
            print("FAIL")
            return 1
        balance_data = trade_client.get_account_summary()
        if not balance_data or "accounts" not in balance_data:
            print("FAIL")
            return 1
        from app.services.portfolio_cache import _normalize_currency_name, get_crypto_prices
        prices = get_crypto_prices()
        exchange_net = 0.0
        for account in balance_data.get("accounts", []):
            currency = _normalize_currency_name(
                account.get("currency") or account.get("instrument_name") or account.get("symbol")
            )
            if not currency:
                continue
            balance = float(account.get("balance", 0))
            if balance < 0:
                borrowed = abs(float(account.get("borrowed_value", 0) or account.get("loan_value", 0)))
                if borrowed == 0 and currency in ["USD", "USDT", "USDC"]:
                    borrowed = abs(balance)
                elif borrowed == 0 and balance != 0:
                    borrowed = abs(balance) * prices.get(currency, 0)
                exchange_net -= borrowed
                continue
            market_val = account.get("market_value")
            usd = 0.0
            if market_val is not None:
                try:
                    usd = float(market_val) if not isinstance(market_val, str) else float(market_val.replace(",", "").strip() or 0)
                except (ValueError, TypeError):
                    pass
            if usd == 0 and currency in ["USD", "USDT", "USDC"]:
                usd = balance
            elif usd == 0 and currency in prices:
                usd = balance * prices[currency]
            exchange_net += usd
        ref = max(abs(exchange_net), 1.0)
        drift_pct = abs(dashboard_net - exchange_net) / ref * 100.0
        if drift_pct > threshold_pct:
            print("FAIL")
            return 1
        print("PASS")
        return 0
    except Exception:
        print("FAIL")
        return 1
    finally:
        try:
            db.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
