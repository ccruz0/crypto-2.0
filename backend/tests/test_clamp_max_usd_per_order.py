"""Un limite de riesgo acota el tamano; no cancela la operacion.

Rechazar filtraba por TAMANO y no por calidad: el 19-ago-2026 cinco simbolos
(ETH_USD, AKT_USD, BTC_USD, SOL_USD, ALGO_USD) tenian trade_amount_usd=1000
contra un tope de 100 y no podian colocar ni una orden.
"""

import inspect
import unittest
from unittest.mock import patch

from app.utils.order_sizing import clamp_order_usd_to_limit


class TestClamp(unittest.TestCase):
    @patch("app.utils.trading_guardrails.resolve_max_usd_per_order", return_value=100.0)
    def test_oversized_is_capped_not_refused(self, _l):
        value, note = clamp_order_usd_to_limit(1000.0, symbol="BTC_USD", side="BUY")
        self.assertEqual(value, 100.0)
        self.assertIn("1000.00", note)

    @patch("app.utils.trading_guardrails.resolve_max_usd_per_order", return_value=100.0)
    def test_within_limit_untouched(self, _l):
        self.assertEqual(clamp_order_usd_to_limit(42.5), (42.5, None))

    @patch("app.utils.trading_guardrails.resolve_max_usd_per_order", return_value=100.0)
    def test_exact_limit_passes(self, _l):
        """El guardrail rechaza con `>`, asi que el limite exacto debe pasar."""
        self.assertEqual(clamp_order_usd_to_limit(100.0), (100.0, None))

    @patch("app.utils.trading_guardrails.resolve_max_usd_per_order", return_value=100.0)
    def test_none_and_zero(self, _l):
        self.assertEqual(clamp_order_usd_to_limit(None)[0], 0.0)
        self.assertEqual(clamp_order_usd_to_limit(0)[0], 0.0)

    @patch("app.utils.trading_guardrails.resolve_max_usd_per_order", return_value=100.0)
    def test_the_five_silenced_symbols(self, _l):
        for sym in ("ETH_USD", "AKT_USD", "BTC_USD", "SOL_USD", "ALGO_USD"):
            self.assertEqual(clamp_order_usd_to_limit(1000.0, symbol=sym)[0], 100.0, sym)


class TestBothOrderPathsAreCovered(unittest.TestCase):
    """SIGNAL_ORDER_REQUIRES_ALERT puede cambiar y despertar el camino dormido.

    La primera version de este arreglo solo cubria `_create_buy_order_impl`, que
    con la configuracion actual esta muerto: las ordenes reales van por
    `_place_order_from_signal_impl`. Las cinco monedas habrian seguido mudas.
    Estos tests fijan que AMBOS caminos recortan, sea cual sea el flag.
    """

    def _src(self, name):
        from app.services import signal_monitor as sm
        fn = getattr(sm.SignalMonitorService, name)
        return inspect.getsource(inspect.unwrap(fn))

    def test_live_path_clamps(self):
        src = self._src("_place_order_from_signal_impl")
        self.assertIn("clamp_order_usd_to_limit", src,
                      "el camino VIVO debe recortar")

    def test_legacy_path_clamps(self):
        src = self._src("_create_buy_order_impl")
        self.assertIn("clamp_order_usd_to_limit", src,
                      "el camino legacy tambien: el flag puede volver a activarlo")

    def test_orchestrator_guard_clamps(self):
        src = self._src("_orchestrator_order_guard")
        self.assertIn("clamp_order_usd_to_limit", src,
                      "el guard debe comprobar sobre el importe ya recortado")

    def test_clamp_is_applied_before_the_guardrail_call(self):
        """Recortar despues del check dejaria pasar una orden mayor que el limite."""
        src = self._src("_orchestrator_order_guard")
        self.assertLess(src.index("clamp_order_usd_to_limit"),
                        src.index("return can_place_real_order"))


class TestProtectedPathUntouched(unittest.TestCase):
    def test_helper_does_not_live_in_the_protected_module(self):
        """trading_guardrails.py es ruta protegida por Path Guard.

        El helper vive fuera porque es logica de DIMENSIONADO, del lado del
        llamador; el limite en si sigue siendo politica del guardrail y solo se
        lee. No es una evasion del control.
        """
        import app.utils.order_sizing as sizing
        import app.utils.trading_guardrails as guardrails
        self.assertTrue(hasattr(sizing, "clamp_order_usd_to_limit"))
        self.assertFalse(hasattr(guardrails, "clamp_order_usd_to_limit"))


if __name__ == "__main__":
    unittest.main()
