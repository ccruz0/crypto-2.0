"""TradeSignal must be per exchange order, not one row per symbol."""
import unittest
from unittest.mock import MagicMock, patch

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.signal_writer import upsert_trade_signal


class TestPerOrderTradeSignal(unittest.TestCase):
    def _mock_db_chain(self, first_results):
        """Return mock db where sequential .first() calls yield from first_results."""
        db = MagicMock()
        filters = []

        def _query(*_args, **_kwargs):
            chain = MagicMock()
            idx = {"i": 0}

            def _first():
                i = idx["i"]
                idx["i"] += 1
                if i < len(first_results):
                    return first_results[i]
                return None

            chain.filter.return_value = chain
            chain.first.side_effect = _first
            filters.append(chain)
            return chain

        db.query.side_effect = _query
        return db, filters

    @patch("app.services.signal_writer.TradeSignal")
    def test_two_doge_orders_create_two_trade_signals(self, mock_trade_signal_cls):
        """Regression: second DOGE BUY must not overwrite first order's exchange_order_id."""
        db, _ = self._mock_db_chain([None, None])  # no existing rows per order lookup

        created = []

        def _make_signal(**kwargs):
            sig = MagicMock()
            sig.id = len(created) + 1
            for k, v in kwargs.items():
                setattr(sig, k, v)
            created.append(sig)
            return sig

        mock_trade_signal_cls.side_effect = _make_signal

        order_a = "5755600491448633454"
        order_b = "5755600491449038884"

        upsert_trade_signal(
            db=db,
            symbol="DOGE_USD",
            exchange_order_id=order_a,
            status="order_placed",
            should_trade=True,
        )
        upsert_trade_signal(
            db=db,
            symbol="DOGE_USD",
            exchange_order_id=order_b,
            status="order_placed",
            should_trade=True,
        )

        self.assertEqual(mock_trade_signal_cls.call_count, 2)
        self.assertEqual(created[0].exchange_order_id, order_a)
        self.assertEqual(created[1].exchange_order_id, order_b)
        self.assertEqual(db.add.call_count, 2)
        self.assertEqual(db.commit.call_count, 2)


if __name__ == "__main__":
    unittest.main()
