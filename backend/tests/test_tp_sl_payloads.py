"""
Test to compare payloads between automatic and manual TP/SL creation flows.
This ensures both flows send identical parameters to the exchange API.
"""
import unittest
from unittest.mock import patch, MagicMock
from sqlalchemy.orm import Session

from app.services.tp_sl_order_creator import create_take_profit_order, create_stop_loss_order
from app.database import SessionLocal


class TestTPSLPayloads(unittest.TestCase):
    """Test that automatic and manual TP/SL flows produce identical payloads"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.db = SessionLocal()
        self.captured_kwargs_auto = {}
        self.captured_kwargs_manual = {}
        
    def tearDown(self):
        """Clean up"""
        self.db.close()
    
    def _capture_auto_kwargs(self, *args, **kwargs):
        """Capture kwargs from automatic flow"""
        # Capture all arguments (both positional and keyword)
        captured = {}
        if args:
            # Map positional args to their parameter names based on place_take_profit_order signature
            # signature: (self, symbol, side, price, qty, *, trigger_price=None, entry_price=None, dry_run=True)
            param_names = ['symbol', 'side', 'price', 'qty']
            for i, arg in enumerate(args[1:]):  # Skip 'self'
                if i < len(param_names):
                    captured[param_names[i]] = arg
        captured.update(kwargs)
        self.captured_kwargs_auto.update(captured)
        # Return a mock successful response
        return {
            "order_id": "test_auto_order_123",
            "client_order_id": "test_auto_order_123",
            "status": "OPEN"
        }
    
    def _capture_manual_kwargs(self, *args, **kwargs):
        """Capture kwargs from manual flow"""
        # Capture all arguments (both positional and keyword)
        captured = {}
        if args:
            # Map positional args to their parameter names
            param_names = ['symbol', 'side', 'price', 'qty']
            for i, arg in enumerate(args[1:]):  # Skip 'self'
                if i < len(param_names):
                    captured[param_names[i]] = arg
        captured.update(kwargs)
        self.captured_kwargs_manual.update(captured)
        # Return a mock successful response
        return {
            "order_id": "test_manual_order_456",
            "client_order_id": "test_manual_order_456",
            "status": "OPEN"
        }
    
    @patch('app.services.tp_sl_order_creator.trade_client')
    def test_take_profit_payloads_match(self, mock_trade_client):
        """Test that automatic and manual TP creation use identical parameters"""
        # Setup mock to capture arguments
        mock_trade_client.place_take_profit_order = MagicMock(side_effect=[
            self._capture_auto_kwargs,  # First call (auto)
            self._capture_manual_kwargs  # Second call (manual)
        ])
        
        # Test parameters (same for both flows)
        symbol = "AKT_USDT"
        original_side = "BUY"  # Original order side
        tp_price = 1.5632
        quantity = 6.5
        entry_price = 1.5177
        
        # FLOW 1: Automatic (as called from exchange_sync.py)
        self.captured_kwargs_auto.clear()
        auto_result = create_take_profit_order(
            db=self.db,
            symbol=symbol,
            side=original_side,  # "BUY" - original order side
            tp_price=tp_price,
            quantity=quantity,
            entry_price=entry_price,
            parent_order_id="parent_auto_123",
            oco_group_id="oco_auto_123",
            dry_run=False,
            source="auto"
        )
        
        # FLOW 2: Manual (as called from sl_tp_checker.py)
        self.captured_kwargs_manual.clear()
        manual_result = create_take_profit_order(
            db=self.db,
            symbol=symbol,
            side=original_side,  # "BUY" - original order side (same as auto)
            tp_price=tp_price,
            quantity=quantity,
            entry_price=entry_price,
            parent_order_id="parent_manual_456",
            oco_group_id="oco_manual_456",
            dry_run=False,
            source="manual"
        )
        
        # Compare captured kwargs (excluding fields that should differ)
        # Fields that can differ (not sent to exchange):
        exclude_fields = {'source'}  # source is only for logging
        
        # Fields that might differ but are acceptable:
        # - parent_order_id, oco_group_id (different IDs are OK, but shouldn't affect exchange payload)
        
        # Extract only the parameters that go to place_take_profit_order
        auto_params = {k: v for k, v in self.captured_kwargs_auto.items() if k not in exclude_fields}
        manual_params = {k: v for k, v in self.captured_kwargs_manual.items() if k not in exclude_fields}
        
        # Compare critical fields that must match
        self.assertEqual(auto_params.get('symbol'), manual_params.get('symbol'), 
                         "symbol must match")
        self.assertEqual(auto_params.get('side'), manual_params.get('side'),
                         "side must match")
        self.assertEqual(auto_params.get('price'), manual_params.get('price'),
                         "price must match")
        self.assertEqual(auto_params.get('qty'), manual_params.get('qty'),
                         "qty must match")
        self.assertEqual(auto_params.get('trigger_price'), manual_params.get('trigger_price'),
                         "trigger_price must match")
        self.assertEqual(auto_params.get('entry_price'), manual_params.get('entry_price'),
                         "entry_price must match")
        self.assertEqual(auto_params.get('dry_run'), manual_params.get('dry_run'),
                         "dry_run must match")
        
        # Log the comparison for debugging
        print("\n" + "="*80)
        print("PAYLOAD COMPARISON: AUTO vs MANUAL")
        print("="*80)
        print(f"\nAUTO payload:")
        for k, v in sorted(auto_params.items()):
            print(f"  {k}: {v}")
        print(f"\nMANUAL payload:")
        for k, v in sorted(manual_params.items()):
            print(f"  {k}: {v}")
        print("\n" + "="*80)
        
        # Final assertion: all parameters must match
        self.assertEqual(auto_params, manual_params,
                         f"Payloads must be identical. Differences: "
                         f"auto={auto_params}, manual={manual_params}")
    
    @patch('app.services.tp_sl_order_creator.trade_client')
    def test_stop_loss_payloads_match(self, mock_trade_client):
        """Test that automatic and manual SL creation use identical parameters"""
        # Setup mock to capture arguments
        mock_trade_client.place_stop_loss_order = MagicMock(side_effect=[
            self._capture_auto_kwargs,  # First call (auto)
            self._capture_manual_kwargs  # Second call (manual)
        ])
        
        # Test parameters (same for both flows)
        symbol = "AKT_USDT"
        original_side = "BUY"  # Original order side
        sl_price = 1.4722
        quantity = 6.5
        entry_price = 1.5177
        
        # FLOW 1: Automatic (as called from exchange_sync.py)
        self.captured_kwargs_auto.clear()
        auto_result = create_stop_loss_order(
            db=self.db,
            symbol=symbol,
            side=original_side,  # "BUY" - original order side
            sl_price=sl_price,
            quantity=quantity,
            entry_price=entry_price,
            parent_order_id="parent_auto_123",
            oco_group_id="oco_auto_123",
            dry_run=False,
            source="auto"
        )
        
        # FLOW 2: Manual (as called from sl_tp_checker.py)
        self.captured_kwargs_manual.clear()
        manual_result = create_stop_loss_order(
            db=self.db,
            symbol=symbol,
            side=original_side,  # "BUY" - original order side (same as auto)
            sl_price=sl_price,
            quantity=quantity,
            entry_price=entry_price,
            parent_order_id="parent_manual_456",
            oco_group_id="oco_manual_456",
            dry_run=False,
            source="manual"
        )
        
        # Extract only the parameters that go to place_stop_loss_order
        exclude_fields = {'source'}
        auto_params = {k: v for k, v in self.captured_kwargs_auto.items() if k not in exclude_fields}
        manual_params = {k: v for k, v in self.captured_kwargs_manual.items() if k not in exclude_fields}
        
        # Compare critical fields
        self.assertEqual(auto_params.get('symbol'), manual_params.get('symbol'))
        self.assertEqual(auto_params.get('side'), manual_params.get('side'))
        self.assertEqual(auto_params.get('price'), manual_params.get('price'))
        self.assertEqual(auto_params.get('qty'), manual_params.get('qty'))
        self.assertEqual(auto_params.get('trigger_price'), manual_params.get('trigger_price'))
        self.assertEqual(auto_params.get('entry_price'), manual_params.get('entry_price'))
        self.assertEqual(auto_params.get('dry_run'), manual_params.get('dry_run'))
        
        # Final assertion
        self.assertEqual(auto_params, manual_params,
                         f"SL payloads must be identical. Differences: "
                         f"auto={auto_params}, manual={manual_params}")


if __name__ == '__main__':
    unittest.main()

