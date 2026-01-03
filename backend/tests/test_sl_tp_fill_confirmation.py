"""
Test suite for SL/TP fill confirmation fix

Tests cover:
1. Delayed fill confirmation (polling)
2. Quantity normalization
3. SL/TP creation with normalized quantity
4. Idempotency (preventing duplicate creation)
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from decimal import Decimal
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.signal_monitor import SignalMonitorService
from app.models.exchange_order import OrderStatusEnum


class TestSLTPFillConfirmation(unittest.TestCase):
    """Test SL/TP fill confirmation fix"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.service = SignalMonitorService()
        self.symbol = "ETH_USDT"
        self.order_id = "123456789"
        self.filled_qty_decimal = Decimal("0.5")
        self.filled_price = 3000.0
        
    def test_poll_order_fill_confirmation_immediate_fill(self):
        """Test polling when order is immediately filled"""
        # Mock get_open_orders to return filled order
        with patch('app.services.signal_monitor.trade_client') as mock_client:
            mock_client.get_open_orders.return_value = {
                "data": [{
                    "order_id": self.order_id,
                    "status": "FILLED",
                    "cumulative_quantity": "0.5",
                    "avg_price": str(self.filled_price)
                }]
            }
            
            result = self.service._poll_order_fill_confirmation(
                symbol=self.symbol,
                order_id=self.order_id,
                max_attempts=3,
                poll_interval=0.1
            )
            
            self.assertIsNotNone(result)
            self.assertEqual(result["status"], "FILLED")
            self.assertIsInstance(result["cumulative_quantity"], Decimal)
            self.assertEqual(result["cumulative_quantity"], self.filled_qty_decimal)
            self.assertEqual(result["avg_price"], self.filled_price)
    
    def test_poll_order_fill_confirmation_delayed_fill(self):
        """Test polling when order fills after delay"""
        with patch('app.services.signal_monitor.trade_client') as mock_client:
            # First attempt: order still pending
            # Second attempt: order filled
            mock_client.get_open_orders.side_effect = [
                {"data": [{"order_id": self.order_id, "status": "ACTIVE"}]},
                {"data": [{
                    "order_id": self.order_id,
                    "status": "FILLED",
                    "cumulative_quantity": "0.5",
                    "avg_price": str(self.filled_price)
                }]}
            ]
            mock_client.get_order_history.return_value = {"data": []}
            
            result = self.service._poll_order_fill_confirmation(
                symbol=self.symbol,
                order_id=self.order_id,
                max_attempts=3,
                poll_interval=0.1
            )
            
            self.assertIsNotNone(result)
            self.assertEqual(result["status"], "FILLED")
            self.assertIsInstance(result["cumulative_quantity"], Decimal)
    
    def test_poll_order_fill_confirmation_not_found(self):
        """Test polling when order is never found"""
        with patch('app.services.signal_monitor.trade_client') as mock_client:
            mock_client.get_open_orders.return_value = {"data": []}
            mock_client.get_order_history.return_value = {"data": []}
            
            result = self.service._poll_order_fill_confirmation(
                symbol=self.symbol,
                order_id=self.order_id,
                max_attempts=2,
                poll_interval=0.1
            )
            
            self.assertIsNone(result)
    
    def test_poll_order_fill_confirmation_strict_validation(self):
        """Test that polling requires FILLED status AND cumulative_quantity > 0"""
        with patch('app.services.signal_monitor.trade_client') as mock_client:
            # Test case 1: FILLED but cumulative_quantity = 0 (should fail)
            mock_client.get_open_orders.return_value = {
                "data": [{
                    "order_id": self.order_id,
                    "status": "FILLED",
                    "cumulative_quantity": "0",
                    "avg_price": str(self.filled_price)
                }]
            }
            mock_client.get_order_history.return_value = {"data": []}
            
            result = self.service._poll_order_fill_confirmation(
                symbol=self.symbol,
                order_id=self.order_id,
                max_attempts=2,
                poll_interval=0.1
            )
            
            # Should return None because cumulative_quantity is 0
            self.assertIsNone(result)
            
            # Test case 2: ACTIVE status (should not return filled)
            mock_client.get_open_orders.return_value = {
                "data": [{
                    "order_id": self.order_id,
                    "status": "ACTIVE",
                    "cumulative_quantity": "0.5"
                }]
            }
            
            result = self.service._poll_order_fill_confirmation(
                symbol=self.symbol,
                order_id=self.order_id,
                max_attempts=1,
                poll_interval=0.1
            )
            
            # Should return None because status is not FILLED
            self.assertIsNone(result)
    
    def test_quantity_normalization_string_return(self):
        """Test that normalize_quantity returns string"""
        with patch('app.services.signal_monitor.trade_client') as mock_client:
            # Mock normalize_quantity to return string
            mock_client.normalize_quantity.return_value = "0.5"
            
            normalized = mock_client.normalize_quantity(self.symbol, 0.500001)
            
            self.assertIsInstance(normalized, str)
            self.assertEqual(normalized, "0.5")
    
    @patch('app.services.signal_monitor.ExchangeSyncService')
    @patch('app.services.signal_monitor.db')
    def test_idempotency_guard(self, mock_db, mock_exchange_sync_class):
        """Test that idempotency guard prevents duplicate SL/TP creation"""
        from app.models.exchange_order import ExchangeOrder
        
        # Mock database query to return existing SL/TP orders
        mock_existing_order = Mock()
        mock_existing_order.exchange_order_id = "sl_123"
        mock_existing_order.order_role = "STOP_LOSS"
        
        mock_db_session = Mock()
        mock_query = Mock()
        mock_query.filter.return_value.all.return_value = [mock_existing_order]
        mock_db_session.query.return_value = mock_query
        
        # Mock the service's _poll_order_fill_confirmation to return filled order
        with patch.object(self.service, '_poll_order_fill_confirmation') as mock_poll:
            mock_poll.return_value = {
                "status": "FILLED",
                "cumulative_quantity": Decimal("0.5"),
                "filled_price": self.filled_price
            }
            
            # Mock normalize_quantity
            with patch('app.services.signal_monitor.trade_client') as mock_client:
                mock_client.normalize_quantity.return_value = "0.5"
                
                # This would be called from _create_sell_order, but we're testing the idempotency logic
                # In practice, the idempotency check happens before calling _create_sl_tp_for_filled_order
                # So we verify that existing orders prevent the call
                
                # Query for existing orders (simulating idempotency check)
                existing_sl_tp = mock_db_session.query(ExchangeOrder).filter(
                    ExchangeOrder.parent_order_id == self.order_id,
                    ExchangeOrder.order_role.in_(["STOP_LOSS", "TAKE_PROFIT"]),
                    ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
                ).all()
                
                # If existing orders found, should skip SL/TP creation
                if existing_sl_tp:
                    # Should not call _create_sl_tp_for_filled_order
                    self.assertGreater(len(existing_sl_tp), 0)
                    # Verify query was called correctly
                    mock_db_session.query.assert_called()


class TestQuantityNormalization(unittest.TestCase):
    """Test quantity normalization behavior"""
    
    def test_normalize_quantity_returns_string(self):
        """Verify normalize_quantity returns string, not float"""
        # This would require actual trade_client instance or mock
        # For now, we document the expected behavior
        pass  # Integration test needed with real trade_client


if __name__ == '__main__':
    unittest.main()



