"""
Policy hooks for live trading and exchange mutations.

Contract (stable for future enforcement)
----------------------------------------
- **Real exchange mutations only:** gates must not block dry-run, local simulation, or any path
  where the broker would not perform a real HTTP mutation against the exchange.
- **DB-backed gate:** ``assert_exchange_mutation_allowed`` returns immediately when
  ``get_live_trading(db)`` is false, matching app-wide “live off ⇒ broker dry_run” behavior.
  Stricter rules added later run only after that check (governance, kill-switch, etc.).
- **Broker gate:** ``require_mutation_allowed_for_broker`` is invoked from ``crypto_com_trade``
  only **after** the client has resolved that the call will hit the real API (not dry-run /
  not ``live_trading`` short-circuit), including
  ``create_stop_loss_take_profit_with_variations`` (variant SL/TP fallback).
- **Read-only:** ``get_live_trading`` is a status helper; it does not block.

**Current posture:** ``assert_exchange_mutation_allowed`` is still a no-op after the live-trading
early exit. ``require_mutation_allowed_for_broker`` now enforces the **global trading kill switch**
(``TradingSettings.TRADING_KILL_SWITCH``) as defense-in-depth for order-placement operations:
when the kill switch is ON (or its state cannot be verified) it raises ``LiveTradingBlockedError``
so no real order can reach the exchange. Because the broker only invokes this hook after the
``actual_dry_run`` short-circuit, dry-run / simulation behavior is unchanged, and behavior is also
identical to before whenever the kill switch is OFF.

The file must exist in the tree (it was previously missing, causing ``ModuleNotFoundError``).
See ``docs/development/SERVICES_SINGLETON_IMPORTS.md`` for import/mocking notes.
"""
from typing import Any, Optional

from sqlalchemy.orm import Session


class LiveTradingBlockedError(Exception):
    """Raised when an exchange mutation is blocked by policy."""


def get_live_trading(db: Optional[Session]) -> bool:
    """True if live (non-paper) trading is enabled for this session/environment."""
    from app.utils.live_trading import get_live_trading_status

    return bool(get_live_trading_status(db))


def assert_exchange_mutation_allowed(
    db: Optional[Session],
    operation: str,
    symbol: Optional[str],
    _context: Any = None,
) -> None:
    """
    Pre-flight for code paths that may call the broker with intent to mutate the exchange.

    When live trading is **off** (DB/env via ``get_live_trading``), returns immediately so dry-run
    and simulation are never blocked here. When live is **on**, future policy may raise
    ``LiveTradingBlockedError``; call sites already catch it.
    """
    if not get_live_trading(db):
        return
    _ = operation, symbol, _context  # reserved for logging / future policy


# Broker operations that PLACE a real order. The global trading kill switch must
# block every one of these as defense-in-depth, even if an orchestration-layer gate
# (``can_place_real_order``) was missed. Non-placement mutations (e.g. ``cancel_order``)
# are intentionally NOT blocked so the operator can still reduce exposure.
_KILL_SWITCH_GUARDED_OPERATIONS = frozenset(
    {
        "place_market_order",
        "place_limit_order",
        "place_stop_loss_order",
        "place_take_profit_order",
        "create_stop_loss_take_profit_with_variations",
    }
)


def _trading_kill_switch_blocks() -> bool:
    """
    Return True if the global trading kill switch should block order placement.

    Fail-closed: if the kill switch state cannot be determined (no DB, read error),
    return True (block). Mirrors ``_get_telegram_kill_switch_status`` semantics.
    """
    try:
        from app.database import SessionLocal  # local import to avoid import cycles
    except Exception:
        return True  # fail-closed: cannot even import the session factory

    if SessionLocal is None:
        return True  # fail-closed: DB not configured -> cannot verify

    db = None
    try:
        db = SessionLocal()
        from app.utils.trading_guardrails import _get_telegram_kill_switch_status
        return bool(_get_telegram_kill_switch_status(db))
    except Exception:
        return True  # fail-closed: any error verifying -> block
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass


def require_mutation_allowed_for_broker(operation: str, symbol: Optional[str] = None) -> None:
    """
    Broker-only pre-flight: call **only** when this request will perform a real exchange mutation
    (after ``actual_dry_run`` / live short-circuits in ``crypto_com_trade``).

    No DB session is passed in. Enforces the global trading **kill switch** as a last-resort
    defense-in-depth control for order-placement operations: if the kill switch is ON (or its
    state cannot be verified), raises ``LiveTradingBlockedError`` so the order never reaches the
    exchange. Non-placement mutations (e.g. cancels) are not blocked.

    Callers typically do not catch this—prefer ``assert_exchange_mutation_allowed`` at the
    orchestration layer for graceful handling.
    """
    if operation in _KILL_SWITCH_GUARDED_OPERATIONS and _trading_kill_switch_blocks():
        raise LiveTradingBlockedError(
            f"blocked: trading kill switch is ON (operation={operation}, symbol={symbol})"
        )
