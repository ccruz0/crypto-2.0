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

    def test_parse_rejects_other_order_id(self):
        assert (
            parse_resolved_order_payload(
                {"order_id": "other", "status": "FILLED"},
                "5755608491541413116",
            )
            is None
        )


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
