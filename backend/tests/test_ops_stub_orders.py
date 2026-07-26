"""Unit tests for ops stub order id helpers (no FastAPI import)."""

import unittest

from app.utils.ops_stub_orders import (
    OPS_STUB_CLOSED_PREFIX,
    is_ops_stub_closed_order_id,
)


class TestOpsStubOrders(unittest.TestCase):
    def test_is_ops_stub_closed_order_id(self):
        self.assertTrue(
            is_ops_stub_closed_order_id(
                "STUB-CLOSED-STOP_LOSS-5755600492155811564"
            )
        )
        self.assertTrue(
            is_ops_stub_closed_order_id(
                "stub-closed-TAKE_PROFIT-5755600492155811564"
            )
        )
        self.assertFalse(is_ops_stub_closed_order_id("73817490102011214"))
        self.assertFalse(is_ops_stub_closed_order_id(None))
        self.assertFalse(is_ops_stub_closed_order_id(""))
        self.assertEqual(OPS_STUB_CLOSED_PREFIX, "STUB-CLOSED-")


if __name__ == "__main__":
    unittest.main()
