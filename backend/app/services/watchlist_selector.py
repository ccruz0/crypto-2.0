import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.watchlist import WatchlistItem

logger = logging.getLogger(__name__)


def _row_timestamp(item: WatchlistItem) -> float:
    value = getattr(item, "updated_at", None) or getattr(item, "modified_at", None) or getattr(item, "created_at", None)
    if isinstance(value, datetime):
        try:
            return value.timestamp()
        except Exception:
            return 0.0
    return 0.0


def select_preferred_watchlist_item(items: List[WatchlistItem], symbol: str) -> Optional[WatchlistItem]:
    """Pick the canonical watchlist row for a symbol when duplicates exist."""
    if not items:
        return None

    def _priority(item: WatchlistItem):
        is_deleted = 1 if getattr(item, "is_deleted", False) else 0
        alert_priority = 0 if getattr(item, "alert_enabled", False) else 1
        timestamp_priority = -_row_timestamp(item)
        id_priority = -(getattr(item, "id", 0) or 0)
        return (is_deleted, alert_priority, timestamp_priority, id_priority)

    preferred = sorted(items, key=_priority)[0]
    if len(items) > 1:
        logger.warning(
            "[WATCHLIST_DUPLICATE] symbol=%s rows=%s chosen_id=%s alert_enabled=%s is_deleted=%s",
            symbol,
            len(items),
            getattr(preferred, "id", None),
            getattr(preferred, "alert_enabled", None),
            getattr(preferred, "is_deleted", None),
        )
    return preferred


def get_canonical_watchlist_item(db: Session, symbol: str) -> Optional[WatchlistItem]:
    """Fetch the canonical watchlist row for the given symbol."""
    symbol_upper = (symbol or "").upper()
    try:
        query = db.query(WatchlistItem).filter(WatchlistItem.symbol == symbol_upper)
        try:
            query = query.order_by(WatchlistItem.id.desc())
        except Exception:
            pass
        items = query.all()
    except Exception as err:
        logger.error("Failed to load watchlist rows for %s: %s", symbol_upper, err, exc_info=True)
        db.rollback()
        return None
    return select_preferred_watchlist_item(items, symbol_upper)


