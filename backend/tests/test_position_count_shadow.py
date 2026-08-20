"""Tests for the shadow position counter (PASO B1).

The single property that matters here is that the shadow cannot influence
anything. Everything else it does is measurement, and a measurement that can
change the thing it measures is worse than no measurement at all.

Destination: backend/tests/test_position_count_shadow.py
"""
import logging
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from app.services import position_count_shadow as pcs


@pytest.fixture
def mock_db():
    return MagicMock(spec=Session)


@pytest.fixture(autouse=True)
def _clear_wallet_cache():
    pcs._wallet_cache = {}
    pcs._wallet_cache_at = 0.0
    pcs._wallet_cache_ok = False
    yield


class _Lot:
    def __init__(self, qty, short=False):
        self.lot_qty = Decimal(str(qty))
        self.symbol = "ALGO_USD"
        self._short = short


class TestShadowCannotDecide:
    """The hook must be inert by construction, not by convention."""

    def test_record_returns_nothing(self, mock_db):
        with patch.object(pcs, "count_open_lots_for_symbol", return_value={
            "base": "ALGO", "count": 2, "lots_before_wallet": 2, "long_qty": 238.0,
            "short_qty": 0.0, "wallet": 71.1, "wallet_ok": True, "aligned": True,
            "warning": None,
        }):
            assert pcs.record_shadow_count(mock_db, "ALGO", 0) is None

    def test_shadow_error_is_swallowed_and_logged(self, mock_db, caplog):
        """A shadow that dies quietly would read as 'no divergence'."""
        with patch.object(pcs, "count_open_lots_for_symbol", side_effect=RuntimeError("boom")):
            with caplog.at_level(logging.WARNING):
                assert pcs.record_shadow_count(mock_db, "ALGO", 0) is None
        assert "shadow=ERROR" in caplog.text

    def test_legacy_count_is_untouched_when_shadow_explodes(self, mock_db):
        """The real guarantee: the caller's number survives a shadow failure."""
        with patch(
            "app.services.position_count_shadow.record_shadow_count",
            side_effect=RuntimeError("shadow exploded"),
        ):
            # count_open_positions_for_symbol wraps the hook in try/except, so a
            # detonating shadow must not propagate.
            from app.services.order_position_service import count_open_positions_for_symbol

            db = MagicMock(spec=Session)
            db.query.return_value.filter.return_value.all.return_value = []
            db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
            assert count_open_positions_for_symbol(db, "ALGO") == 0


class TestShadowIsDisableable:
    def test_disabled_by_env_does_no_work(self, mock_db, monkeypatch):
        monkeypatch.setenv("POSITION_COUNT_SHADOW_ENABLED", "false")
        with patch.object(pcs, "count_open_lots_for_symbol") as counted:
            pcs.record_shadow_count(mock_db, "ALGO", 0)
        counted.assert_not_called()


class TestWalletHandling:
    def test_wallet_failure_is_reported_not_hidden(self, mock_db, caplog):
        """B1 never blocks on a wallet failure — but it must say so."""
        with patch.object(pcs, "_load_wallet_by_base", return_value=({}, False)):
            with patch("app.services.expected_take_profit.rebuild_open_lots", return_value=[]):
                result = pcs.count_open_lots_for_symbol(mock_db, "ALGO")
        assert result["wallet_ok"] is False
        assert result["aligned"] is False

    def test_wallet_is_cached_across_calls(self, mock_db, monkeypatch):
        """One exchange round-trip per TTL, not one per guard invocation."""
        monkeypatch.setenv("POSITION_COUNT_SHADOW_WALLET_TTL", "600")
        summary = {"result": {"accounts": [{"currency": "ALGO", "balance": "71.11"}]}}
        client = MagicMock()
        client.get_account_summary.return_value = summary
        with patch.dict("sys.modules"):
            with patch("app.services.brokers.crypto_com_trade.trade_client", client):
                first, ok1 = pcs._load_wallet_by_base()
                second, ok2 = pcs._load_wallet_by_base()
        assert ok1 and ok2
        assert first["ALGO"] == Decimal("71.11")
        assert second["ALGO"] == Decimal("71.11")
        assert client.get_account_summary.call_count == 1


class TestDivergenceLogging:
    def test_divergence_is_flagged_with_cost(self, mock_db, caplog):
        with patch.object(pcs, "count_open_lots_for_symbol", return_value={
            "base": "ALGO", "count": 2, "lots_before_wallet": 3, "long_qty": 238.0,
            "short_qty": 0.0, "wallet": 71.1, "wallet_ok": True, "aligned": True,
            "warning": None,
        }):
            with caplog.at_level(logging.INFO):
                pcs.record_shadow_count(mock_db, "ALGO", 0)
        line = caplog.text
        assert "legacy=0" in line and "shadow=2" in line and "diverge=1" in line
        assert "ms=" in line, "sin coste medido no se puede decidir la cache de B2"

    def test_agreement_is_logged_too(self, mock_db, caplog):
        """Only logging divergences would hide the denominator."""
        with patch.object(pcs, "count_open_lots_for_symbol", return_value={
            "base": "SOL", "count": 0, "lots_before_wallet": 0, "long_qty": 0.0,
            "short_qty": 0.0, "wallet": 0.0, "wallet_ok": True, "aligned": True,
            "warning": None,
        }):
            with caplog.at_level(logging.INFO):
                pcs.record_shadow_count(mock_db, "SOL", 0)
        assert "diverge=0" in caplog.text
