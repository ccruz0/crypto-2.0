"""Fail-closed tests for get_live_trading_status.

Regression for the 2026-07-05 live-leak incident: the env var LIVE_TRADING was 'true'
while the DB said 'false'. On a transient DB read error the old code fell back to the env
and returned True, so the bot placed a REAL order while the operator believed trading was
OFF. With a DB session, the DB is authoritative and the function must FAIL CLOSED (False)
on any error or missing row — never fall back to a stale env.
"""
from unittest.mock import MagicMock, patch

from app.utils.live_trading import get_live_trading_status


def _db_returning(setting_value):
    db = MagicMock()
    row = MagicMock()
    row.setting_value = setting_value
    db.query.return_value.filter.return_value.first.return_value = row
    return db


def _db_no_row():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    return db


def _db_raising():
    db = MagicMock()
    db.query.side_effect = RuntimeError("db connection dropped")
    return db


def test_db_true_returns_true():
    assert get_live_trading_status(_db_returning("true")) is True


def test_db_false_returns_false():
    assert get_live_trading_status(_db_returning("false")) is False


@patch.dict("os.environ", {"LIVE_TRADING": "true"})
def test_db_error_fails_closed_even_when_env_true():
    # The exact incident: env='true', DB read errors -> MUST return False, not fall to env.
    assert get_live_trading_status(_db_raising()) is False


@patch.dict("os.environ", {"LIVE_TRADING": "true"})
def test_db_missing_row_fails_closed_even_when_env_true():
    # No DB row + stale env='true' -> default OFF (fail-closed).
    assert get_live_trading_status(_db_no_row()) is False


@patch.dict("os.environ", {"LIVE_TRADING": "true"})
def test_env_fallback_only_when_no_db_session():
    # Without a DB session the env var is still the source of truth.
    assert get_live_trading_status(None) is True


@patch.dict("os.environ", {"LIVE_TRADING": "false"})
def test_no_db_env_false_returns_false():
    assert get_live_trading_status(None) is False
