"""El auditor de parents desnudos no debe alertar por posiciones ya cerradas via OCO.

Un OCO real llena UNA pata (SL o TP) y cancela la otra. El bug corregido:
_is_naked exigia ambas patas FILLED (imposible en un OCO) y el HOURLY SL/TP
AUDIT re-alertaba cada hora, durante los 7 dias de lookback, por parents ya
cerrados. El caso ETH micro oculto por wallet-sum solo alerta cuando wallet-sum
NO cubre SL+TP (issue #617); _iter_naked_entry_parents sigue encontrandolo.
"""
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
from app.services.sl_tp_checker import _iter_naked_entry_parents


def _parent():
    return ExchangeOrder(
        exchange_order_id="parent-1",
        symbol="BONK_USD",
        order_role=None,
        status=OrderStatusEnum.FILLED,
        exchange_create_time=datetime.now(timezone.utc),
    )


def _chained_query_db(rows):
    db = MagicMock()
    q = MagicMock()
    q.filter.return_value = q
    q.order_by.return_value = q
    q.all.return_value = rows
    db.query.return_value = q
    return db


class TestNakedParentClosedOco(unittest.TestCase):
    def _run(self, filled_side_effect):
        db = _chained_query_db([_parent()])
        with patch(
            "app.services.expected_take_profit.rebuild_open_lots", return_value=[]
        ), patch(
            "app.services.sl_tp_protection.has_complete_sl_tp_protection",
            return_value=False,
        ), patch(
            "app.services.sl_tp_protection.has_filled_sl_tp_protection",
            return_value=False,
        ), patch(
            "app.services.sl_tp_protection.get_active_protection_order",
            return_value=None,
        ), patch(
            "app.services.sl_tp_protection.get_filled_protection_order",
            side_effect=filled_side_effect,
        ):
            return _iter_naked_entry_parents(db, "BONK_USD")

    def test_parent_cerrado_por_sl_filled_no_es_naked(self):
        closed = ExchangeOrder(
            exchange_order_id="sl-1",
            order_role="STOP_LOSS",
            status=OrderStatusEnum.FILLED,
        )

        def fake(db, pid, role):
            return closed if role == "STOP_LOSS" else None

        self.assertEqual(self._run(fake), [])

    def test_parent_cerrado_por_tp_filled_no_es_naked(self):
        closed = ExchangeOrder(
            exchange_order_id="tp-1",
            order_role="TAKE_PROFIT",
            status=OrderStatusEnum.FILLED,
        )

        def fake(db, pid, role):
            return closed if role == "TAKE_PROFIT" else None

        self.assertEqual(self._run(fake), [])

    def test_parent_sin_ningun_hijo_sigue_alertando(self):
        result = self._run(lambda db, pid, role: None)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].exchange_order_id, "parent-1")


if __name__ == "__main__":
    unittest.main()
