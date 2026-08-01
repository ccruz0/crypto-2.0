"""Tests for full trading kill switch wiring.

Covers the SAFETY contract that activating TRADING_KILL_SWITCH reliably and
immediately stops ALL real order placement:

1. Kill switch read is fail-closed (DB/read error -> treated as ON).
2. The pre-trade gate (can_place_real_order) used by BOTH the manual order path
   (routes_orders.place_order) and the automatic signal path (signal_monitor)
   blocks when the kill switch is ON or unreadable.
3. Broker-level defense-in-depth: require_mutation_allowed_for_broker blocks
   every order-placement operation when the kill switch is ON / unreadable, so a
   missed orchestration-layer gate still cannot place a real order. Non-placement
   mutations (cancel) are not blocked.
4. Operator API control: GET/POST /api/trading/kill-switch.
"""
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy.orm import Session

from app.utils.trading_guardrails import (
    _get_telegram_kill_switch_status,
    can_place_real_order,
)
from app.services.live_trading_gate import (
    require_mutation_allowed_for_broker,
    LiveTradingBlockedError,
    _trading_kill_switch_blocks,
)


@pytest.fixture
def mock_db():
    return MagicMock(spec=Session)


class TestKillSwitchReadFailClosed:
    """_get_telegram_kill_switch_status must fail-closed on read error."""

    def test_returns_false_when_setting_absent(self, mock_db):
        mock_db.query.return_value.filter.return_value.first.return_value = None
        assert _get_telegram_kill_switch_status(mock_db) is False

    def test_returns_true_when_setting_true(self, mock_db):
        setting = MagicMock()
        setting.setting_value = "true"
        mock_db.query.return_value.filter.return_value.first.return_value = setting
        assert _get_telegram_kill_switch_status(mock_db) is True

    def test_returns_false_when_setting_false(self, mock_db):
        setting = MagicMock()
        setting.setting_value = "false"
        mock_db.query.return_value.filter.return_value.first.return_value = setting
        assert _get_telegram_kill_switch_status(mock_db) is False

    def test_fail_closed_on_read_error(self, mock_db):
        """DB read error -> kill switch considered ON (block)."""
        mock_db.query.side_effect = Exception("db down")
        assert _get_telegram_kill_switch_status(mock_db) is True


class TestPreTradeGate:
    """can_place_real_order gates both manual and automatic signal order paths."""

    @patch("app.utils.trading_guardrails.get_live_trading_status", return_value=True)
    @patch("app.utils.trading_guardrails._get_telegram_kill_switch_status", return_value=True)
    @patch("app.utils.trading_guardrails._get_trade_enabled_for_symbol", return_value=True)
    @patch("app.utils.trading_guardrails.count_total_open_positions", return_value=0)
    def test_gate_blocks_when_kill_switch_on(self, _count, _trade, _ks, _live, mock_db):
        allowed, reason = can_place_real_order(
            db=mock_db, symbol="BTC_USDT", order_usd_value=50.0, side="BUY"
        )
        assert allowed is False
        assert "kill switch" in reason.lower()

    @patch("app.utils.trading_guardrails.get_live_trading_status", return_value=True)
    def test_gate_fail_closed_when_read_errors(self, _live, mock_db):
        """Kill switch read error -> gate blocks (fail-closed)."""
        mock_db.query.side_effect = Exception("db down")
        allowed, reason = can_place_real_order(
            db=mock_db, symbol="BTC_USDT", order_usd_value=50.0, side="BUY"
        )
        assert allowed is False
        assert "kill switch" in reason.lower()

    @patch("app.utils.trading_guardrails.get_live_trading_status", return_value=True)
    @patch("app.utils.trading_guardrails._get_telegram_kill_switch_status", return_value=False)
    @patch("app.utils.trading_guardrails._get_trade_enabled_for_symbol", return_value=True)
    @patch("app.utils.trading_guardrails.count_total_open_positions", return_value=0)
    def test_gate_allows_when_kill_switch_off(self, _count, _trade, _ks, _live, mock_db):
        mock_query = MagicMock()
        mock_query.filter.return_value.order_by.return_value.first.return_value = None
        mock_query.filter.return_value.scalar.return_value = 0
        mock_db.query.return_value = mock_query
        allowed, reason = can_place_real_order(
            db=mock_db, symbol="BTC_USDT", order_usd_value=50.0, side="BUY"
        )
        assert allowed is True
        assert reason is None


class TestBrokerDefenseInDepth:
    """require_mutation_allowed_for_broker is the last-resort broker chokepoint."""

    PLACEMENT_OPS = [
        "place_market_order",
        "place_limit_order",
        "place_stop_loss_order",
        "place_take_profit_order",
        "create_stop_loss_take_profit_with_variations",
    ]

    @patch("app.services.live_trading_gate._trading_kill_switch_blocks", return_value=True)
    def test_all_placement_ops_blocked_when_kill_switch_on(self, _blocks):
        for op in self.PLACEMENT_OPS:
            with pytest.raises(LiveTradingBlockedError):
                require_mutation_allowed_for_broker(op, "BTC_USDT")

    @patch("app.services.live_trading_gate._trading_kill_switch_blocks", return_value=False)
    def test_placement_ops_allowed_when_kill_switch_off(self, _blocks):
        for op in self.PLACEMENT_OPS:
            # Should NOT raise.
            require_mutation_allowed_for_broker(op, "BTC_USDT")

    @patch("app.services.live_trading_gate._trading_kill_switch_blocks", return_value=True)
    def test_cancel_not_blocked_even_when_kill_switch_on(self, mock_blocks):
        # Non-placement mutation: operator can still reduce exposure.
        require_mutation_allowed_for_broker("cancel_order", "BTC_USDT")
        mock_blocks.assert_not_called()


class TestTradingKillSwitchBlocksHelper:
    """_trading_kill_switch_blocks must fail-closed when state is unknown."""

    def test_fail_closed_when_session_factory_missing(self):
        with patch("app.database.SessionLocal", None):
            assert _trading_kill_switch_blocks() is True

    def test_reads_true_and_closes_session(self):
        fake_db = MagicMock()
        with patch("app.database.SessionLocal", MagicMock(return_value=fake_db)):
            with patch(
                "app.utils.trading_guardrails._get_telegram_kill_switch_status",
                return_value=True,
            ):
                assert _trading_kill_switch_blocks() is True
        fake_db.close.assert_called_once()

    def test_reads_false(self):
        fake_db = MagicMock()
        with patch("app.database.SessionLocal", MagicMock(return_value=fake_db)):
            with patch(
                "app.utils.trading_guardrails._get_telegram_kill_switch_status",
                return_value=False,
            ):
                assert _trading_kill_switch_blocks() is False

    def test_fail_closed_on_session_error(self):
        with patch("app.database.SessionLocal", MagicMock(side_effect=Exception("db down"))):
            assert _trading_kill_switch_blocks() is True


class TestKillSwitchApi:
    """Operator control endpoints in routes_control."""

    def test_get_status_on(self):
        from app.api.routes_control import get_kill_switch_status

        db = MagicMock(spec=Session)
        with patch(
            "app.utils.trading_guardrails._get_telegram_kill_switch_status",
            return_value=True,
        ):
            resp = get_kill_switch_status(db=db)
        assert resp["kill_switch_on"] is True
        assert resp["trading_blocked"] is True

    def test_get_status_off(self):
        from app.api.routes_control import get_kill_switch_status

        db = MagicMock(spec=Session)
        with patch(
            "app.utils.trading_guardrails._get_telegram_kill_switch_status",
            return_value=False,
        ):
            resp = get_kill_switch_status(db=db)
        assert resp["kill_switch_on"] is False
        assert resp["trading_blocked"] is False

    def test_set_kill_switch_on(self):
        from app.api.routes_control import set_kill_switch, KillSwitchRequest

        db = MagicMock(spec=Session)
        with patch(
            "app.api.routes_control._set_kill_switch_in_db", return_value=True
        ) as mock_set:
            resp = set_kill_switch(KillSwitchRequest(enabled=True), db=db)
        mock_set.assert_called_once_with(db, True)
        assert resp["ok"] is True
        assert resp["kill_switch_on"] is True

    def test_set_kill_switch_off(self):
        from app.api.routes_control import set_kill_switch, KillSwitchRequest

        db = MagicMock(spec=Session)
        with patch(
            "app.api.routes_control._set_kill_switch_in_db", return_value=True
        ) as mock_set:
            resp = set_kill_switch(KillSwitchRequest(enabled=False), db=db)
        mock_set.assert_called_once_with(db, False)
        assert resp["kill_switch_on"] is False

    def test_set_kill_switch_db_failure(self):
        from app.api.routes_control import set_kill_switch, KillSwitchRequest

        db = MagicMock(spec=Session)
        with patch(
            "app.api.routes_control._set_kill_switch_in_db", return_value=False
        ):
            resp = set_kill_switch(KillSwitchRequest(enabled=True), db=db)
        assert resp["ok"] is False
        assert resp["success"] is False
