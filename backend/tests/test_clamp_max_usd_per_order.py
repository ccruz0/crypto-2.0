"""Un limite de riesgo acota el tamano; no cancela la operacion.

Rechazar filtraba por TAMANO y no por calidad: el 19-ago-2026 cinco simbolos
(ETH_USD, AKT_USD, BTC_USD, SOL_USD, ALGO_USD) tenian trade_amount_usd=1000
contra un tope de 100 y no podian colocar ni una orden. 1000 > 100 siempre,
independientemente del mercado.
"""

import unittest
from unittest.mock import patch

from app.utils.trading_guardrails import clamp_order_usd_to_limit


class TestClampOrderUsd(unittest.TestCase):
    @patch("app.utils.trading_guardrails.resolve_max_usd_per_order", return_value=100.0)
    def test_oversized_order_is_capped_not_refused(self, _limit):
        value, note = clamp_order_usd_to_limit(1000.0, symbol="BTC_USD", side="BUY")
        self.assertEqual(value, 100.0)
        self.assertIsNotNone(note)
        self.assertIn("1000.00", note)
        self.assertIn("100.00", note)

    @patch("app.utils.trading_guardrails.resolve_max_usd_per_order", return_value=100.0)
    def test_order_within_limit_is_untouched(self, _limit):
        value, note = clamp_order_usd_to_limit(42.5, symbol="XRP", side="BUY")
        self.assertEqual(value, 42.5)
        self.assertIsNone(note, "no debe anotarse nada si no se recorta")

    @patch("app.utils.trading_guardrails.resolve_max_usd_per_order", return_value=100.0)
    def test_exactly_at_the_limit_passes_unchanged(self, _limit):
        """El guardrail rechaza con `>`, asi que el limite exacto debe pasar."""
        value, note = clamp_order_usd_to_limit(100.0)
        self.assertEqual(value, 100.0)
        self.assertIsNone(note)

    @patch("app.utils.trading_guardrails.resolve_max_usd_per_order", return_value=100.0)
    def test_clamped_value_survives_the_guardrail(self, _limit):
        """La razon de recortar en el origen: el valor devuelto debe pasar el check.

        Si el recorte se hiciera solo en la comprobacion y la colocacion usara el
        importe original, se saltaria el limite en vez de aplicarlo — peor que
        rechazar.
        """
        value, _ = clamp_order_usd_to_limit(1000.0)
        self.assertLessEqual(value, 100.0)

    @patch("app.utils.trading_guardrails.resolve_max_usd_per_order", return_value=100.0)
    def test_none_and_zero_do_not_explode(self, _limit):
        self.assertEqual(clamp_order_usd_to_limit(None)[0], 0.0)
        self.assertEqual(clamp_order_usd_to_limit(0)[0], 0.0)

    @patch("app.utils.trading_guardrails.resolve_max_usd_per_order", return_value=100.0)
    def test_the_five_silenced_symbols_can_now_trade(self, _limit):
        """Los cinco casos reales de produccion, todos con 1000 configurado."""
        for sym in ("ETH_USD", "AKT_USD", "BTC_USD", "SOL_USD", "ALGO_USD"):
            value, note = clamp_order_usd_to_limit(1000.0, symbol=sym, side="BUY")
            self.assertEqual(value, 100.0, sym)
            self.assertIsNotNone(note, sym)


if __name__ == "__main__":
    unittest.main()
