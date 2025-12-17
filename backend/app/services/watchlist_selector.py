import logging
from collections import OrderedDict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

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


def _watchlist_key(item: WatchlistItem) -> Tuple[str, str]:
    symbol = (getattr(item, "symbol", "") or "").upper()
    exchange = (getattr(item, "exchange", "CRYPTO_COM") or "CRYPTO_COM").upper()
    return symbol, exchange


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


def deduplicate_watchlist_items(items: List[WatchlistItem]) -> List[WatchlistItem]:
    """Collapse duplicate watchlist rows per symbol using canonical selector."""
    canonical_items, _ = partition_watchlist_items(items)
    return canonical_items


def partition_watchlist_items(items: List[WatchlistItem]) -> Tuple[List[WatchlistItem], List[WatchlistItem]]:
    """Split watchlist rows into canonical entries and duplicates (per symbol+exchange)."""
    if not items:
        return [], []

    grouped_items: "OrderedDict[Tuple[str, str], List[WatchlistItem]]" = OrderedDict()
    for item in items:
        symbol, exchange = _watchlist_key(item)
        if not symbol:
            continue
        grouped_items.setdefault((symbol, exchange), []).append(item)

    canonical_items: List[WatchlistItem] = []
    duplicates: List[WatchlistItem] = []
    for (symbol, exchange), symbol_items in grouped_items.items():
        preferred = select_preferred_watchlist_item(symbol_items, symbol)
        if not preferred:
            continue
        canonical_items.append(preferred)
        for candidate in symbol_items:
            if candidate is preferred:
                continue
            duplicates.append(candidate)
            logger.warning(
                "[WATCHLIST_DUPLICATE_DETECTED] symbol=%s exchange=%s duplicate_id=%s canonical_id=%s",
                symbol,
                exchange,
                getattr(candidate, "id", None),
                getattr(preferred, "id", None),
            )

    return canonical_items, duplicates


def cleanup_watchlist_duplicates(
    db: Session,
    *,
    dry_run: bool = False,
    soft_delete: bool = True,
) -> Dict[str, int]:
    """Deduplicate watchlist_items in database by soft-deleting/disabling duplicate rows.

    Args:
        db: Active SQLAlchemy session.
        dry_run: When True, the transaction is rolled back after computing the cleanup.
        soft_delete: When True, duplicates are marked is_deleted=True; otherwise they are hard-deleted.
    Returns:
        Dict summary with scanned, canonical, duplicates counts.
    """
    rows: List[WatchlistItem] = []
    try:
        rows = (
            db.query(WatchlistItem)
            .order_by(WatchlistItem.symbol.asc(), WatchlistItem.exchange.asc(), WatchlistItem.id.desc())
            .all()
        )
    except Exception as err:
        logger.error("Failed to load watchlist_items for cleanup: %s", err, exc_info=True)
        db.rollback()
        raise

    canonical, duplicates = partition_watchlist_items(rows)
    summary = {
        "scanned": len(rows),
        "canonical": len(canonical),
        "duplicates": len(duplicates),
    }

    if not duplicates:
        logger.info("[WATCHLIST_DEDUP] No duplicates found across %s rows", len(rows))
        return summary

    logger.info("[WATCHLIST_DEDUP] Cleaning %s duplicate rows (scanned=%s, canonical=%s)", summary["duplicates"], summary["scanned"], summary["canonical"])

    for dup in duplicates:
        symbol, exchange = _watchlist_key(dup)
        logger.info(
            "[WATCHLIST_DEDUP] Disabling duplicate id=%s symbol=%s exchange=%s alerted=%s trade_enabled=%s",
            getattr(dup, "id", None),
            symbol,
            exchange,
            getattr(dup, "alert_enabled", None),
            getattr(dup, "trade_enabled", None),
        )
        # Disable trading/alerts to avoid accidental execution
        for field in ("alert_enabled", "buy_alert_enabled", "sell_alert_enabled", "trade_enabled", "trade_on_margin"):
            if hasattr(dup, field):
                setattr(dup, field, False)
        if hasattr(dup, "trade_amount_usd"):
            dup.trade_amount_usd = None
        if hasattr(dup, "skip_sl_tp_reminder"):
            dup.skip_sl_tp_reminder = True

        if soft_delete and hasattr(dup, "is_deleted"):
            dup.is_deleted = True
        elif not soft_delete:
            try:
                db.delete(dup)
            except Exception as err:
                logger.warning("Failed to hard delete duplicate %s: %s", getattr(dup, "id", None), err)

    try:
        if dry_run:
            db.rollback()
        else:
            db.commit()
    except Exception as err:
        logger.error("Failed to persist watchlist deduplication changes: %s", err, exc_info=True)
        db.rollback()
        raise

    return summary

