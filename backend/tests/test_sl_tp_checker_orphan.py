"""Tests for SL/TP orphan detection (exchange-aware, no false positives on standalone TPs)."""

from unittest.mock import MagicMock, patch

from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.services.sl_tp_checker import SLTPCheckerService


def _tp_order(
    order_id: str,
    *,
    parent_order_id=None,
    oco_group_id=None,
    symbol: str = "BTC_USD",
    price: float = 67000.0,
):
    order = MagicMock(spec=ExchangeOrder)
    order.exchange_order_id = order_id
    order.symbol = symbol
    order.order_type = "TAKE_PROFIT_LIMIT"
    order.order_role = "TAKE_PROFIT"
    order.side = OrderSideEnum.SELL
    order.status = OrderStatusEnum.ACTIVE
    order.price = price
    order.quantity = 1.3
    order.parent_order_id = parent_order_id
    order.oco_group_id = oco_group_id
    return order


def _mock_db_with_orders(orders):
    db = MagicMock()
    query = MagicMock()
    db.query.return_value = query
    query.filter.return_value = query
    query.all.return_value = orders
    query.first.return_value = None
    return db


def test_standalone_tp_on_exchange_not_flagged_without_parent_or_oco():
    """Legacy/manual trigger TPs on exchange must not alert as orphan."""
    checker = SLTPCheckerService()
    order = _tp_order("73817490101952837")
    db = _mock_db_with_orders([order])

    with patch.object(checker, "_fetch_exchange_open_order_ids", return_value={"73817490101952837"}):
        issues = checker._check_oco_issues(db)

    assert issues["orphaned_orders"] == []


def test_ghost_tp_not_on_exchange_is_flagged():
    """DB row ACTIVE but absent from unified exchange open orders is a true orphan."""
    checker = SLTPCheckerService()
    order = _tp_order(
        "73817490101967198",
        parent_order_id="5755600491541415740",
        oco_group_id="oco_5755600491541415740_1783513499",
        price=61720.39,
    )
    db = _mock_db_with_orders([order])

    with patch.object(
        checker,
        "_fetch_exchange_open_order_ids",
        return_value={"73817490101952837", "73817490101945043"},
    ):
        issues = checker._check_oco_issues(db)

    assert len(issues["orphaned_orders"]) == 1
    assert issues["orphaned_orders"][0]["order_id"] == "73817490101967198"
    assert "ACTIVE in DB but not on exchange" in issues["orphaned_orders"][0]["missing"]
    assert "missing parent_order_id" not in issues["orphaned_orders"][0]["missing"]


def test_oco_sibling_filled_still_flagged_when_on_exchange():
    """OCO integrity issue remains actionable even if order still shows on exchange."""
    checker = SLTPCheckerService()
    order = _tp_order(
        "tp-on-exchange",
        parent_order_id="parent-1",
        oco_group_id="oco-1",
    )
    sibling = MagicMock(spec=ExchangeOrder)
    sibling.status = OrderStatusEnum.FILLED
    sibling.order_role = "STOP_LOSS"
    sibling.exchange_order_id = "sl-filled"

    db = MagicMock()
    query = MagicMock()
    db.query.return_value = query
    query.filter.return_value = query

    def all_side_effect():
        # First call: active_sl_tp; second: oco siblings
        if not hasattr(all_side_effect, "n"):
            all_side_effect.n = 0
        all_side_effect.n += 1
        if all_side_effect.n == 1:
            return [order]
        return [sibling]

    query.all.side_effect = all_side_effect
    query.first.return_value = None

    with patch.object(checker, "_fetch_exchange_open_order_ids", return_value={"tp-on-exchange"}):
        issues = checker._check_oco_issues(db)

    assert len(issues["orphaned_orders"]) == 1
    assert "sibling STOP_LOSS sl-filled FILLED" in issues["orphaned_orders"][0]["missing"]


def test_no_ghost_alert_when_exchange_fetch_unavailable():
    """When unified fetch returns no IDs, do not mark every DB order as ghost."""
    checker = SLTPCheckerService()
    order = _tp_order("ghost-candidate")
    db = _mock_db_with_orders([order])

    with patch.object(checker, "_fetch_exchange_open_order_ids", return_value=set()):
        issues = checker._check_oco_issues(db)

    assert issues["orphaned_orders"] == []
