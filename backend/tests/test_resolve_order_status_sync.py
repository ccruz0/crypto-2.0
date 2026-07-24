"""Tests for TP/SL fill status resolution and fill Telegram notifications."""

from __future__ import annotations

import sys
import types
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

# Stub heavy service deps before importing exchange_sync (keeps unit tests light).
def _ensure_stub(name: str, **attrs):
    if name in sys.modules and not isinstance(sys.modules[name], MagicMock):
        mod = sys.modules[name]
        for k, v in attrs.items():
            setattr(mod, k, v)
        return mod
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


_ensure_stub("app.services.telegram_notifier", telegram_notifier=MagicMock())
_ensure_stub("app.services.fill_dedup_postgres", get_fill_dedup=MagicMock())
_ensure_stub("app.services.throttle_service", build_strategy_key=lambda *a, **k: "default:default")
_ensure_stub(
    "app.utils.pipeline_logging",
    make_json_safe=lambda x: x,
    log_critical_failure=MagicMock(),
)
_ensure_stub(
    "app.services.sl_tp_protection",
    GHOST_CANCEL_GRACE_SECONDS=3600,
    get_active_protection_order=MagicMock(),
    has_complete_sl_tp_protection=MagicMock(return_value=False),
    release_sl_tp_creation_lock=MagicMock(),
    should_mark_unresolved_order_cancelled=MagicMock(return_value=(False, "skip")),
    try_acquire_sl_tp_creation_lock=MagicMock(return_value=True),
)
_ensure_stub("app.services.open_orders", merge_orders=MagicMock(), UnifiedOpenOrder=object)
_ensure_stub(
    "app.services.open_orders_cache",
    store_unified_open_orders=MagicMock(),
    update_open_orders_cache=MagicMock(),
)
_broker = _ensure_stub("app.services.brokers")
_broker_mod = _ensure_stub(
    "app.services.brokers.crypto_com_trade",
    CryptoComTradeClient=MagicMock,
    trade_client=MagicMock(),
)

import pytest

from app.services.exchange_sync import (
    ExchangeSyncService,
    expand_symbols_with_quote_variants,
    normalize_resolved_exchange_status,
    parse_resolved_order_payload,
    quote_instrument_variants,
    should_notify_executed_fill,
    RECENT_FILL_WINDOW_SECONDS,
)


class TestQuoteInstrumentVariants:
    def test_usd_adds_usdt_twin(self):
        assert quote_instrument_variants("BTC_USD") == ["BTC_USD", "BTC_USDT"]

    def test_usdt_adds_usd_twin(self):
        assert quote_instrument_variants("eth_usdt") == ["ETH_USDT", "ETH_USD"]

    def test_expand_preserves_order_and_dedupes(self):
        assert expand_symbols_with_quote_variants(["BTC_USD", "BTC_USDT", "ETH_USDT"]) == [
            "BTC_USD",
            "BTC_USDT",
            "ETH_USDT",
            "ETH_USD",
        ]


class TestNormalizeAndParse:
    def test_executed_alias_becomes_filled(self):
        assert normalize_resolved_exchange_status("EXECUTED") == "FILLED"
        assert normalize_resolved_exchange_status("canceled") == "CANCELLED"

    def test_parse_detail_payload(self):
        parsed = parse_resolved_order_payload(
            {
                "order_id": "5755608491541413116",
                "status": "FILLED",
                "cumulative_quantity": "0.00016",
                "avg_price": "65199.57",
                "quantity": "0.00016",
            },
            "5755608491541413116",
        )
        assert parsed is not None
        assert parsed["status"] == "FILLED"
        assert parsed["cumulative_quantity"] == pytest.approx(0.00016)
        assert parsed["price"] == pytest.approx(65199.57)

    def test_parse_cancelled_with_fill_qty_becomes_filled(self):
        parsed = parse_resolved_order_payload(
            {
                "order_id": "73817490102011214",
                "status": "CANCELLED",
                "cumulative_quantity": "0.30000",
                "avg_price": "65960.21",
                "quantity": "0.30000",
                "contingency_type": "TAKE_PROFIT",
                "exchange_order_id": "5755600492041405464",
            },
            "73817490102011214",
        )
        assert parsed is not None
        assert parsed["status"] == "FILLED"
        assert parsed["contingency_type"] == "TAKE_PROFIT"
        assert parsed["child_exchange_order_id"] == "5755600492041405464"

    def test_parse_rejects_other_order_id(self):
        assert (
            parse_resolved_order_payload(
                {"order_id": "other", "status": "FILLED"},
                "5755608491541413116",
            )
            is None
        )


class TestProtectionRoleFromOrderData:
    def test_contingency_take_profit(self):
        from app.services.exchange_sync import protection_role_from_order_data

        assert (
            protection_role_from_order_data(
                {"order_type": "LIMIT", "contingency_type": "TAKE_PROFIT"}
            )
            == "TAKE_PROFIT"
        )

    def test_order_type_stop_limit(self):
        from app.services.exchange_sync import protection_role_from_order_data

        assert protection_role_from_order_data({"order_type": "STOP_LIMIT"}) == "STOP_LOSS"


class TestResolveOrderStatusFromExchange:
    def test_prefers_get_order_detail(self):
        svc = ExchangeSyncService()
        detail = {
            "code": 0,
            "result": {
                "order_id": "tp-1",
                "status": "FILLED",
                "cumulative_quantity": "0.00016",
                "avg_price": "65199.57",
                "quantity": "0.00016",
            },
        }
        with patch(
            "app.services.exchange_sync.trade_client.get_order_detail",
            return_value=detail,
        ) as mock_detail, patch(
            "app.services.exchange_sync.trade_client.get_order_history"
        ) as mock_hist:
            result = svc._resolve_order_status_from_exchange(
                "tp-1",
                datetime(2026, 7, 8, tzinfo=timezone.utc),
                instrument_name="BTC_USD",
            )
            assert result is not None
            assert result["status"] == "FILLED"
            mock_detail.assert_called_once_with("tp-1")
            mock_hist.assert_not_called()

    def test_falls_back_to_advanced_detail_when_spot_empty(self):
        svc = ExchangeSyncService()
        adv_detail = {
            "code": 0,
            "result": {
                "order_id": "73817490102011214",
                "status": "FILLED",
                "cumulative_quantity": "0.30000",
                "avg_price": "65960.21",
                "quantity": "0.30000",
                "contingency_type": "TAKE_PROFIT",
            },
        }
        with patch(
            "app.services.exchange_sync.trade_client.get_order_detail",
            return_value={"code": 0},
        ), patch(
            "app.services.exchange_sync.trade_client.get_advanced_order_detail",
            return_value=adv_detail,
        ) as mock_adv, patch(
            "app.services.exchange_sync.trade_client.get_order_history"
        ) as mock_hist:
            result = svc._resolve_order_status_from_exchange(
                "73817490102011214",
                datetime(2026, 7, 19, 10, 24, tzinfo=timezone.utc),
                instrument_name="BTC_USD",
            )
            assert result is not None
            assert result["status"] == "FILLED"
            assert result["cumulative_quantity"] == pytest.approx(0.3)
            mock_adv.assert_called_once_with("73817490102011214")
            mock_hist.assert_not_called()

    def test_falls_back_to_instrument_history_when_detail_empty(self):
        svc = ExchangeSyncService()
        history = {
            "data": [
                {
                    "order_id": "tp-2",
                    "status": "FILLED",
                    "cumulative_quantity": "0.00016",
                    "price": "65199.57",
                    "quantity": "0.00016",
                }
            ]
        }

        def history_side_effect(**kwargs):
            if kwargs.get("instrument_name") == "BTC_USD":
                return history
            return {"data": []}

        with patch(
            "app.services.exchange_sync.trade_client.get_order_detail",
            return_value=None,
        ), patch(
            "app.services.exchange_sync.trade_client.get_advanced_order_detail",
            return_value=None,
        ), patch(
            "app.services.exchange_sync.trade_client.get_order_history",
            side_effect=history_side_effect,
        ) as mock_hist, patch.object(
            svc, "_resolve_advanced_order_status_from_exchange", return_value=None
        ):
            result = svc._resolve_order_status_from_exchange(
                "tp-2",
                datetime(2026, 7, 8, tzinfo=timezone.utc),
                instrument_name="BTC_USD",
            )
            assert result is not None
            assert result["status"] == "FILLED"
            assert any(
                call.kwargs.get("instrument_name") == "BTC_USD"
                for call in mock_hist.call_args_list
            )

    def test_unscoped_history_alone_is_not_required_when_instrument_hits(self):
        svc = ExchangeSyncService()
        calls = []

        def history_side_effect(**kwargs):
            calls.append(kwargs.get("instrument_name"))
            if kwargs.get("instrument_name") == "BTC_USD":
                return {
                    "data": [
                        {
                            "order_id": "tp-3",
                            "status": "EXECUTED",
                            "cumulative_quantity": 0.00016,
                            "avg_price": 65199.57,
                            "quantity": 0.00016,
                        }
                    ]
                }
            return {"data": []}

        with patch(
            "app.services.exchange_sync.trade_client.get_order_detail",
            return_value=None,
        ), patch(
            "app.services.exchange_sync.trade_client.get_advanced_order_detail",
            return_value=None,
        ), patch(
            "app.services.exchange_sync.trade_client.get_order_history",
            side_effect=history_side_effect,
        ), patch.object(
            svc, "_resolve_advanced_order_status_from_exchange", return_value=None
        ):
            result = svc._resolve_order_status_from_exchange(
                "tp-3",
                instrument_name="BTC_USD",
            )
            assert result["status"] == "FILLED"
            assert "BTC_USD" in calls

    def test_advanced_resolve_uses_narrow_windows_not_create_to_now(self):
        svc = ExchangeSyncService()
        create_at = datetime(2026, 7, 19, 10, 24, tzinfo=timezone.utc)
        calls = []

        def adv_hist(**kwargs):
            calls.append((kwargs.get("start_time"), kwargs.get("end_time")))
            start = kwargs.get("start_time") or 0
            end = kwargs.get("end_time") or 0
            # Only the first ~24h window around create contains the fill.
            create_ms = int(create_at.timestamp() * 1000)
            if start <= create_ms <= end:
                return {
                    "data": [
                        {
                            "order_id": "73817490102011214",
                            "status": "FILLED",
                            "cumulative_quantity": "0.30000",
                            "avg_price": "65960.21",
                            "quantity": "0.30000",
                            "contingency_type": "TAKE_PROFIT",
                        }
                    ]
                }
            return {"data": []}

        with patch(
            "app.services.exchange_sync.trade_client.get_advanced_order_detail",
            return_value=None,
        ), patch(
            "app.services.exchange_sync.trade_client.get_advanced_order_history",
            side_effect=adv_hist,
        ), patch(
            "app.database.SessionLocal",
            side_effect=Exception("no db"),
        ):
            result = svc._resolve_advanced_order_status_from_exchange(
                "73817490102011214",
                create_at,
            )
            assert result is not None
            assert result["status"] == "FILLED"
            assert calls, "expected narrow window history calls"
            # Every window must be <= 24h (+1s tolerance)
            for start, end in calls:
                assert (end - start) <= 24 * 60 * 60 * 1000 + 1000
            # Must not use a single create→now mega-window
            assert not any((end - start) > 48 * 60 * 60 * 1000 for start, end in calls)


class TestReconcileMisclassifiedProtectionFills:
    def test_upgrades_cancelled_zero_qty_tp_to_filled(self):
        from app.models.exchange_order import OrderStatusEnum

        svc = ExchangeSyncService()
        order = MagicMock()
        order.exchange_order_id = "73817490102011217"
        order.symbol = "BTC_USD"
        order.status = OrderStatusEnum.CANCELLED
        order.cumulative_quantity = 0
        order.avg_price = None
        order.price = 65199.57
        order.side = MagicMock(value="SELL")
        order.order_role = "TAKE_PROFIT"
        order.order_type = "TAKE_PROFIT_LIMIT"
        order.exchange_create_time = datetime(2026, 7, 19, tzinfo=timezone.utc)
        order.created_at = order.exchange_create_time
        order.execution_notified_at = None
        order.parent_order_id = "5755600491541413116"
        order.trade_signal_id = None

        db = MagicMock()
        query = MagicMock()
        db.query.return_value = query
        query.filter.return_value = query
        query.order_by.return_value = query
        query.limit.return_value = query
        query.all.return_value = [order]
        # Watchlist lookup inside _apply_protection_fill_from_resolve
        query.first.return_value = None

        _ensure_stub(
            "app.services.signal_monitor",
            _emit_lifecycle_event=MagicMock(),
        )
        _ensure_stub(
            "app.services.strategy_profiles",
            resolve_strategy_profile=lambda *a, **k: ("default", "default"),
        )
        _ensure_stub("app.models.watchlist", WatchlistItem=MagicMock())

        with patch.object(
            svc,
            "_resolve_advanced_order_status_from_exchange",
            return_value={
                "status": "FILLED",
                "cumulative_quantity": 0.00016,
                "price": 65239.32,
                "quantity": 0.00016,
                "child_exchange_order_id": "5755600492017002493",
            },
        ), patch.object(
            svc, "_maybe_notify_executed_fill_telegram"
        ) as mock_tg, patch.object(
            svc, "_cancel_oco_sibling"
        ), patch.object(
            svc, "_upsert_protection_child_spot_fill"
        ) as mock_child:
            repaired = svc._reconcile_misclassified_protection_fills(db, limit=5)

        assert repaired == 1
        assert order.status == OrderStatusEnum.FILLED
        assert order.cumulative_quantity == pytest.approx(0.00016)
        assert order.avg_price == pytest.approx(65239.32)
        mock_tg.assert_called_once()
        mock_child.assert_called_once()

    def test_skips_confirmed_cancelled_on_subsequent_passes(self):
        from app.models.exchange_order import OrderStatusEnum

        svc = ExchangeSyncService()
        order = MagicMock()
        order.exchange_order_id = "73817490102025222"
        order.symbol = "DGB_USD"
        order.status = OrderStatusEnum.CANCELLED
        order.cumulative_quantity = 0
        order.order_role = "STOP_LOSS"
        order.order_type = "STOP_LIMIT"
        order.exchange_create_time = datetime(2026, 7, 23, tzinfo=timezone.utc)
        order.created_at = order.exchange_create_time

        db = MagicMock()
        query = MagicMock()
        db.query.return_value = query
        query.filter.return_value = query
        query.order_by.return_value = query
        query.limit.return_value = query
        query.all.return_value = [order]

        with patch.object(
            svc,
            "_resolve_advanced_order_status_from_exchange",
            return_value={
                "status": "CANCELLED",
                "cumulative_quantity": 0.0,
                "price": None,
                "quantity": 0.0,
            },
        ) as mock_adv, patch.object(
            svc, "_apply_protection_fill_from_resolve"
        ) as mock_apply:
            assert svc._reconcile_misclassified_protection_fills(db, limit=5) == 0
            assert mock_adv.call_count == 1
            mock_apply.assert_not_called()
            # Second pass must not re-hit advanced API
            assert svc._reconcile_misclassified_protection_fills(db, limit=5) == 0
            assert mock_adv.call_count == 1


class TestUpsertProtectionChildSpotFill:
    def test_inserts_missing_child_and_suppresses_telegram(self):
        from app.models.exchange_order import OrderSideEnum, OrderStatusEnum

        svc = ExchangeSyncService()
        parent = MagicMock()
        parent.exchange_order_id = "73817490102011214"
        parent.symbol = "BTC_USD"
        parent.side = OrderSideEnum.SELL
        parent.order_type = "TAKE_PROFIT_LIMIT"
        parent.order_role = "TAKE_PROFIT"
        parent.parent_order_id = "entry-1"
        parent.quantity = 0.3
        parent.price = 65945.0
        parent.avg_price = 65960.21
        parent.cumulative_quantity = 0.3
        parent.execution_notified_at = datetime(2026, 7, 23, 11, 6, tzinfo=timezone.utc)
        parent.exchange_create_time = datetime(2026, 7, 19, tzinfo=timezone.utc)
        parent.created_at = parent.exchange_create_time

        db = MagicMock()
        query = MagicMock()
        db.query.return_value = query
        query.filter.return_value = query
        query.first.return_value = None  # child missing

        child_id = svc._upsert_protection_child_spot_fill(
            db,
            parent,
            {
                "status": "FILLED",
                "cumulative_quantity": 0.3,
                "price": 65960.21,
                "child_exchange_order_id": "5755600492041405464",
            },
        )
        assert child_id == "5755600492041405464"
        db.add.assert_called_once()
        created = db.add.call_args[0][0]
        assert created.exchange_order_id == "5755600492041405464"
        assert created.status == OrderStatusEnum.FILLED
        assert created.order_role == "TAKE_PROFIT"
        assert created.execution_notified_at is not None


class TestResolvePrefersAdvancedForProtection:
    def test_protection_row_tries_advanced_before_spot(self):
        from app.models.exchange_order import OrderStatusEnum

        svc = ExchangeSyncService()
        row = MagicMock()
        row.symbol = "BTC_USD"
        row.order_role = "TAKE_PROFIT"
        row.order_type = "TAKE_PROFIT_LIMIT"

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = row

        adv_detail = {
            "code": 0,
            "result": {
                "order_id": "73817490102011214",
                "status": "FILLED",
                "cumulative_quantity": "0.30000",
                "avg_price": "65960.21",
                "quantity": "0.30000",
                "exchange_order_id": "5755600492041405464",
            },
        }
        with patch(
            "app.services.exchange_sync.SessionLocal", return_value=db
        ), patch(
            "app.services.exchange_sync.trade_client.get_advanced_order_detail",
            return_value=adv_detail,
        ) as mock_adv, patch(
            "app.services.exchange_sync.trade_client.get_order_detail",
        ) as mock_spot:
            result = svc._resolve_order_status_from_exchange(
                "73817490102011214",
                datetime(2026, 7, 19, tzinfo=timezone.utc),
                instrument_name="BTC_USD",
            )
            assert result is not None
            assert result["status"] == "FILLED"
            assert result["child_exchange_order_id"] == "5755600492041405464"
            mock_adv.assert_called_once()
            mock_spot.assert_not_called()


class TestMaybeNotifyExecutedFillTelegram:
    def _tp_order(self):
        order = MagicMock()
        order.exchange_order_id = "tp-fill-1"
        order.symbol = "BTC_USD"
        order.side = MagicMock(value="SELL")
        order.order_role = "TAKE_PROFIT"
        order.order_type = "TAKE_PROFIT_LIMIT"
        order.trade_signal_id = None
        order.parent_order_id = "entry-1"
        order.avg_price = 65199.57
        order.price = 65199.57
        order.quantity = 0.00016
        order.cumulative_quantity = 0.00016
        order.execution_notified_at = None
        order.exchange_update_time = datetime(2026, 7, 8, tzinfo=timezone.utc)
        order.exchange_create_time = datetime(2026, 7, 1, tzinfo=timezone.utc)
        return order

    def test_sends_telegram_for_tp_fill(self):
        svc = ExchangeSyncService()
        order = self._tp_order()
        db = MagicMock()
        fill_dedup = MagicMock()
        fill_dedup.should_notify_fill.return_value = (True, "new fill")
        notifier = MagicMock()
        notifier.send_executed_order.return_value = True

        with patch(
            "app.services.exchange_sync.should_notify_executed_fill",
            return_value=(True, "system order"),
        ), patch(
            "app.services.exchange_sync.get_fill_dedup",
            return_value=fill_dedup,
        ), patch(
            "app.services.exchange_sync._count_open_entry_buy_orders",
            return_value=1,
        ), patch(
            "app.services.exchange_sync.link_system_trade_signal_to_order",
            return_value=False,
        ), patch(
            "app.services.telegram_notifier.telegram_notifier",
            notifier,
        ), patch.object(
            svc, "_lookup_entry_price_for_protection", return_value=62343.84
        ):
            ok = svc._maybe_notify_executed_fill_telegram(
                db,
                order,
                source="sync_open_orders_resolve",
                price=65199.57,
                quantity=0.00016,
                status_str="FILLED",
            )
        assert ok is True
        notifier.send_executed_order.assert_called_once()
        kwargs = notifier.send_executed_order.call_args.kwargs
        assert kwargs["order_role"] == "TAKE_PROFIT"
        assert kwargs["symbol"] == "BTC_USD"
        assert order.execution_notified_at is not None

    def test_skips_when_gate_blocks(self):
        svc = ExchangeSyncService()
        order = self._tp_order()
        fill_dedup = MagicMock()
        notifier = MagicMock()
        with patch(
            "app.services.exchange_sync.should_notify_executed_fill",
            return_value=(False, "already notified"),
        ), patch(
            "app.services.exchange_sync.get_fill_dedup",
            return_value=fill_dedup,
        ), patch(
            "app.services.telegram_notifier.telegram_notifier",
            notifier,
        ):
            ok = svc._maybe_notify_executed_fill_telegram(
                MagicMock(),
                order,
                source="sync_open_orders_resolve",
            )
        assert ok is False
        notifier.send_executed_order.assert_not_called()


class TestProtectionFillGate:
    def test_tp_role_allowed_even_if_old(self):
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        filled_at = now - timedelta(days=5)
        order = MagicMock()
        order.execution_notified_at = None
        order.trade_signal_id = None
        order.parent_order_id = None
        order.order_role = "TAKE_PROFIT"
        order.order_type = "TAKE_PROFIT_LIMIT"
        order.exchange_update_time = filled_at
        order.exchange_create_time = filled_at
        allowed, reason = should_notify_executed_fill(
            db=MagicMock(),
            order=order,
            now_utc=now,
            source="sync_open_orders_resolve",
            requested_by_admin=False,
        )
        assert allowed is True
        assert "system" in reason.lower()

    def test_old_manual_entry_blocked(self):
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        filled_at = now - timedelta(seconds=RECENT_FILL_WINDOW_SECONDS + 60)
        order = MagicMock()
        order.execution_notified_at = None
        order.trade_signal_id = None
        order.parent_order_id = None
        order.order_role = None
        order.order_type = "LIMIT"
        order.exchange_update_time = filled_at
        order.exchange_create_time = filled_at
        allowed, reason = should_notify_executed_fill(
            db=MagicMock(),
            order=order,
            now_utc=now,
            source="sync_order_history",
            requested_by_admin=False,
        )
        assert allowed is False
        assert "historical" in reason.lower() or "outside" in reason.lower()
