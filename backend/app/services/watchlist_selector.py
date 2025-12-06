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
    """Fetch the canonical watchlist row for the given symbol.
    
    Filters out deleted items to match behavior of watchlist_consistency_check.py
    and other scripts that explicitly filter by is_deleted == False.
    """
    symbol_upper = (symbol or "").upper()
    try:
        query = db.query(WatchlistItem).filter(WatchlistItem.symbol == symbol_upper)
        # Filter out deleted items (consistent with watchlist_consistency_check.py)
        # Note: SQLAlchemy queries are lazy, so we need to catch exceptions during query construction
        # and also during execution (.all()) since column existence is checked at both stages
        try:
            query = query.filter(WatchlistItem.is_deleted == False)
        except Exception:
            # If is_deleted column doesn't exist during query construction, continue without filter
            pass
        try:
            query = query.order_by(WatchlistItem.id.desc())
        except Exception:
            pass
        # Execute query - if is_deleted column doesn't exist, exception may occur here
        try:
            items = query.all()
        except Exception as query_err:
            # If exception occurs during query execution (e.g., column doesn't exist),
            # retry without the is_deleted filter
            logger.debug("Query execution failed, retrying without is_deleted filter: %s", query_err)
            try:
                query = db.query(WatchlistItem).filter(WatchlistItem.symbol == symbol_upper)
                try:
                    query = query.order_by(WatchlistItem.id.desc())
                except Exception:
                    pass
                items = query.all()
            except Exception as retry_err:
                # If retry also fails, log and return empty list to allow graceful degradation
                logger.warning("Retry query also failed for %s: %s", symbol_upper, retry_err)
                items = []
    except Exception as err:
        logger.error("Failed to load watchlist rows for %s: %s", symbol_upper, err, exc_info=True)
        db.rollback()
        return None
    return select_preferred_watchlist_item(items, symbol_upper)



