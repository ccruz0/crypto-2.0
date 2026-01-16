import os
import asyncio
import time
import tempfile
import uuid
import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.watchlist import WatchlistItem
from app.services.signal_monitor import SignalMonitorService
from app.services.signal_order_orchestrator import create_order_intent
from app.models.order_intent import OrderIntent


SQLALCHEMY_DATABASE_URL = "sqlite:///./test_alert_to_buy_flow.db"
engine = None
TestingSessionLocal = None


def _sqlite_db_paths(url_or_path: str) -> list[str]:
    if url_or_path.startswith("sqlite:////"):
        db_path = "/" + url_or_path[len("sqlite:////") :]
    elif url_or_path.startswith("sqlite:///"):
        db_path = url_or_path[len("sqlite:///") :]
    else:
        db_path = url_or_path

    if not db_path or db_path == ":memory:":
        return []

    candidate_paths = []
    if os.path.isabs(db_path):
        candidate_paths.append(db_path)
    else:
        candidate_paths.append(os.path.abspath(db_path))
        candidate_paths.append(os.path.abspath(os.path.join(os.path.dirname(__file__), db_path)))
        candidate_paths.append(
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", db_path))
        )
    return candidate_paths


def _cleanup_sqlite_db(url_or_path: str) -> None:
    candidate_paths = _sqlite_db_paths(url_or_path)
    if not candidate_paths:
        return

    for _ in range(5):
        removed_any = False
        for path in candidate_paths:
            for suffix in ("", "-wal", "-shm"):
                target = f"{path}{suffix}"
                if not os.path.exists(target):
                    continue
                try:
                    os.remove(target)
                    removed_any = True
                except OSError:
                    continue
        if not any(
            os.path.exists(f"{path}{suffix}")
            for path in candidate_paths
            for suffix in ("", "-wal", "-shm")
        ):
            return
        if not removed_any:
            time.sleep(0.2)


def _dedupe_table_indexes(table) -> None:
    seen = set()
    duplicates = []
    for idx in list(table.indexes):
        if idx.name in seen:
            duplicates.append(idx)
        else:
            seen.add(idx.name)
    for idx in duplicates:
        table.indexes.remove(idx)


def setup_module(module):
    db_url = SQLALCHEMY_DATABASE_URL
    _cleanup_sqlite_db(db_url)
    if any(os.path.exists(path) for path in _sqlite_db_paths(db_url)):
        temp_name = f"test_alert_to_buy_flow_{uuid.uuid4().hex}.db"
        db_url = f"sqlite:///{os.path.join(tempfile.gettempdir(), temp_name)}"
        _cleanup_sqlite_db(db_url)
    global engine, TestingSessionLocal
    engine = create_engine(
        db_url, connect_args={"check_same_thread": False}
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    _dedupe_table_indexes(OrderIntent.__table__)
    Base.metadata.create_all(bind=engine)


def teardown_module(module):
    if engine is None:
        return
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def get_test_db():
    if TestingSessionLocal is None:
        raise RuntimeError("TestingSessionLocal was not initialized.")
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_order_intent_created_when_signal_id_missing():
    os.environ["LIVE_TRADING"] = "true"
    db = next(get_test_db())
    try:
        order_intent, status = create_order_intent(
            db=db,
            signal_id=None,
            symbol="btc/usdt",
            side="BUY",
            message_content="BUY SIGNAL btc/usdt 1.00 test",
        )
        assert status in ("PENDING", "ORDER_BLOCKED_LIVE_TRADING")
        assert order_intent is not None
        assert order_intent.idempotency_key
    finally:
        db.close()


def test_place_order_from_signal_normalizes_symbol(monkeypatch):
    os.environ["LIVE_TRADING"] = "true"
    db = next(get_test_db())
    try:
        watchlist_item = WatchlistItem(
            symbol="btc/usdt",
            exchange="CRYPTO_COM",
            trade_enabled=True,
            alert_enabled=True,
            buy_alert_enabled=True,
            trade_amount_usd=100.0,
        )
        db.add(watchlist_item)
        db.commit()

        captured = {}

        def fake_place_market_order(*, symbol, side, notional=None, qty=None, is_margin=None, leverage=None, dry_run=None, source=None):
            captured["symbol"] = symbol
            captured["side"] = side
            return {"order_id": "test_order", "status": "NEW", "avg_price": 1.0, "quantity": 1.0}

        from app.services import signal_monitor as signal_monitor_module
        monkeypatch.setattr(signal_monitor_module.trade_client, "place_market_order", fake_place_market_order)

        service = SignalMonitorService()
        result = asyncio.run(
            service._place_order_from_signal(
                db=db,
                symbol="btc/usdt",
                side="BUY",
                watchlist_item=watchlist_item,
                current_price=1.0,
                source="test",
            )
        )

        assert captured.get("symbol") == "BTC_USDT"
        assert captured.get("side") == "BUY"
        assert result.get("order_id") == "test_order"
    finally:
        db.close()


def test_idempotency_key_content_based_when_signal_id_missing():
    """Test that idempotency key uses message_content + normalized symbol when signal_id is missing."""
    os.environ["LIVE_TRADING"] = "true"
    db = next(get_test_db())
    try:
        # Same message_content should produce same idempotency key
        db.query(OrderIntent).filter(OrderIntent.symbol == "BTC_USDT").delete()
        db.commit()

        intent1, status1 = create_order_intent(
            db=db,
            signal_id=None,
            symbol="btc/usdt",
            side="BUY",
            message_content="BUY SIGNAL btc/usdt 1.00 test",
            strategy_key="swing:conservative",
        )
        intent2, status2 = create_order_intent(
            db=db,
            signal_id=None,
            symbol="BTC_USDT",
            side="BUY",
            message_content="BUY SIGNAL btc/usdt 1.00 test",  # Same content
            strategy_key="swing:conservative",
        )

        assert intent1 is not None
        assert intent2 is not None
        assert intent1.id == intent2.id
        assert intent1.idempotency_key == intent2.idempotency_key
        assert status2 == "DEDUP_SKIPPED"

        # Different message_content should produce different idempotency key
        intent3, status3 = create_order_intent(
            db=db,
            signal_id=None,
            symbol="BTC_USDT",
            side="BUY",
            message_content="BUY SIGNAL btc/usdt 1.01 different",  # Different content
            strategy_key="swing:conservative",
        )

        assert intent3 is not None
        assert intent3.id != intent1.id
        assert intent3.idempotency_key != intent1.idempotency_key
        assert status3 == "PENDING"
    finally:
        db.close()
