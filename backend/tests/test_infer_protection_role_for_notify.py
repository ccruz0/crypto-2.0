"""Infer SL/TP role for ORDER EXECUTED when exchange reports MARKET."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.exchange_sync import ExchangeSyncService


def test_infer_role_from_db_trigger_type_when_exchange_says_market():
    svc = ExchangeSyncService()
    order = SimpleNamespace(
        order_role=None,
        order_type="STOP_LIMIT",
        parent_order_id=None,
    )
    # History payload after trigger conversion often looks like a plain MARKET fill.
    role = svc._infer_protection_order_role(
        order,
        order_data={"order_type": "MARKET"},
        db=None,
    )
    assert role == "STOP_LOSS"


def test_infer_role_from_contingency_on_limit_fill():
    svc = ExchangeSyncService()
    order = SimpleNamespace(
        order_role=None,
        order_type="LIMIT",
        parent_order_id=None,
    )
    role = svc._infer_protection_order_role(
        order,
        order_data={"order_type": "LIMIT", "contingency_type": "TAKE_PROFIT"},
        db=None,
    )
    assert role == "TAKE_PROFIT"


def test_infer_role_from_trigger_parent_for_spot_child_market():
    svc = ExchangeSyncService()
    parent = SimpleNamespace(
        order_role="TAKE_PROFIT",
        order_type="TAKE_PROFIT_LIMIT",
    )
    child = SimpleNamespace(
        order_role=None,
        order_type="MARKET",
        parent_order_id="73817490102011214",
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = parent

    role = svc._infer_protection_order_role(child, order_data={"order_type": "MARKET"}, db=db)
    assert role == "TAKE_PROFIT"


def test_manual_market_not_inferred_as_protection():
    svc = ExchangeSyncService()
    order = SimpleNamespace(
        order_role=None,
        order_type="MARKET",
        parent_order_id=None,
    )
    role = svc._infer_protection_order_role(
        order,
        order_data={"order_type": "MARKET"},
        db=None,
    )
    assert role is None
