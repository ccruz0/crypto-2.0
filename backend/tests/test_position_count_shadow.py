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


class _CapLot:
    def __init__(self, qty, entry_id, buy_time=None, symbol="APT_USD"):
        from datetime import datetime, timezone
        self.lot_qty = Decimal(str(qty))
        self.buy_order_id = entry_id
        self.buy_time = buy_time or datetime(2026, 8, 27, tzinfo=timezone.utc)
        self.symbol = symbol


class TestWalletCapForCount:
    """The counted quantity must fit in |wallet|; the display path is untouched.

    Regression for the APT case of 28-ago-2026: protected 173.10 + naked
    ghosts 17.65/17.54 (entries of 2-3 ago, protections mass-cancelled 11-ago)
    = 208.29 counted vs wallet 173.49 -> count said 3, truth was 1.
    """

    def _protected(self, ids):
        return patch(
            "app.services.expected_take_profit._protected_entry_ids_for_lots",
            return_value=set(ids),
        )

    def test_apt_ghosts_are_dropped(self, mock_db):
        from datetime import datetime, timezone
        real = _CapLot("173.10", "e-real", datetime(2026, 8, 27, 8, tzinfo=timezone.utc))
        ghost1 = _CapLot("17.65", "e-ghost-aug2", datetime(2026, 8, 2, tzinfo=timezone.utc))
        ghost2 = _CapLot("17.54", "e-ghost-aug3", datetime(2026, 8, 3, tzinfo=timezone.utc))
        with self._protected({"e-real"}):
            kept, dropped = pcs._cap_lots_to_wallet_for_count(
                mock_db, [ghost1, ghost2, real], Decimal("173.48953042")
            )
        assert dropped == 2
        assert [l.buy_order_id for l in kept] == ["e-real"]

    def test_exact_match_passes_untouched(self, mock_db):
        lot = _CapLot("1.84335603", "e-dot")
        with self._protected({"e-dot"}):
            kept, dropped = pcs._cap_lots_to_wallet_for_count(
                mock_db, [lot], Decimal("1.84335603")
            )
        assert dropped == 0 and len(kept) == 1

    def test_naked_real_fill_within_capacity_is_kept(self, mock_db):
        """ETH_USDT-style: a naked fill that FITS in wallet stays counted."""
        from datetime import datetime, timezone
        protected = _CapLot("1.0", "e-prot")
        naked = _CapLot("0.5", "e-naked", datetime(2026, 8, 28, tzinfo=timezone.utc))
        with self._protected({"e-prot"}):
            kept, dropped = pcs._cap_lots_to_wallet_for_count(
                mock_db, [protected, naked], Decimal("1.6")
            )
        assert dropped == 0
        assert {l.buy_order_id for l in kept} == {"e-prot", "e-naked"}

    def test_newest_naked_wins_over_oldest(self, mock_db):
        from datetime import datetime, timezone
        old = _CapLot("0.5", "e-old", datetime(2026, 8, 1, tzinfo=timezone.utc))
        new = _CapLot("0.5", "e-new", datetime(2026, 8, 28, tzinfo=timezone.utc))
        with self._protected(set()):
            kept, dropped = pcs._cap_lots_to_wallet_for_count(
                mock_db, [old, new], Decimal("0.6")
            )
        assert dropped == 1
        assert [l.buy_order_id for l in kept] == ["e-new"]

    def test_protected_never_dropped_even_over_wallet(self, mock_db):
        lot = _CapLot("10.0", "e-prot-big")
        with self._protected({"e-prot-big"}):
            kept, dropped = pcs._cap_lots_to_wallet_for_count(
                mock_db, [lot], Decimal("7.0")
            )
        assert dropped == 0 and len(kept) == 1

    def test_zero_wallet_passes_through(self, mock_db):
        lot = _CapLot("5.0", "e-any")
        kept, dropped = pcs._cap_lots_to_wallet_for_count(mock_db, [lot], Decimal("0"))
        assert dropped == 0 and len(kept) == 1
