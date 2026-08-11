"""Tests for ghost protection list/clean helpers (Monitoring box)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.ghost_protection import (
    clean_ghost_protection_alerts,
    list_ghost_protection_alerts,
)


def _tp_order(**kwargs):
    defaults = dict(
        order_type="TAKE_PROFIT_LIMIT",
        status="ACTIVE",
        base_symbol="ALGO",
        symbol="ALGO_USDT",
        quantity=125.0,
        order_id="ghost-1",
        order_role="TAKE_PROFIT",
        side="BUY",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_list_ghost_protection_alerts_filters_wrong_side():
    orders = [_tp_order()]
    balances = [{"currency": "ALGO", "balance": 400.0}]
    resolved = SimpleNamespace(orders=orders, sync_status="ok")

    with (
        patch(
            "app.services.ghost_protection.resolve_open_orders",
            return_value=resolved,
        ),
        patch(
            "app.services.ghost_protection.balances_from_account_summary",
            return_value=balances,
        ),
    ):
        db = MagicMock()
        result = list_ghost_protection_alerts(db)

    assert result["ok"] is True
    assert result["count"] == 1
    assert result["by_base"] == {"ALGO": 1}
    assert result["alerts"][0]["reason"] == "wrong_side_cover_on_long"
    assert result["alerts"][0]["order_id"] == "ghost-1"


def test_list_ghost_protection_alerts_bases_filter():
    orders = [
        _tp_order(order_id="a", base_symbol="ALGO", symbol="ALGO_USDT"),
        _tp_order(
            order_id="b",
            base_symbol="SUI",
            symbol="SUI_USDT",
            quantity=50.0,
        ),
    ]
    balances = [
        {"currency": "ALGO", "balance": 400.0},
        {"currency": "SUI", "balance": 10.0},
    ]
    resolved = SimpleNamespace(orders=orders, sync_status="ok")

    with patch(
        "app.services.ghost_protection.resolve_open_orders",
        return_value=resolved,
    ):
        db = MagicMock()
        result = list_ghost_protection_alerts(
            db, bases=["ALGO"], balances=balances
        )

    assert result["count"] == 1
    assert result["alerts"][0]["base"] == "ALGO"


def test_clean_ghost_dry_run_does_not_cancel():
    orders = [_tp_order()]
    balances = [{"currency": "ALGO", "balance": 400.0}]
    resolved = SimpleNamespace(
        orders=orders, sync_status="ok", data_verified=True, source="crypto_com_api"
    )

    with (
        patch(
            "app.services.ghost_protection.resolve_open_orders",
            return_value=resolved,
        ),
        patch(
            "app.services.ghost_protection.cancel_protection_order_on_exchange"
        ) as cancel_mock,
    ):
        db = MagicMock()
        result = clean_ghost_protection_alerts(
            db, dry_run=True, balances=balances
        )

    cancel_mock.assert_not_called()
    assert result["dry_run"] is True
    assert result["cancelled"] == 0
    assert result["count"] == 1
    assert result["results"][0]["status"] == "would_cancel"


def test_clean_ghost_live_cancels_and_marks_db():
    orders = [_tp_order()]
    balances = [{"currency": "ALGO", "balance": 400.0}]
    resolved = SimpleNamespace(
        orders=orders, sync_status="ok", data_verified=True, source="crypto_com_api"
    )
    row = MagicMock()
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = row

    with (
        patch(
            "app.services.ghost_protection.resolve_open_orders",
            return_value=resolved,
        ),
        patch(
            "app.services.ghost_protection.cancel_protection_order_on_exchange",
            return_value={"order_id": "ghost-1"},
        ) as cancel_mock,
    ):
        result = clean_ghost_protection_alerts(
            db, dry_run=False, balances=balances
        )

    cancel_mock.assert_called_once_with("ghost-1", order_type="TAKE_PROFIT_LIMIT")
    assert result["cancelled"] == 1
    assert result["failed"] == 0
    assert result["results"][0]["status"] == "cancelled"
    assert row.status is not None
    db.commit.assert_called()


def test_clean_only_requested_order_ids():
    orders = [
        _tp_order(order_id="keep-me"),
        _tp_order(order_id="cancel-me", quantity=200.0),
    ]
    balances = [{"currency": "ALGO", "balance": 400.0}]
    resolved = SimpleNamespace(
        orders=orders, sync_status="ok", data_verified=True, source="crypto_com_api"
    )

    with (
        patch(
            "app.services.ghost_protection.resolve_open_orders",
            return_value=resolved,
        ),
        patch(
            "app.services.ghost_protection.cancel_protection_order_on_exchange",
            return_value={},
        ) as cancel_mock,
    ):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        result = clean_ghost_protection_alerts(
            db,
            dry_run=False,
            order_ids=["cancel-me"],
            balances=balances,
        )

    cancel_mock.assert_called_once_with("cancel-me", order_type="TAKE_PROFIT_LIMIT")
    assert result["count"] == 1
    assert result["cancelled"] == 1


def test_clean_live_refuses_stale_sync():
    orders = [_tp_order()]
    balances = [{"currency": "ALGO", "balance": 400.0}]
    resolved = SimpleNamespace(
        orders=orders,
        sync_status="stale_cache_db_fallback",
        data_verified=True,
        source="database_fallback",
    )

    with (
        patch(
            "app.services.ghost_protection.resolve_open_orders",
            return_value=resolved,
        ),
        patch(
            "app.services.ghost_protection.cancel_protection_order_on_exchange"
        ) as cancel_mock,
    ):
        db = MagicMock()
        result = clean_ghost_protection_alerts(
            db, dry_run=False, balances=balances
        )

    cancel_mock.assert_not_called()
    assert result["ok"] is False
    assert result["cancelled"] == 0
    assert "Refusing live cancel" in (result.get("error") or "")


def test_clean_live_allow_stale_overrides_gate():
    orders = [_tp_order()]
    balances = [{"currency": "ALGO", "balance": 400.0}]
    resolved = SimpleNamespace(
        orders=orders,
        sync_status="stale_cache_db_fallback",
        data_verified=False,
        source="database_fallback",
    )

    with (
        patch(
            "app.services.ghost_protection.resolve_open_orders",
            return_value=resolved,
        ),
        patch(
            "app.services.ghost_protection.cancel_protection_order_on_exchange",
            return_value={},
        ) as cancel_mock,
    ):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        result = clean_ghost_protection_alerts(
            db, dry_run=False, balances=balances, allow_stale=True
        )

    cancel_mock.assert_called_once()
    assert result["cancelled"] == 1
