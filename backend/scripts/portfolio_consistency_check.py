#!/usr/bin/env python3
"""
Portfolio consistency check: compare our total_usd to exchange equity; fail if drift > threshold
or if data is missing (unless ALLOW_EMPTY_PORTFOLIO=1). Used by scripts/aws/portfolio_consistency_check.sh.
Strict semantics: exit 0 only when data available and drift <= threshold; exit 1 on exception,
missing data, or drift > threshold.
"""
import os
import sys
import logging
from typing import Optional

# Add backend to path when run as script
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)
debug = os.environ.get("DEBUG", "").strip() == "1"


def _extract_exchange_equity(balance_data: dict) -> Optional[float]:
    """Extract single equity value from get_account_summary-style response. Returns None if none found."""
    if not balance_data or not isinstance(balance_data, dict):
        return None
    # Minimal scan: check accounts[0] for common equity keys
    accounts = balance_data.get("accounts") or balance_data.get("result", {}).get("accounts")
    if isinstance(accounts, list) and len(accounts) > 0:
        acc = accounts[0] if isinstance(accounts[0], dict) else {}
        for key in (
            "wallet_balance_after_haircut", "wallet_balance_af_haircut",
            "account_balance", "wallet_balance", "total_balance",
            "equity", "net_equity", "margin_equity",
        ):
            val = acc.get(key)
            if val is not None:
                try:
                    v = float(str(val).strip().replace(",", "").replace(" ", ""))
                    if v != 0:
                        return v
                except (ValueError, TypeError):
                    pass
    # Top-level equity-like keys
    for key in ("wallet_balance", "account_balance", "equity", "total_usd"):
        val = balance_data.get(key)
        if val is not None:
            try:
                v = float(str(val).strip().replace(",", "").replace(" ", ""))
                if v != 0:
                    return v
            except (ValueError, TypeError):
                pass
    return None


def main() -> int:
    try:
        from sqlalchemy.exc import OperationalError
        from app.database import SessionLocal
        from app.services.portfolio_cache import get_portfolio_summary
    except Exception as e:
        logger.exception("Import failed")
        print("FAIL")
        return 1

    allow_empty = os.environ.get("ALLOW_EMPTY_PORTFOLIO", "").strip() == "1"
    threshold_pct = float(os.environ.get("DRIFT_THRESHOLD_PCT", "1.0"))
    max_retries = 2
    last_err = None

    for attempt in range(1, max_retries + 1):
        try:
            if SessionLocal is None:
                print("FAIL")
                logger.error("Database not configured")
                return 1
            db = SessionLocal()
            try:
                summary = get_portfolio_summary(db, request_context=None)
            finally:
                db.close()
            if not summary or not isinstance(summary, dict):
                if allow_empty:
                    print("PASS")
                    return 0
                print("FAIL")
                logger.error("No portfolio summary")
                return 1
            our_total = summary.get("total_usd")
            if our_total is None:
                our_total = 0.0
            else:
                try:
                    our_total = float(our_total)
                except (TypeError, ValueError):
                    our_total = 0.0
            balances = summary.get("balances") or []
            has_data = (our_total > 0) or (len(balances) > 0)

            # Check exchange for equity (for drift) and for "has data"
            exchange_equity = None
            try:
                from app.services.brokers.crypto_com_trade import trade_client
                from app.utils.credential_resolver import resolve_crypto_credentials
                api_key, api_secret, _, _ = resolve_crypto_credentials()
                if api_key and api_secret:
                    if trade_client.api_key != api_key or trade_client.api_secret != api_secret:
                        trade_client.api_key = api_key
                        trade_client.api_secret = api_secret
                balance_data = trade_client.get_account_summary()
                if isinstance(balance_data, dict) and balance_data.get("accounts"):
                    has_data = True
                exchange_equity = _extract_exchange_equity(balance_data or {})
            except Exception as api_err:
                last_err = api_err
                if debug:
                    logger.info("Exchange API error: %s", type(api_err).__name__)
                # No exchange data -> fail unless allow_empty and we have no data anyway
                if not has_data and allow_empty:
                    print("PASS")
                    return 0
                print("FAIL")
                logger.error("Exchange/portfolio data unavailable")
                return 1

            if not has_data and not allow_empty:
                print("FAIL")
                logger.error("No portfolio/balance data")
                return 1
            if allow_empty and not has_data and exchange_equity is None:
                print("PASS")
                return 0

            # Drift: compare our total to exchange
            ref = exchange_equity if exchange_equity is not None and exchange_equity != 0 else our_total
            if ref is None or ref == 0:
                if allow_empty:
                    print("PASS")
                    return 0
                print("FAIL")
                logger.error("No reference value for drift")
                return 1
            drift_pct = abs((our_total or 0) - (exchange_equity or 0)) / float(ref) * 100.0
            if drift_pct > threshold_pct:
                print("FAIL")
                if debug:
                    logger.info("drift_pct=%.2f threshold=%.2f", drift_pct, threshold_pct)
                logger.error("Drift above threshold")
                return 1
            print("PASS")
            if debug:
                logger.info("drift_pct=%.2f threshold=%.2f", drift_pct, threshold_pct)
            return 0
        except OperationalError as e:
            last_err = e
            if debug:
                logger.info("Attempt %s: DB error: %s", attempt, type(e).__name__)
            if attempt == max_retries:
                print("FAIL")
                logger.error("DB unreachable after retries")
                return 1
        except Exception as e:
            print("FAIL")
            logger.exception("Portfolio check failed")
            return 1
    print("FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
