"""Auto/orchestrator path must protect margin short *adds* (DOGE_USD 2026-08-08).

Regression: ``_place_order_from_signal_impl`` used pre-place ``is_margin_short_entry``
(True only when ``not position_exists``) for post-fill ``needs_protection``. Adding to an
existing DOGE short (order 5755600492782582799) skipped SL/TP; healing OFF left it naked.
"""
import asyncio
from unittest.mock import MagicMock, Mock, patch

from app.services.signal_monitor import SignalMonitorService


def _watchlist(symbol="DOGE_USD", margin=True):
    w = Mock()
    w.symbol = symbol
    w.trade_enabled = True
    w.trade_amount_usd = 100.0
    w.trade_on_margin = margin
    return w


def _db():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []
    db.query.return_value.filter.return_value.count.return_value = 0
    return db


class TestPlaceOrderFromSignalShortAddProtection:
    def test_existing_short_lot_still_gets_protection(self):
        svc = SignalMonitorService()
        db = _db()
        w = _watchlist()

        with patch("app.services.signal_monitor.trade_client") as mock_tc, \
             patch("app.utils.live_trading.get_live_trading_status", return_value=True), \
             patch("app.services.live_trading_gate.assert_exchange_mutation_allowed"), \
             patch(
                 "app.services.order_position_service.count_open_positions_for_symbol",
                 return_value=1,
             ), \
             patch("app.services.risk_guard.shorting_enabled", return_value=True), \
             patch(
                 "app.services.margin_info_service.instrument_allows_margin_short",
                 return_value=True,
             ), \
             patch(
                 "app.services.margin_decision_helper.decide_trading_mode",
             ) as mock_mode, \
             patch.object(
                 svc,
                 "_create_protection_after_entry_fill",
                 return_value={"status": "ok"},
             ) as mock_protect, \
             patch.object(
                 svc,
                 "_is_short_entry_needing_protection",
                 return_value=True,
             ):
            mock_mode.return_value = Mock(use_margin=True, leverage=None)
            mock_tc.place_market_order.return_value = {
                "order_id": "5755600492782582799",
                "status": "FILLED",
                "avg_price": "0.070881",
                "cumulative_quantity": "1412",
            }

            result = asyncio.run(
                svc._place_order_from_signal_impl(
                    db=db,
                    symbol="DOGE_USD",
                    side="SELL",
                    watchlist_item=w,
                    current_price=0.0708,
                    source="orchestrator",
                )
            )

        assert result.get("order_id") == "5755600492782582799"
        mock_protect.assert_called_once()
        assert mock_protect.call_args.kwargs["entry_side"] == "SELL"
        assert mock_protect.call_args.kwargs["order_id"] == "5755600492782582799"

    def test_existing_bot_long_still_protects_as_independent_short(self):
        """SELL alerts open a short even if a bot long exists; SL/TP still attach."""
        svc = SignalMonitorService()
        db = _db()
        w = _watchlist()

        with patch("app.services.signal_monitor.trade_client") as mock_tc, \
             patch("app.utils.live_trading.get_live_trading_status", return_value=True), \
             patch("app.services.live_trading_gate.assert_exchange_mutation_allowed"), \
             patch(
                 "app.services.order_position_service.count_open_positions_for_symbol",
                 return_value=1,
             ), \
             patch("app.services.risk_guard.shorting_enabled", return_value=True), \
             patch(
                 "app.services.margin_info_service.instrument_allows_margin_short",
                 return_value=True,
             ), \
             patch(
                 "app.services.margin_decision_helper.decide_trading_mode",
             ) as mock_mode, \
             patch.object(
                 svc,
                 "_create_protection_after_entry_fill",
                 return_value={"status": "ok"},
             ) as mock_protect, \
             patch.object(
                 svc,
                 "_is_short_entry_needing_protection",
                 return_value=False,
             ):
            mock_mode.return_value = Mock(use_margin=True, leverage=None)
            mock_tc.place_market_order.return_value = {
                "order_id": "independent-short-1",
                "status": "FILLED",
                "avg_price": "0.07",
                "cumulative_quantity": "100",
            }

            result = asyncio.run(
                svc._place_order_from_signal_impl(
                    db=db,
                    symbol="DOGE_USD",
                    side="SELL",
                    watchlist_item=w,
                    current_price=0.07,
                    source="orchestrator",
                )
            )

        assert result.get("order_id") == "independent-short-1"
        mock_protect.assert_called_once()
        assert mock_protect.call_args.kwargs["entry_side"] == "SELL"

    def test_helper_wallet_negative_is_short(self):
        svc = SignalMonitorService()
        with patch("app.services.signal_monitor.trade_client") as mock_tc, \
             patch(
                 "app.services.exchange_sync._base_wallet_balance_from_accounts",
                 return_value=-1412.0,
             ):
            mock_tc.get_account_summary.return_value = {"accounts": []}
            assert svc._is_short_entry_needing_protection(
                db=_db(),
                symbol="DOGE_USD",
                order_id="x",
                user_wants_margin=True,
                use_margin=True,
            ) is True

    def test_helper_wallet_flat_is_long_close(self):
        svc = SignalMonitorService()
        with patch("app.services.signal_monitor.trade_client") as mock_tc, \
             patch(
                 "app.services.exchange_sync._base_wallet_balance_from_accounts",
                 return_value=0.0,
             ):
            mock_tc.get_account_summary.return_value = {"accounts": []}
            assert svc._is_short_entry_needing_protection(
                db=_db(),
                symbol="DOGE_USD",
                order_id="x",
                user_wants_margin=True,
                use_margin=True,
            ) is False

    def test_helper_wallet_down_margin_shorting_protects_add(self):
        svc = SignalMonitorService()
        short_lot = Mock()
        with patch("app.services.signal_monitor.trade_client") as mock_tc, \
             patch(
                 "app.services.exchange_sync._base_wallet_balance_from_accounts",
                 return_value=None,
             ), \
             patch("app.services.risk_guard.shorting_enabled", return_value=True), \
             patch(
                 "app.services.expected_take_profit.rebuild_open_lots",
                 return_value=[short_lot],
             ), \
             patch(
                 "app.services.expected_take_profit._entry_side_for_lot",
                 return_value=__import__(
                     "app.models.exchange_order", fromlist=["OrderSideEnum"]
                 ).OrderSideEnum.SELL,
             ):
            mock_tc.get_account_summary.return_value = {"accounts": []}
            assert svc._is_short_entry_needing_protection(
                db=_db(),
                symbol="DOGE_USD",
                order_id="5755600492782582799",
                user_wants_margin=True,
                use_margin=True,
            ) is True

    def test_helper_wallet_down_long_only_is_long_close(self):
        svc = SignalMonitorService()
        long_lot = Mock()
        with patch("app.services.signal_monitor.trade_client") as mock_tc, \
             patch(
                 "app.services.exchange_sync._base_wallet_balance_from_accounts",
                 return_value=None,
             ), \
             patch("app.services.risk_guard.shorting_enabled", return_value=True), \
             patch(
                 "app.services.expected_take_profit.rebuild_open_lots",
                 return_value=[long_lot],
             ), \
             patch(
                 "app.services.expected_take_profit._entry_side_for_lot",
                 return_value=__import__(
                     "app.models.exchange_order", fromlist=["OrderSideEnum"]
                 ).OrderSideEnum.BUY,
             ):
            mock_tc.get_account_summary.return_value = {"accounts": []}
            assert svc._is_short_entry_needing_protection(
                db=_db(),
                symbol="DOGE_USD",
                order_id="long-close",
                user_wants_margin=True,
                use_margin=True,
            ) is False

    def test_first_short_still_protects_when_wallet_still_flat(self):
        """Bugbot: pre-fill wallet may read >=0; is_margin_short_entry must still gate protect."""
        svc = SignalMonitorService()
        db = _db()
        w = _watchlist()

        with patch("app.services.signal_monitor.trade_client") as mock_tc, \
             patch("app.utils.live_trading.get_live_trading_status", return_value=True), \
             patch("app.services.live_trading_gate.assert_exchange_mutation_allowed"), \
             patch(
                 "app.services.order_position_service.count_open_positions_for_symbol",
                 return_value=0,
             ), \
             patch("app.services.risk_guard.shorting_enabled", return_value=True), \
             patch(
                 "app.services.margin_info_service.instrument_allows_margin_short",
                 return_value=True,
             ), \
             patch(
                 "app.services.margin_decision_helper.decide_trading_mode",
             ) as mock_mode, \
             patch.object(
                 svc,
                 "_create_protection_after_entry_fill",
                 return_value={"status": "ok"},
             ) as mock_protect, \
             patch.object(
                 svc,
                 "_is_short_entry_needing_protection",
                 return_value=False,
             ):
            mock_mode.return_value = Mock(use_margin=True, leverage=None)
            mock_tc.place_market_order.return_value = {
                "order_id": "first-short-1",
                "status": "FILLED",
                "avg_price": "0.07",
                "cumulative_quantity": "100",
            }

            result = asyncio.run(
                svc._place_order_from_signal_impl(
                    db=db,
                    symbol="DOGE_USD",
                    side="SELL",
                    watchlist_item=w,
                    current_price=0.07,
                    source="orchestrator",
                )
            )

        assert result.get("order_id") == "first-short-1"
        mock_protect.assert_called_once()
        assert mock_protect.call_args.kwargs["entry_side"] == "SELL"
