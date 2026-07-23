"""Bot-managed OCO: when TP (or SL) fills, cancel the ACTIVE sibling."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.models.exchange_order import OrderStatusEnum
from app.services.exchange_sync import ExchangeSyncService


def _order(
    *,
    oid: str,
    role: str,
    status,
    oco_group_id: str | None = "oco_5755600491541413116_1",
    parent_order_id: str | None = "5755600491541413116",
    order_type: str | None = None,
    symbol: str = "BTC_USD",
    recent: bool = True,
):
    o = MagicMock()
    o.exchange_order_id = oid
    o.order_role = role
    o.status = status
    o.oco_group_id = oco_group_id
    o.parent_order_id = parent_order_id
    o.symbol = symbol
    o.order_type = order_type or (
        "TAKE_PROFIT_LIMIT" if role == "TAKE_PROFIT" else "STOP_LIMIT"
    )
    o.side = MagicMock(value="SELL")
    now = datetime.now(timezone.utc)
    if recent:
        o.exchange_update_time = now
        o.exchange_create_time = now
    else:
        o.exchange_update_time = datetime(2026, 7, 9, tzinfo=timezone.utc)
        o.exchange_create_time = datetime(2026, 7, 8, tzinfo=timezone.utc)
    return o


class TestFindOcoSiblings:
    def test_finds_by_oco_group_id(self):
        svc = ExchangeSyncService()
        filled = _order(oid="73817490101967200", role="TAKE_PROFIT", status=OrderStatusEnum.FILLED)
        sibling = _order(oid="73817490101967199", role="STOP_LOSS", status=OrderStatusEnum.ACTIVE)

        qm = MagicMock()
        qm.filter.return_value = qm
        qm.all.return_value = [sibling]
        db = MagicMock()
        db.query.return_value = qm

        found = svc._find_oco_siblings(db, filled)
        assert len(found) == 1
        assert found[0].exchange_order_id == "73817490101967199"

    def test_finds_by_parent_and_opposite_role_when_no_oco_group(self):
        svc = ExchangeSyncService()
        filled = _order(
            oid="tp-1",
            role="TAKE_PROFIT",
            status=OrderStatusEnum.FILLED,
            oco_group_id=None,
            parent_order_id="parent-buy-1",
        )
        sibling = _order(
            oid="sl-1",
            role="STOP_LOSS",
            status=OrderStatusEnum.ACTIVE,
            oco_group_id=None,
            parent_order_id="parent-buy-1",
        )

        calls = {"n": 0}

        def _all():
            calls["n"] += 1
            # First query is oco_group (skipped); only parent query runs
            return [sibling]

        qm = MagicMock()
        qm.filter.return_value = qm
        qm.all.side_effect = _all
        db = MagicMock()
        db.query.return_value = qm

        found = svc._find_oco_siblings(db, filled)
        assert len(found) == 1
        assert found[0].exchange_order_id == "sl-1"

    def test_no_linkage_returns_empty_without_null_oco_scan(self):
        svc = ExchangeSyncService()
        filled = _order(
            oid="tp-1",
            role="TAKE_PROFIT",
            status=OrderStatusEnum.FILLED,
            oco_group_id=None,
            parent_order_id=None,
        )
        db = MagicMock()
        assert svc._find_oco_siblings(db, filled) == []
        db.query.assert_not_called()


class TestCancelOcoSiblingBotCase:
    def test_filled_tp_cancels_active_sl_via_advanced_type(self):
        """Production-like bot OCO: filled TP + ACTIVE SL same oco_group_id / parent."""
        svc = ExchangeSyncService()
        filled = _order(
            oid="73817490101967200",
            role="TAKE_PROFIT",
            status=OrderStatusEnum.FILLED,
            order_type="TAKE_PROFIT_LIMIT",
        )
        sibling = _order(
            oid="73817490101967199",
            role="STOP_LOSS",
            status=OrderStatusEnum.ACTIVE,
            order_type="STOP_LIMIT",
        )

        with patch.object(svc, "_find_oco_siblings", return_value=[sibling]), patch(
            "app.services.live_trading_gate.assert_exchange_mutation_allowed"
        ), patch(
            "app.services.brokers.crypto_com_trade.trade_client.cancel_order",
            return_value={"order_id": sibling.exchange_order_id},
        ) as cancel, patch.object(
            svc, "_send_oco_cancellation_notification"
        ) as notify:
            db = MagicMock()
            ok = svc._cancel_oco_sibling(db, filled)

        assert ok is True
        cancel.assert_called_once_with("73817490101967199", order_type="STOP_LIMIT")
        assert sibling.status == OrderStatusEnum.CANCELLED
        db.commit.assert_called()
        notify.assert_called_once()

    def test_does_not_cancel_already_filled_sibling(self):
        svc = ExchangeSyncService()
        filled = _order(oid="tp-1", role="TAKE_PROFIT", status=OrderStatusEnum.FILLED)
        sibling = _order(oid="sl-1", role="STOP_LOSS", status=OrderStatusEnum.FILLED)

        with patch.object(svc, "_find_oco_siblings", return_value=[sibling]), patch(
            "app.services.brokers.crypto_com_trade.trade_client.cancel_order"
        ) as cancel:
            db = MagicMock()
            ok = svc._cancel_oco_sibling(db, filled)

        assert ok is True
        cancel.assert_not_called()

    def test_already_gone_on_exchange_marks_cancelled(self):
        svc = ExchangeSyncService()
        filled = _order(oid="tp-1", role="TAKE_PROFIT", status=OrderStatusEnum.FILLED)
        sibling = _order(oid="sl-1", role="STOP_LOSS", status=OrderStatusEnum.ACTIVE)

        with patch.object(svc, "_find_oco_siblings", return_value=[sibling]), patch(
            "app.services.live_trading_gate.assert_exchange_mutation_allowed"
        ), patch(
            "app.services.brokers.crypto_com_trade.trade_client.cancel_order",
            return_value={"error": "Order not found"},
        ), patch.object(svc, "_send_oco_cancellation_notification"):
            db = MagicMock()
            ok = svc._cancel_oco_sibling(db, filled)

        assert ok is True
        assert sibling.status == OrderStatusEnum.CANCELLED

    def test_maps_role_to_conditional_type_when_order_type_missing(self):
        svc = ExchangeSyncService()
        filled = _order(oid="tp-1", role="TAKE_PROFIT", status=OrderStatusEnum.FILLED)
        sibling = _order(oid="sl-1", role="STOP_LOSS", status=OrderStatusEnum.ACTIVE)
        sibling.order_type = None

        with patch.object(svc, "_find_oco_siblings", return_value=[sibling]), patch(
            "app.services.live_trading_gate.assert_exchange_mutation_allowed"
        ), patch(
            "app.services.brokers.crypto_com_trade.trade_client.cancel_order",
            return_value={"order_id": "sl-1"},
        ) as cancel, patch.object(svc, "_send_oco_cancellation_notification"):
            assert svc._cancel_oco_sibling(MagicMock(), filled) is True

        cancel.assert_called_once_with("sl-1", order_type="STOP_LIMIT")


class TestSweepOrphanedOcoSiblings:
    def test_sweeps_active_sl_still_in_open_orders(self):
        svc = ExchangeSyncService()
        orphan_sl = _order(
            oid="73817490101967199",
            role="STOP_LOSS",
            status=OrderStatusEnum.ACTIVE,
            recent=False,
        )
        filled_tp = _order(
            oid="73817490101967200",
            role="TAKE_PROFIT",
            status=OrderStatusEnum.FILLED,
            recent=False,
        )

        qm = MagicMock()
        qm.filter.return_value = qm
        qm.order_by.return_value = qm
        qm.limit.return_value = qm
        qm.all.return_value = [orphan_sl]
        db = MagicMock()
        db.query.return_value = qm

        with patch.object(
            svc, "_find_oco_siblings", return_value=[filled_tp]
        ), patch.object(
            svc, "_cancel_oco_sibling", return_value=True
        ) as cancel:
            n = svc._sweep_orphaned_oco_siblings(
                db, live_open_ids={"73817490101967199"}, limit=10
            )

        assert n == 1
        cancel.assert_called_once()
        assert cancel.call_args.kwargs.get("force_live_cancel") is True

    def test_skips_orphan_not_in_live_open_ids(self):
        svc = ExchangeSyncService()
        orphan_sl = _order(oid="sl-ghost", role="STOP_LOSS", status=OrderStatusEnum.ACTIVE)
        filled_tp = _order(oid="tp-1", role="TAKE_PROFIT", status=OrderStatusEnum.FILLED)

        qm = MagicMock()
        qm.filter.return_value = qm
        qm.order_by.return_value = qm
        qm.limit.return_value = qm
        qm.all.return_value = [orphan_sl]
        db = MagicMock()
        db.query.return_value = qm

        with patch.object(svc, "_find_oco_siblings", return_value=[filled_tp]), patch.object(
            svc, "_cancel_oco_sibling"
        ) as cancel:
            n = svc._sweep_orphaned_oco_siblings(db, live_open_ids={"other"}, limit=10)

        assert n == 0
        cancel.assert_not_called()


class TestCancelOcoAfterProtectionFill:
    def test_falls_back_when_oco_helper_returns_false(self):
        svc = ExchangeSyncService()
        filled = _order(oid="tp-1", role="TAKE_PROFIT", status=OrderStatusEnum.FILLED)
        with patch.object(svc, "_cancel_oco_sibling", return_value=False), patch.object(
            svc, "_cancel_remaining_sl_tp", return_value=1
        ) as fallback:
            assert svc._cancel_oco_after_protection_fill(MagicMock(), filled) is True
        fallback.assert_called_once()


def test_cancel_order_type_for_sibling_helpers():
    svc = ExchangeSyncService()
    assert svc._opposite_protection_role("TAKE_PROFIT") == "STOP_LOSS"
    assert svc._opposite_protection_role("STOP_LOSS") == "TAKE_PROFIT"
    assert svc._is_active_oco_sibling_status(OrderStatusEnum.ACTIVE)
    assert svc._is_active_oco_sibling_status("PENDING")
    assert not svc._is_active_oco_sibling_status(OrderStatusEnum.FILLED)
    assert svc._cancel_result_indicates_already_gone({"error": "Order not found"})
