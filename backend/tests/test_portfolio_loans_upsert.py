"""portfolio_loans must hold one row per borrowed currency, not one per refresh.

update_portfolio_cache used to deactivate the historical rows for each borrowed
currency and INSERT a fresh one on every run. exchange_sync refreshes the cache
whenever it is older than 60s, so the table grew by one row per currency per
minute and nothing pruned it — prod reached id 518376 for what should be at most
one row per currency, and every refresh rewrote every historical row.
"""

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.portfolio import PortfolioBalance, PortfolioSnapshot
from app.models.portfolio_loan import PortfolioLoan

TABLES = [
    PortfolioBalance.__table__,
    PortfolioSnapshot.__table__,
    PortfolioLoan.__table__,
]


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine, tables=TABLES)
    session = session_local()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine, tables=TABLES)
        engine.dispose()


def _account(currency, balance):
    return {"currency": currency, "balance": balance, "available": balance}


def _run_cache_update(db_session, accounts):
    """Drive update_portfolio_cache with a stubbed exchange, bypassing dedup."""
    from app.services import portfolio_cache

    portfolio_cache._last_update_time = 0
    portfolio_cache._last_update_result = None

    with patch.object(
        portfolio_cache.trade_client, "get_account_summary",
        return_value={"accounts": accounts},
    ), patch.object(
        portfolio_cache, "resolve_crypto_credentials",
        create=True, return_value=("k", "s", "pair", None),
    ), patch.object(
        portfolio_cache, "get_crypto_prices",
        return_value={"XRP": 2.85, "DOGE": 0.0708},
    ):
        return portfolio_cache.update_portfolio_cache(db_session)


def test_repeated_refreshes_do_not_append_loan_rows(db_session):
    """Ten refreshes must leave one XRP row, not ten."""
    accounts = [_account("XRP", -0.34958214)]

    for _ in range(10):
        _run_cache_update(db_session, accounts)

    xrp_rows = db_session.query(PortfolioLoan).filter(
        PortfolioLoan.currency == "XRP"
    ).all()
    assert len(xrp_rows) == 1, f"expected 1 XRP row, got {len(xrp_rows)}"

    row = xrp_rows[0]
    assert row.is_active is True
    assert float(row.borrowed_amount) == pytest.approx(0.34958214)


def test_refresh_updates_the_amount_in_place(db_session):
    """A changed borrow must overwrite the row, not add a second one."""
    _run_cache_update(db_session, [_account("XRP", -0.34958214)])
    _run_cache_update(db_session, [_account("XRP", -0.5)])

    rows = db_session.query(PortfolioLoan).filter(
        PortfolioLoan.currency == "XRP"
    ).all()
    assert len(rows) == 1
    assert float(rows[0].borrowed_amount) == pytest.approx(0.5)


def test_repaid_currency_stops_being_active(db_session):
    """A loan that disappears must not stay flagged active with a stale amount.

    Prod had ALGO/DOGE/USD still is_active=True thousands of rows behind the
    rest, because the old code only ever touched currencies seen in that cycle.
    """
    _run_cache_update(db_session, [_account("XRP", -0.35), _account("DOGE", -2769.5)])
    _run_cache_update(db_session, [_account("XRP", -0.35)])

    active = db_session.query(PortfolioLoan).filter(
        PortfolioLoan.is_active == True  # noqa: E712
    ).all()
    assert {row.currency for row in active} == {"XRP"}

    doge = db_session.query(PortfolioLoan).filter(
        PortfolioLoan.currency == "DOGE"
    ).one()
    assert doge.is_active is False


def test_multiple_currencies_keep_one_row_each(db_session):
    accounts = [_account("XRP", -0.35), _account("DOGE", -2769.5)]
    for _ in range(5):
        _run_cache_update(db_session, accounts)

    assert db_session.query(PortfolioLoan).count() == 2


def test_full_repayment_retires_every_active_row(db_session):
    """When every loan is repaid, loans_found is empty — and that is the case
    that matters most.

    portfolio_snapshot only falls back to portfolio_loans when there are no
    negative balances left (`if total_borrowed_usd == 0.0`), which is exactly
    the full-repayment state. Rows left active there become the borrowed total
    of the wallet balance. Found by Cursor Bugbot on PR #504.
    """
    _run_cache_update(db_session, [_account("XRP", -0.35), _account("DOGE", -2769.5)])
    assert db_session.query(PortfolioLoan).filter(
        PortfolioLoan.is_active == True  # noqa: E712
    ).count() == 2

    # Everything repaid: no negative balances at all.
    _run_cache_update(db_session, [_account("XRP", 12.0), _account("DOGE", 4.0)])

    active = db_session.query(PortfolioLoan).filter(
        PortfolioLoan.is_active == True  # noqa: E712
    ).all()
    assert active == [], f"stale active rows survive full repayment: {active}"

    # The rows stay for history, they are just no longer active.
    assert db_session.query(PortfolioLoan).count() == 2
