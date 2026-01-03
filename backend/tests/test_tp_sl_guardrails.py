"""
Tests for SL/TP order creation guardrails.
Ensures that guardrails (Live toggle, Telegram kill switch) are enforced
for SL/TP order creation paths.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from sqlalchemy.orm import Session

from app.services.tp_sl_order_creator import create_take_profit_order, create_stop_loss_order
from app.services.brokers.crypto_com_trade import trade_client


@pytest.fixture
def mock_db():
    """Mock database session"""
    return MagicMock(spec=Session)


class TestTPOrderGuardrails:
    """Test guardrails for Take Profit order creation"""
    
    @patch('app.services.tp_sl_order_creator.telegram_notifier')
    @patch('app.services.signal_monitor._emit_lifecycle_event')
    @patch('app.services.tp_sl_order_creator.can_place_real_order')
    @patch.object(trade_client, 'place_take_profit_order')
    def test_tp_blocked_when_live_off(self, mock_place_order, mock_can_place, mock_emit_event, mock_telegram, mock_db):
        """Test that TP order is blocked when Live toggle is OFF"""
        # Setup: guardrails block the order
        mock_can_place.return_value = (False, "blocked: Live toggle is OFF")
        
        # Call create_take_profit_order
        result = create_take_profit_order(
            db=mock_db,
            symbol="BTC_USDT",
            side="BUY",
            tp_price=50000.0,
            quantity=0.001,
            entry_price=49000.0,
            dry_run=False,
        )
        
        # Assert: order should be blocked
        assert result["order_id"] is None
        assert "error" in result
        assert "blocked" in result["error"].lower()
        
        # Assert: exchange client should NOT be called
        mock_place_order.assert_not_called()
        
        # Assert: lifecycle event should be emitted
        mock_emit_event.assert_called_once()
        call_args = mock_emit_event.call_args
        assert call_args[1]["event_type"] == "SLTP_BLOCKED"
        assert "TP blocked" in call_args[1]["event_reason"]
        
        # Assert: Telegram message should be sent
        mock_telegram.send_message.assert_called_once()
        telegram_msg = mock_telegram.send_message.call_args[0][0]
        assert "SL/TP BLOCKED" in telegram_msg
        assert "TAKE PROFIT" in telegram_msg
    
    @patch('app.services.tp_sl_order_creator.telegram_notifier')
    @patch('app.services.signal_monitor._emit_lifecycle_event')
    @patch('app.services.tp_sl_order_creator.can_place_real_order')
    @patch.object(trade_client, 'place_take_profit_order')
    def test_tp_blocked_when_kill_switch_on(self, mock_place_order, mock_can_place, mock_emit_event, mock_telegram, mock_db):
        """Test that TP order is blocked when Telegram kill switch is ON"""
        # Setup: guardrails block the order
        mock_can_place.return_value = (False, "blocked: Telegram kill switch is ON")
        
        # Call create_take_profit_order
        result = create_take_profit_order(
            db=mock_db,
            symbol="ETH_USDT",
            side="BUY",
            tp_price=3000.0,
            quantity=0.01,
            entry_price=2900.0,
            dry_run=False,
        )
        
        # Assert: order should be blocked
        assert result["order_id"] is None
        assert "error" in result
        assert "blocked" in result["error"].lower()
        
        # Assert: exchange client should NOT be called
        mock_place_order.assert_not_called()
        
        # Assert: lifecycle event should be emitted
        mock_emit_event.assert_called_once()
        call_args = mock_emit_event.call_args
        assert call_args[1]["event_type"] == "SLTP_BLOCKED"
        assert "kill switch" in call_args[1]["event_reason"].lower()
    
    @patch('app.services.tp_sl_order_creator.telegram_notifier')
    @patch('app.services.signal_monitor._emit_lifecycle_event')
    @patch('app.services.tp_sl_order_creator.can_place_real_order')
    @patch.object(trade_client, 'place_take_profit_order')
    def test_tp_allowed_when_guardrails_pass(self, mock_place_order, mock_can_place, mock_emit_event, mock_telegram, mock_db):
        """Test that TP order is placed when guardrails pass"""
        # Setup: guardrails allow the order
        mock_can_place.return_value = (True, None)
        mock_place_order.return_value = {"order_id": "tp_12345"}
        
        # Call create_take_profit_order
        result = create_take_profit_order(
            db=mock_db,
            symbol="BTC_USDT",
            side="BUY",
            tp_price=50000.0,
            quantity=0.001,
            entry_price=49000.0,
            dry_run=False,
        )
        
        # Assert: order should be created
        assert result["order_id"] == "tp_12345"
        assert result.get("error") is None
        
        # Assert: exchange client should be called
        mock_place_order.assert_called_once()
        
        # Assert: lifecycle event should NOT be emitted (order not blocked)
        mock_emit_event.assert_not_called()
    
    @patch('app.services.tp_sl_order_creator.can_place_real_order')
    @patch.object(trade_client, 'place_take_profit_order')
    def test_tp_bypasses_guardrails_in_dry_run(self, mock_place_order, mock_can_place, mock_db):
        """Test that guardrails are bypassed in dry_run mode"""
        # Setup
        mock_place_order.return_value = {"order_id": "tp_dry_12345"}
        
        # Call create_take_profit_order with dry_run=True
        result = create_take_profit_order(
            db=mock_db,
            symbol="BTC_USDT",
            side="BUY",
            tp_price=50000.0,
            quantity=0.001,
            entry_price=49000.0,
            dry_run=True,  # Dry run mode
        )
        
        # Assert: guardrails should NOT be checked
        mock_can_place.assert_not_called()
        
        # Assert: order should be created (dry run)
        assert result["order_id"] == "tp_dry_12345"


class TestSLOrderGuardrails:
    """Test guardrails for Stop Loss order creation"""
    
    @patch('app.services.tp_sl_order_creator.telegram_notifier')
    @patch('app.services.signal_monitor._emit_lifecycle_event')
    @patch('app.services.tp_sl_order_creator.can_place_real_order')
    @patch.object(trade_client, 'place_stop_loss_order')
    def test_sl_blocked_when_live_off(self, mock_place_order, mock_can_place, mock_emit_event, mock_telegram, mock_db):
        """Test that SL order is blocked when Live toggle is OFF"""
        # Setup: guardrails block the order
        mock_can_place.return_value = (False, "blocked: Live toggle is OFF")
        
        # Call create_stop_loss_order
        result = create_stop_loss_order(
            db=mock_db,
            symbol="BTC_USDT",
            side="BUY",
            sl_price=48000.0,
            quantity=0.001,
            entry_price=49000.0,
            dry_run=False,
        )
        
        # Assert: order should be blocked
        assert result["order_id"] is None
        assert "error" in result
        assert "blocked" in result["error"].lower()
        
        # Assert: exchange client should NOT be called
        mock_place_order.assert_not_called()
        
        # Assert: lifecycle event should be emitted
        mock_emit_event.assert_called_once()
        call_args = mock_emit_event.call_args
        assert call_args[1]["event_type"] == "SLTP_BLOCKED"
        assert "SL blocked" in call_args[1]["event_reason"]
        
        # Assert: Telegram message should be sent
        mock_telegram.send_message.assert_called_once()
        telegram_msg = mock_telegram.send_message.call_args[0][0]
        assert "SL/TP BLOCKED" in telegram_msg
        assert "STOP LOSS" in telegram_msg
    
    @patch('app.services.tp_sl_order_creator.telegram_notifier')
    @patch('app.services.signal_monitor._emit_lifecycle_event')
    @patch('app.services.tp_sl_order_creator.can_place_real_order')
    @patch.object(trade_client, 'place_stop_loss_order')
    def test_sl_blocked_when_kill_switch_on(self, mock_place_order, mock_can_place, mock_emit_event, mock_telegram, mock_db):
        """Test that SL order is blocked when Telegram kill switch is ON"""
        # Setup: guardrails block the order
        mock_can_place.return_value = (False, "blocked: Telegram kill switch is ON")
        
        # Call create_stop_loss_order
        result = create_stop_loss_order(
            db=mock_db,
            symbol="ETH_USDT",
            side="BUY",
            sl_price=2800.0,
            quantity=0.01,
            entry_price=2900.0,
            dry_run=False,
        )
        
        # Assert: order should be blocked
        assert result["order_id"] is None
        assert "error" in result
        assert "blocked" in result["error"].lower()
        
        # Assert: exchange client should NOT be called
        mock_place_order.assert_not_called()
        
        # Assert: lifecycle event should be emitted
        mock_emit_event.assert_called_once()
        call_args = mock_emit_event.call_args
        assert call_args[1]["event_type"] == "SLTP_BLOCKED"
        assert "kill switch" in call_args[1]["event_reason"].lower()
    
    @patch('app.services.tp_sl_order_creator.telegram_notifier')
    @patch('app.services.signal_monitor._emit_lifecycle_event')
    @patch('app.services.tp_sl_order_creator.can_place_real_order')
    @patch.object(trade_client, 'place_stop_loss_order')
    def test_sl_allowed_when_guardrails_pass(self, mock_place_order, mock_can_place, mock_emit_event, mock_telegram, mock_db):
        """Test that SL order is placed when guardrails pass"""
        # Setup: guardrails allow the order
        mock_can_place.return_value = (True, None)
        mock_place_order.return_value = {"order_id": "sl_12345"}
        
        # Call create_stop_loss_order
        result = create_stop_loss_order(
            db=mock_db,
            symbol="BTC_USDT",
            side="BUY",
            sl_price=48000.0,
            quantity=0.001,
            entry_price=49000.0,
            dry_run=False,
        )
        
        # Assert: order should be created
        assert result["order_id"] == "sl_12345"
        assert result.get("error") is None
        
        # Assert: exchange client should be called
        mock_place_order.assert_called_once()
        
        # Assert: lifecycle event should NOT be emitted (order not blocked)
        mock_emit_event.assert_not_called()
    
    @patch('app.services.tp_sl_order_creator.can_place_real_order')
    @patch.object(trade_client, 'place_stop_loss_order')
    def test_sl_bypasses_guardrails_in_dry_run(self, mock_place_order, mock_can_place, mock_db):
        """Test that guardrails are bypassed in dry_run mode"""
        # Setup
        mock_place_order.return_value = {"order_id": "sl_dry_12345"}
        
        # Call create_stop_loss_order with dry_run=True
        result = create_stop_loss_order(
            db=mock_db,
            symbol="BTC_USDT",
            side="BUY",
            sl_price=48000.0,
            quantity=0.001,
            entry_price=49000.0,
            dry_run=True,  # Dry run mode
        )
        
        # Assert: guardrails should NOT be checked
        mock_can_place.assert_not_called()
        
        # Assert: order should be created (dry run)
        assert result["order_id"] == "sl_dry_12345"
    
    @patch('app.services.tp_sl_order_creator.can_place_real_order')
    def test_can_place_called_with_ignore_trade_yes(self, mock_can_place, mock_db):
        """Test that can_place_real_order is called with ignore_trade_yes=True for SL/TP"""
        # Setup
        mock_can_place.return_value = (True, None)
        
        # Call create_stop_loss_order
        create_stop_loss_order(
            db=mock_db,
            symbol="BTC_USDT",
            side="BUY",
            sl_price=48000.0,
            quantity=0.001,
            entry_price=49000.0,
            dry_run=False,
        )
        
        # Assert: can_place_real_order should be called with ignore_trade_yes=True
        mock_can_place.assert_called_once()
        call_kwargs = mock_can_place.call_args[1]
        assert call_kwargs["ignore_trade_yes"] is True

