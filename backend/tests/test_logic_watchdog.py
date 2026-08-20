"""Unit tests for the logic watchdog detectors.

Runs entirely on in-memory SQLite with the real ORM models - no exchange,
no Telegram, no Postgres. Every detector is exercised for both the
positive case and the "must NOT fire" case, because a watchdog that cries
wolf is worse than no watchdog.

Destination: backend/tests/test_logic_watchdog.py
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.models.telegram_message import TelegramMessage
from app.models import watchdog as wd_models  # noqa: F401  (registers tables)
from app.services import logic_watchdog as lw


NOW = datetime(2026, 7, 28, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def db(monkeypatch):
    monkeypatch.setenv("WATCHDOG_WINDOW_HOURS", "6")
    monkeypatch.setenv("WATCHDOG_PROTECTION_GRACE_MIN", "15")
    monkeypatch.setenv("WATCHDOG_MIN_POSITION_USD", "5")
    engine = create_engine("sqlite://")
    # Only the tables this suite touches. Full metadata.create_all hits a
    # duplicate-index conflict on order_intents under SQLite.
    Base.metadata.create_all(
        engine,
        tables=[
            ExchangeOrder.__table__,
            TelegramMessage.__table__,
            wd_models.WatchdogAnomaly.__table__,
            wd_models.WatchdogFixRequest.__table__,
        ],
    )
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _order(db, oid, **kw):
    defaults = dict(
        exchange_order_id=oid,
        symbol="SOL_USD",
        side=OrderSideEnum.BUY,
        order_type="LIMIT",
        status=OrderStatusEnum.FILLED,
        price=100.0,
        quantity=1.0,
        cumulative_quantity=1.0,
        cumulative_value=100.0,
        avg_price=100.0,
        exchange_update_time=NOW - timedelta(hours=1),
        created_at=NOW - timedelta(hours=1),
    )
    defaults.update(kw)
    o = ExchangeOrder(**defaults)
    db.add(o)
    db.commit()
    return o


def _kinds(findings):
    return {f["kind"] for f in findings}


# ---------------------------------------------------------------- rule 1 ---
def test_entry_without_protection_is_flagged(db):
    _order(db, "ENTRY1")
    assert "MISSING_SL_TP" in _kinds(lw.detect_missing_protection(db, NOW))


def test_entry_with_both_legs_and_alert_is_clean(db):
    _order(db, "ENTRY1")
    _order(db, "SL1", order_type="STOP_LIMIT", order_role="STOP_LOSS", side=OrderSideEnum.SELL,
           status=OrderStatusEnum.ACTIVE, price=95.0, parent_order_id="ENTRY1")
    _order(db, "TP1", order_type="TAKE_PROFIT_LIMIT", order_role="TAKE_PROFIT", side=OrderSideEnum.SELL,
           status=OrderStatusEnum.ACTIVE, price=110.0, parent_order_id="ENTRY1")
    db.add(TelegramMessage(message="SL/TP ORDERS CREATED ... Entry Order: ENTRY1", symbol="SOL_USD",
                           timestamp=NOW - timedelta(minutes=55)))
    db.commit()
    assert lw.detect_missing_protection(db, NOW) == []


def test_legs_exist_but_no_telegram_alert_is_a_reporting_bug(db):
    """The TELEGRAM_SL_TP_FIX.md class: orders fine, notification lost."""
    _order(db, "ENTRY1")
    _order(db, "SL1", order_type="STOP_LIMIT", order_role="STOP_LOSS", side=OrderSideEnum.SELL,
           status=OrderStatusEnum.ACTIVE, price=95.0, parent_order_id="ENTRY1")
    _order(db, "TP1", order_type="TAKE_PROFIT_LIMIT", order_role="TAKE_PROFIT", side=OrderSideEnum.SELL,
           status=OrderStatusEnum.ACTIVE, price=110.0, parent_order_id="ENTRY1")
    found = lw.detect_missing_protection(db, NOW)
    assert _kinds(found) == {"PROTECTION_ALERT_LOST"}
    # and it must NOT be reported as a trading bug
    assert all(f["severity"] != "high" for f in found)


def test_only_stop_loss_missing(db):
    _order(db, "ENTRY1")
    _order(db, "TP1", order_type="TAKE_PROFIT_LIMIT", order_role="TAKE_PROFIT", side=OrderSideEnum.SELL,
           status=OrderStatusEnum.ACTIVE, price=110.0, parent_order_id="ENTRY1")
    assert "MISSING_SL" in _kinds(lw.detect_missing_protection(db, NOW))


def test_dust_position_is_ignored(db):
    _order(db, "ENTRY1", price=0.01, quantity=1.0, cumulative_quantity=1.0,
           cumulative_value=0.01, avg_price=0.01)
    assert lw.detect_missing_protection(db, NOW) == []


def test_position_closed_via_protection_is_clean(db):
    _order(db, "ENTRY1")
    _order(db, "TP1", order_type="TAKE_PROFIT_LIMIT", order_role="TAKE_PROFIT", side=OrderSideEnum.SELL,
           status=OrderStatusEnum.FILLED, price=110.0, parent_order_id="ENTRY1")
    assert lw.detect_missing_protection(db, NOW) == []


def test_fill_inside_grace_period_is_not_flagged_yet(db):
    _order(db, "ENTRY1", exchange_update_time=NOW - timedelta(minutes=5))
    assert lw.detect_missing_protection(db, NOW) == []


def test_naked_short_flagged_when_wallet_short(db):
    _order(
        db,
        "SHORT1",
        side=OrderSideEnum.SELL,
        symbol="ALGO_USD",
        quantity=1139.0,
        cumulative_quantity=1139.0,
        price=0.0876,
        avg_price=0.0876,
        cumulative_value=99.78,
    )
    found = lw.detect_missing_protection(db, NOW, wallet_by_base={"ALGO": -100.0})
    assert "MISSING_SL_TP" in _kinds(found)


def test_alert_sell_on_net_long_wallet_not_flagged(db):
    """ALGO case: ALERT SELL without SL/TP while wallet stays long is a long-close ghost."""
    _order(
        db,
        "SELL_LONG_CLOSE",
        side=OrderSideEnum.SELL,
        symbol="ALGO_USD",
        quantity=1139.0,
        cumulative_quantity=1139.0,
        price=0.0876,
        avg_price=0.0876,
        cumulative_value=99.78,
    )
    assert lw.detect_missing_protection(db, NOW, wallet_by_base={"ALGO": 1010.0}) == []


# ---------------------------------------------------------------- rule 2 ---
@pytest.mark.parametrize(
    "body,expected",
    [
        ("❌ <b>SL Order:</b> FAILED (no se pudo crear)", "SL_CREATION_FAILED"),
        ("❌ <b>TP Order:</b> FAILED (no se pudo crear)", "TP_CREATION_FAILED"),
        ("\U0001f6ab <b>PROTECTION ORDER REJECTED</b>", "PROTECTION_REJECTED"),
        ("⚠️ <b>CONDITIONAL ORDER REJECTED (140001)</b>", "CONDITIONAL_ORDER_140001"),
        ("❌ <b>ORDER FAILED</b>", "ORDER_FAILED"),
        ("⚠️ <b>POSICIÓN SIN PROTECCIÓN: SOL_USD</b>", "POSITION_UNPROTECTED_ALERT"),
    ],
)
def test_failure_strings_detected(db, body, expected):
    db.add(TelegramMessage(message=body, symbol="SOL_USD", timestamp=NOW - timedelta(minutes=30)))
    db.commit()
    assert _kinds(lw.detect_failure_strings(db, NOW)) == {expected}


def test_healthy_messages_produce_nothing(db):
    db.add(TelegramMessage(message="\U0001f7e2 <b>BUY ORDER CREATED</b> ... Order ID: X1",
                           symbol="SOL_USD", timestamp=NOW - timedelta(minutes=30)))
    db.add(TelegramMessage(message="\U0001f6e1️ <b>SL/TP ORDERS CREATED</b> ... all good",
                           symbol="SOL_USD", timestamp=NOW - timedelta(minutes=29)))
    db.commit()
    assert lw.detect_failure_strings(db, NOW) == []


def test_messages_outside_the_window_are_ignored(db):
    db.add(TelegramMessage(message="❌ <b>ORDER FAILED</b>", symbol="SOL_USD",
                           timestamp=NOW - timedelta(days=3)))
    db.commit()
    assert lw.detect_failure_strings(db, NOW) == []


# ---------------------------------------------------------------- rule 3 ---
def test_stop_loss_above_entry_on_a_long(db):
    _order(db, "ENTRY1")
    _order(db, "SL1", order_type="STOP_LIMIT", order_role="STOP_LOSS", side=OrderSideEnum.SELL,
           status=OrderStatusEnum.ACTIVE, price=105.0, parent_order_id="ENTRY1")
    assert "SL_WRONG_SIDE_OF_ENTRY" in _kinds(lw.detect_price_sanity(db, NOW))


def test_take_profit_below_entry_on_a_long(db):
    _order(db, "ENTRY1")
    _order(db, "TP1", order_type="TAKE_PROFIT_LIMIT", order_role="TAKE_PROFIT", side=OrderSideEnum.SELL,
           status=OrderStatusEnum.ACTIVE, price=90.0, parent_order_id="ENTRY1")
    assert "TP_WRONG_SIDE_OF_ENTRY" in _kinds(lw.detect_price_sanity(db, NOW))


def test_correct_prices_are_clean(db):
    _order(db, "ENTRY1")
    _order(db, "SL1", order_type="STOP_LIMIT", order_role="STOP_LOSS", side=OrderSideEnum.SELL,
           status=OrderStatusEnum.ACTIVE, price=95.0, trigger_condition=95.0, parent_order_id="ENTRY1")
    _order(db, "TP1", order_type="TAKE_PROFIT_LIMIT", order_role="TAKE_PROFIT", side=OrderSideEnum.SELL,
           status=OrderStatusEnum.ACTIVE, price=110.0, trigger_condition=110.0, parent_order_id="ENTRY1")
    assert lw.detect_price_sanity(db, NOW) == []


def test_trigger_price_mismatch(db):
    _order(db, "ENTRY1")
    _order(db, "SL1", order_type="STOP_LIMIT", order_role="STOP_LOSS", side=OrderSideEnum.SELL,
           status=OrderStatusEnum.ACTIVE, price=95.0, trigger_condition=99.0, parent_order_id="ENTRY1")
    assert "TRIGGER_PRICE_MISMATCH" in _kinds(lw.detect_price_sanity(db, NOW))


def test_protection_quantity_mismatch(db):
    _order(db, "ENTRY1")
    _order(db, "SL1", order_type="STOP_LIMIT", order_role="STOP_LOSS", side=OrderSideEnum.SELL,
           status=OrderStatusEnum.ACTIVE, price=95.0, quantity=0.5, parent_order_id="ENTRY1")
    assert "PROTECTION_QTY_MISMATCH" in _kinds(lw.detect_price_sanity(db, NOW))


def test_short_entry_direction_is_inverted(db):
    _order(db, "ENTRY1", side=OrderSideEnum.SELL)
    # For a SHORT, a valid SL sits ABOVE entry - this one is below, so it must fire.
    _order(db, "SL1", order_type="STOP_LIMIT", order_role="STOP_LOSS", side=OrderSideEnum.BUY,
           status=OrderStatusEnum.ACTIVE, price=95.0, parent_order_id="ENTRY1")
    assert "SL_WRONG_SIDE_OF_ENTRY" in _kinds(lw.detect_price_sanity(db, NOW))


# ---------------------------------------------------------------- rule 4 ---
def test_oco_sibling_not_cancelled(db):
    _order(db, "TP1", order_type="TAKE_PROFIT_LIMIT", order_role="TAKE_PROFIT", side=OrderSideEnum.SELL,
           status=OrderStatusEnum.FILLED, price=110.0, oco_group_id="OCO1",
           exchange_update_time=NOW - timedelta(hours=1))
    _order(db, "SL1", order_type="STOP_LIMIT", order_role="STOP_LOSS", side=OrderSideEnum.SELL,
           status=OrderStatusEnum.ACTIVE, price=95.0, oco_group_id="OCO1")
    found = lw.detect_orphans_and_oco(db, NOW)
    assert "OCO_SIBLING_NOT_CANCELLED" in _kinds(found)
    assert any(f["severity"] == "high" for f in found if f["kind"] == "OCO_SIBLING_NOT_CANCELLED")


def test_oco_properly_cancelled_is_clean(db):
    _order(db, "TP1", order_type="TAKE_PROFIT_LIMIT", order_role="TAKE_PROFIT", side=OrderSideEnum.SELL,
           status=OrderStatusEnum.FILLED, price=110.0, oco_group_id="OCO1")
    _order(db, "SL1", order_type="STOP_LIMIT", order_role="STOP_LOSS", side=OrderSideEnum.SELL,
           status=OrderStatusEnum.CANCELLED, price=95.0, oco_group_id="OCO1")
    assert "OCO_SIBLING_NOT_CANCELLED" not in _kinds(lw.detect_orphans_and_oco(db, NOW))


def test_orphan_leg_without_parent(db):
    _order(db, "SL1", order_type="STOP_LIMIT", order_role="STOP_LOSS", side=OrderSideEnum.SELL,
           status=OrderStatusEnum.ACTIVE, price=95.0, parent_order_id="GHOST")
    assert "ORPHAN_PROTECTION_NO_PARENT" in _kinds(lw.detect_orphans_and_oco(db, NOW))


def test_orphan_leg_with_cancelled_parent(db):
    _order(db, "ENTRY1", status=OrderStatusEnum.CANCELLED)
    _order(db, "SL1", order_type="STOP_LIMIT", order_role="STOP_LOSS", side=OrderSideEnum.SELL,
           status=OrderStatusEnum.ACTIVE, price=95.0, parent_order_id="ENTRY1")
    assert "ORPHAN_PROTECTION_DEAD_PARENT" in _kinds(lw.detect_orphans_and_oco(db, NOW))


# --------------------------------------------------------------- helpers ---
def test_role_detection():
    class O:
        order_role = None
        order_type = None

    o = O()
    o.order_type = "STOP_LIMIT"
    assert lw._role_of(o) == "SL"
    o.order_type = "TAKE_PROFIT_LIMIT"
    assert lw._role_of(o) == "TP"
    o.order_type = "LIMIT"
    assert lw._role_of(o) is None
    o.order_type = "MARKET"
    o.order_role = "ENTRY"
    assert lw._role_of(o) is None


def test_fingerprint_is_stable_and_distinct():
    a = lw._fingerprint("MISSING_SL_TP", "SOL_USD", "E1")
    assert a == lw._fingerprint("MISSING_SL_TP", "SOL_USD", "E1")
    assert a != lw._fingerprint("MISSING_SL_TP", "SOL_USD", "E2")
    assert a != lw._fingerprint("MISSING_SL", "SOL_USD", "E1")


def test_dry_run_writes_nothing(db):
    _order(db, "ENTRY1")
    res = lw.persist_and_alert(db, lw.detect_missing_protection(db, NOW), dry_run=True)
    assert res["dry_run"] is True
    assert res["would_create"] == 1
    assert db.query(wd_models.WatchdogAnomaly).count() == 0


# ---------------------------------------------------------------- rule 5 ---
# Protection type mismatch (#521): the books say STOP_LOSS, the exchange holds
# a plain LIMIT. Only the exchange can reveal it, so these tests stub it.


def _stub_types(monkeypatch, mapping):
    """Make the exchange answer `mapping[order_id]`; None means unreadable."""
    monkeypatch.setattr(lw, "_exchange_order_type", lambda oid: mapping.get(str(oid)))


def _protected_position(db):
    _order(db, "ENTRY1")
    _order(db, "SL1", order_type="STOP_LIMIT", order_role="STOP_LOSS", side=OrderSideEnum.SELL,
           status=OrderStatusEnum.ACTIVE, price=95.0, parent_order_id="ENTRY1")


def test_fake_stop_on_live_position_is_high_severity(db, monkeypatch):
    _protected_position(db)
    _stub_types(monkeypatch, {"SL1": "LIMIT"})
    findings = lw.detect_protection_type_mismatch(db, NOW)
    assert "protection_type_mismatch" in _kinds(findings)
    bad = [f for f in findings if f["kind"] == "protection_type_mismatch"][0]
    assert bad["severity"] == "high"
    assert bad["evidence"]["order_type_exchange"] == "LIMIT"
    assert bad["evidence"]["parent_position_live"] is True


def test_real_stop_limit_is_clean(db, monkeypatch):
    _protected_position(db)
    _stub_types(monkeypatch, {"SL1": "STOP_LIMIT"})
    assert lw.detect_protection_type_mismatch(db, NOW) == []


def test_take_profit_limit_is_clean(db, monkeypatch):
    _order(db, "ENTRY1")
    _order(db, "TP1", order_type="TAKE_PROFIT_LIMIT", order_role="TAKE_PROFIT",
           side=OrderSideEnum.SELL, status=OrderStatusEnum.ACTIVE, price=110.0,
           parent_order_id="ENTRY1")
    _stub_types(monkeypatch, {"TP1": "TAKE_PROFIT_LIMIT"})
    assert lw.detect_protection_type_mismatch(db, NOW) == []


def test_fake_stop_without_live_parent_is_medium(db, monkeypatch):
    # Parent cancelled -> nothing is exposed, so it must not page as high.
    _order(db, "ENTRY1", status=OrderStatusEnum.CANCELLED, cumulative_quantity=0.0)
    _order(db, "SL1", order_type="STOP_LIMIT", order_role="STOP_LOSS", side=OrderSideEnum.SELL,
           status=OrderStatusEnum.ACTIVE, price=95.0, parent_order_id="ENTRY1")
    _stub_types(monkeypatch, {"SL1": "LIMIT"})
    bad = [f for f in lw.detect_protection_type_mismatch(db, NOW)
           if f["kind"] == "protection_type_mismatch"][0]
    assert bad["severity"] == "medium"
    assert bad["evidence"]["parent_position_live"] is False


def test_dead_protection_legs_are_not_checked(db, monkeypatch):
    # A cancelled SL protects nothing; verifying it would only make noise.
    _order(db, "ENTRY1")
    _order(db, "SL1", order_type="STOP_LIMIT", order_role="STOP_LOSS", side=OrderSideEnum.SELL,
           status=OrderStatusEnum.CANCELLED, price=95.0, parent_order_id="ENTRY1")
    _stub_types(monkeypatch, {"SL1": "LIMIT"})
    assert lw.detect_protection_type_mismatch(db, NOW) == []


def test_unreadable_exchange_reports_instead_of_passing(db, monkeypatch):
    # Silence must never be mistaken for a clean result.
    _protected_position(db)
    _stub_types(monkeypatch, {})
    findings = lw.detect_protection_type_mismatch(db, NOW)
    assert "protection_type_unverified" in _kinds(findings)
    assert "protection_type_mismatch" not in _kinds(findings)


def test_truncation_is_reported_not_silent(db, monkeypatch):
    _order(db, "ENTRY1")
    for i in range(3):
        _order(db, f"SL{i}", order_type="STOP_LIMIT", order_role="STOP_LOSS",
               side=OrderSideEnum.SELL, status=OrderStatusEnum.ACTIVE, price=95.0,
               parent_order_id="ENTRY1")
    monkeypatch.setenv("WATCHDOG_MAX_TYPE_CHECKS", "1")
    _stub_types(monkeypatch, {"SL0": "STOP_LIMIT", "SL1": "STOP_LIMIT", "SL2": "STOP_LIMIT"})
    findings = lw.detect_protection_type_mismatch(db, NOW)
    trunc = [f for f in findings if f["kind"] == "protection_type_check_truncated"]
    assert trunc and trunc[0]["evidence"]["skipped"] == 2


def test_detector_is_registered_in_the_run(db):
    # A detector that exists but is never called is the #515 failure mode.
    assert lw.detect_protection_type_mismatch in lw.DETECTORS
