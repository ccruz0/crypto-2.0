"""Feature extraction + label derivation for Auto ML entry model (offline / runtime).

No I/O, no secrets, no trading_config mutation.
Label (v1): positive if direction hit @ 1h OR TP touched before SL.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from alert_quality_metrics import parse_context_json, to_utc_ms

# Stable feature order — train and inference must match exactly.
FEATURE_NAMES: tuple[str, ...] = (
    "rsi",
    "ma50_dist",
    "ma200_dist",
    "ema10_dist",
    "volume_ratio",
    "atr_pct",
    "strategy_index",
    "side_buy",
    "hour_utc_norm",
)

FEATURE_VERSION = 1


def _f(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        x = float(val)
    except (TypeError, ValueError):
        return default
    if x != x or x in (float("inf"), float("-inf")):  # NaN / inf
        return default
    return x


def _rel_dist(price: float, level: Optional[float]) -> float:
    if price is None or price <= 0 or level is None:
        return 0.0
    try:
        lv = float(level)
    except (TypeError, ValueError):
        return 0.0
    if lv <= 0:
        return 0.0
    return (price - lv) / price


def _ctx_get(ctx: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in ctx and ctx[k] is not None:
            return ctx[k]
        # Nested indicators blob used by some emitters
        ind = ctx.get("indicators")
        if isinstance(ind, dict) and k in ind and ind[k] is not None:
            return ind[k]
    return None


def extract_features(
    *,
    side: str,
    entry_price: float,
    entry_ts_ms: Optional[int] = None,
    context: Optional[dict[str, Any]] = None,
    atr: Optional[float] = None,
) -> dict[str, float]:
    """Build named feature dict from alert-time context + entry."""
    ctx = context or {}
    price = _f(entry_price, 0.0)
    if price <= 0:
        for key in ("price", "current_price", "spot_price"):
            price = _f(_ctx_get(ctx, key), 0.0)
            if price > 0:
                break

    rsi = _f(_ctx_get(ctx, "rsi", "RSI"), 50.0)
    # Clamp RSI to a sane band for the model
    rsi = max(0.0, min(100.0, rsi))

    ma50 = _ctx_get(ctx, "ma50", "MA50")
    ma200 = _ctx_get(ctx, "ma200", "MA200")
    ema10 = _ctx_get(ctx, "ema10", "EMA10")

    vol = _ctx_get(ctx, "volume_ratio", "vol_ratio", "volumeRatio")
    if vol is None:
        cur = _ctx_get(ctx, "current_volume", "volume")
        avg = _ctx_get(ctx, "avg_volume")
        if cur is not None and avg is not None and _f(avg) > 0:
            vol = _f(cur) / _f(avg)
    volume_ratio = _f(vol, 1.0)

    atr_val = atr
    if atr_val is None:
        atr_val = _ctx_get(ctx, "atr", "ATR", "atr14")
    atr_pct = (_f(atr_val) / price) if price > 0 and atr_val is not None else 0.0

    idx = _ctx_get(ctx, "strategy_index", "strategy.index", "index")
    if idx is None and isinstance(ctx.get("strategy"), dict):
        idx = ctx["strategy"].get("index")
    strategy_index = _f(idx, 50.0) / 100.0

    side_u = (side or "").strip().upper()
    side_buy = 1.0 if side_u == "BUY" else 0.0

    hour = 12.0
    if entry_ts_ms is not None:
        try:
            dt = datetime.fromtimestamp(int(entry_ts_ms) / 1000.0, tz=timezone.utc)
            hour = float(dt.hour)
        except (OverflowError, OSError, ValueError):
            hour = 12.0
    hour_utc_norm = hour / 23.0 if hour <= 23 else 1.0

    return {
        "rsi": rsi,
        "ma50_dist": _rel_dist(price, ma50 if ma50 is not None else None),
        "ma200_dist": _rel_dist(price, ma200 if ma200 is not None else None),
        "ema10_dist": _rel_dist(price, ema10 if ema10 is not None else None),
        "volume_ratio": volume_ratio,
        "atr_pct": atr_pct,
        "strategy_index": strategy_index,
        "side_buy": side_buy,
        "hour_utc_norm": hour_utc_norm,
    }


def feature_vector(feats: dict[str, float]) -> list[float]:
    return [float(feats.get(name, 0.0)) for name in FEATURE_NAMES]


def features_from_alert_row(raw: dict[str, Any], *, normalized: Optional[dict[str, Any]] = None) -> dict[str, float]:
    """Extract features from a raw telegram_messages-like row and/or normalize_alert output."""
    ctx = parse_context_json(raw.get("context_json"))
    if normalized:
        side = str(normalized.get("side") or "BUY")
        entry = float(normalized.get("entry_price") or 0.0)
        ts = normalized.get("entry_ts_ms")
        atr = normalized.get("atr")
        # Prefer richer context still on the raw row
        return extract_features(
            side=side,
            entry_price=entry,
            entry_ts_ms=int(ts) if ts is not None else to_utc_ms(raw.get("timestamp")),
            context=ctx,
            atr=float(atr) if atr is not None else None,
        )
    side = str(raw.get("side") or "BUY")
    entry = _f(raw.get("entry_price") or ctx.get("entry_price") or ctx.get("price"))
    atr_raw = raw.get("atr")
    atr_val: Optional[float] = None
    if atr_raw is not None:
        atr_val = _f(atr_raw)
    return extract_features(
        side=side,
        entry_price=entry,
        entry_ts_ms=to_utc_ms(raw.get("timestamp") or raw.get("entry_ts")),
        context=ctx,
        atr=atr_val,
    )


def derive_label(labeled_row: dict[str, Any]) -> Optional[int]:
    """Binary label from Phase-1 metrics.

    1 = good entry (dir hit @ 1h OR TP before SL)
    0 = poor entry (dir miss @ 1h and not TP-before-SL)
    None = cannot label yet (missing forward path)
    """
    if labeled_row.get("error"):
        return None
    dir_1h = labeled_row.get("dir_acc_1h")
    tp_sl = labeled_row.get("tp_before_sl")
    if dir_1h is None and tp_sl is None:
        return None
    if dir_1h is True or tp_sl is True:
        return 1
    # Explicit miss: direction false, and TP-before-SL is False or unknown
    if dir_1h is False:
        return 0
    # Only tp_before_sl known and False
    if tp_sl is False:
        return 0
    return None


def attach_features_and_label(
    labeled_rows: Sequence[dict[str, Any]],
    raw_by_id: Optional[dict[Any, dict[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """Return dataset rows with features, x vector, and y (drops unlabeled)."""
    out: list[dict[str, Any]] = []
    for row in labeled_rows:
        y = derive_label(row)
        if y is None:
            continue
        raw = None
        if raw_by_id is not None and row.get("id") is not None:
            raw = raw_by_id.get(row["id"])
        if raw is None:
            # Reconstruct minimal raw from labeled fields
            raw = {
                "id": row.get("id"),
                "timestamp": row.get("entry_ts_ms"),
                "context_json": row.get("context_json") or {},
                "side": row.get("side"),
                "entry_price": row.get("entry_price"),
                "atr": row.get("atr"),
            }
        feats = features_from_alert_row(raw, normalized=row)
        out.append(
            {
                "id": row.get("id"),
                "symbol": row.get("symbol"),
                "side": row.get("side"),
                "strategy_key": row.get("strategy_key"),
                "entry_price": row.get("entry_price"),
                "entry_ts_ms": row.get("entry_ts_ms"),
                "dir_acc_1h": row.get("dir_acc_1h"),
                "tp_before_sl": row.get("tp_before_sl"),
                "composite_score": row.get("composite_score"),
                "features": feats,
                "x": feature_vector(feats),
                "y": y,
                "label_source": "alert",
                "feature_version": FEATURE_VERSION,
            }
        )
    return out


TRADE_OUTCOME_LABEL_DEF = (
    "y=1 if round-trip pnl_usd > 0 else 0 (COMPLETE trade_outcomes with alert)"
)


def features_look_default(feats: dict[str, float]) -> bool:
    """True when context was empty enough that features are uninformative defaults."""
    return (
        abs(feats.get("rsi", 50.0) - 50.0) < 1e-9
        and abs(feats.get("ma50_dist", 0.0)) < 1e-12
        and abs(feats.get("ma200_dist", 0.0)) < 1e-12
        and abs(feats.get("ema10_dist", 0.0)) < 1e-12
        and abs(feats.get("atr_pct", 0.0)) < 1e-12
    )


def _symbol_base(symbol: Any) -> str:
    s = str(symbol or "").strip().upper()
    for suf in ("_USDT", "_USD", "USDT", "USD"):
        if s.endswith(suf) and len(s) > len(suf):
            return s[: -len(suf)]
    return s


def _context_has_indicator_keys(ctx: dict[str, Any]) -> bool:
    if not ctx:
        return False
    for key in ("rsi", "RSI", "ma50", "MA50", "ma200", "MA200", "ema10", "EMA10", "atr", "ATR"):
        if _ctx_get(ctx, key) is not None:
            return True
    return False


def enrich_outcomes_with_nearest_signal_context(
    outcomes: Sequence[dict[str, Any]],
    signal_alerts: Sequence[dict[str, Any]],
    *,
    max_skew_seconds: int = 6 * 3600,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Copy indicator context from the nearest prior SIGNAL alert (same symbol).

    Fill-linked telegram rows often store only ``{symbol, order_id, ...}``. Prefer a
    SIGNAL alert with the same base symbol whose timestamp is at or before entry,
    within ``max_skew_seconds``.
    """
    by_base: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for alert in signal_alerts:
        ctx = parse_context_json(alert.get("context_json"))
        if not _context_has_indicator_keys(ctx):
            continue
        ts_ms = to_utc_ms(alert.get("timestamp") or alert.get("entry_ts_ms"))
        if ts_ms is None:
            continue
        base = _symbol_base(alert.get("symbol"))
        if not base:
            continue
        by_base.setdefault(base, []).append((int(ts_ms), alert))
    for base in by_base:
        by_base[base].sort(key=lambda x: x[0])

    stats = {"checked": 0, "already_rich": 0, "enriched": 0, "no_match": 0}
    out: list[dict[str, Any]] = []
    for oc in outcomes:
        item = dict(oc)
        stats["checked"] += 1
        ctx = parse_context_json(item.get("context_json"))
        if _context_has_indicator_keys(ctx):
            stats["already_rich"] += 1
            out.append(item)
            continue
        entry_ts = item.get("entry_ts") or item.get("alert_timestamp") or item.get("timestamp")
        entry_ms = to_utc_ms(entry_ts)
        base = _symbol_base(item.get("symbol"))
        if entry_ms is None or not base or base not in by_base:
            stats["no_match"] += 1
            out.append(item)
            continue
        best: Optional[tuple[int, dict[str, Any]]] = None
        for ts_ms, alert in by_base[base]:
            if ts_ms > int(entry_ms):
                break
            skew = int(entry_ms) - ts_ms
            if skew > max_skew_seconds * 1000:
                continue
            # Prefer later (closer) prior SIGNAL
            if best is None or ts_ms >= best[0]:
                best = (ts_ms, alert)
        if best is None:
            stats["no_match"] += 1
            out.append(item)
            continue
        donor = best[1]
        donor_ctx = parse_context_json(donor.get("context_json"))
        # Keep order ids if present; overlay indicator keys from SIGNAL.
        merged = dict(ctx)
        merged.update(donor_ctx)
        item["context_json"] = merged
        item["signal_context_telegram_id"] = donor.get("id")
        item["signal_context_skew_ms"] = int(entry_ms) - best[0]
        stats["enriched"] += 1
        out.append(item)
    return out, stats


def attach_features_from_trade_outcomes(
    outcomes: Sequence[dict[str, Any]],
    *,
    drop_degraded_features: bool = True,
    feature_fallback_by_id: Optional[dict[Any, dict[str, Any]]] = None,
    keep_degraded: bool = False,
) -> tuple[list[dict[str, Any]], set[Any]]:
    """Build ML rows from Phase 1a COMPLETE outcomes joined to alert context.

    Expects each outcome dict to include:
      label, side, entry_price, entry_ts (or entry_ts_ms), symbol,
      telegram_message_id, context_json (from telegram_messages),
      optional exit_reason / pnl_usd / entry_exchange_order_id.

    When fill-linked ``context_json`` is empty, features look like defaults
    (RSI=50, zero distances). Options:
      - ``feature_fallback_by_id``: reuse features from an alert-path row
        (same telegram id) so hybrid can keep fill labels with the same
        feature vector the Phase-0 path already used.
      - ``keep_degraded``: if still degraded (and no usable fallback), emit
        the fill row anyway (hybrid prefers realized PnL labels over dropping).

    Returns (rows, suppress_alert_ids). ``suppress_alert_ids`` are telegram
    message ids that had a COMPLETE outcome but were dropped (e.g. degraded
    features) — hybrid must not keep Phase 0 labels for those alerts.
    """
    out: list[dict[str, Any]] = []
    suppress_alert_ids: set[Any] = set()
    fallback = feature_fallback_by_id or {}
    for oc in outcomes:
        tid = oc.get("telegram_message_id")
        if tid is None:
            continue
        label = oc.get("label")
        if label is None:
            continue
        try:
            y = int(label)
        except (TypeError, ValueError):
            continue
        if y not in (0, 1):
            continue

        entry_ts = oc.get("entry_ts") or oc.get("entry_ts_ms") or oc.get("timestamp")
        entry_ts_ms = to_utc_ms(entry_ts)
        side = str(oc.get("side") or "BUY").upper()
        entry_price = _f(oc.get("entry_price"))
        raw = {
            "id": tid,
            "timestamp": entry_ts,
            "context_json": oc.get("context_json") or {},
            "side": side,
            "entry_price": entry_price,
        }
        normalized = {
            "side": side,
            "entry_price": entry_price,
            "entry_ts_ms": entry_ts_ms,
        }
        feats = features_from_alert_row(raw, normalized=normalized)
        x = feature_vector(feats)
        if drop_degraded_features and features_look_default(feats):
            fb = fallback.get(tid)
            fb_feats = fb.get("features") if isinstance(fb, dict) else None
            fb_x = fb.get("x") if isinstance(fb, dict) else None
            if isinstance(fb_feats, dict) and isinstance(fb_x, list) and fb_x:
                feats = dict(fb_feats)
                x = list(fb_x)
            elif keep_degraded:
                pass  # emit fill label with default features
            else:
                suppress_alert_ids.add(tid)
                continue
        out.append(
            {
                "id": tid,
                "symbol": oc.get("symbol"),
                "side": side,
                "strategy_key": oc.get("strategy_key") or "auto",
                "entry_price": entry_price,
                "entry_ts_ms": entry_ts_ms,
                "exit_reason": oc.get("exit_reason"),
                "pnl_usd": oc.get("pnl_usd"),
                "entry_exchange_order_id": oc.get("entry_exchange_order_id"),
                "features": feats,
                "x": x,
                "y": y,
                "label_source": "trade_outcome",
                "feature_version": FEATURE_VERSION,
            }
        )
    return out, suppress_alert_ids


def merge_alert_and_trade_datasets(
    alert_rows: Sequence[dict[str, Any]],
    trade_rows: Sequence[dict[str, Any]],
    *,
    suppress_alert_ids: Optional[set[Any]] = None,
) -> list[dict[str, Any]]:
    """Emit all fill rows (keyed by entry order), then alert rows without fills.

    Multiple COMPLETE outcomes per alert are kept as separate training rows
    (unique ``entry_exchange_order_id``). Alert-path labels are suppressed for
    any telegram id that has a fill row or is in ``suppress_alert_ids``.
    """
    suppress: set[Any] = set(suppress_alert_ids or ())
    ordered: list[dict[str, Any]] = []
    seen_entry: set[Any] = set()
    for row in trade_rows:
        eid = row.get("entry_exchange_order_id") or f"tid:{row.get('id')}"
        if eid in seen_entry:
            continue
        seen_entry.add(eid)
        item = dict(row)
        item["label_source"] = "trade_outcome"
        ordered.append(item)
        if row.get("id") is not None:
            suppress.add(row["id"])
    for row in alert_rows:
        rid = row.get("id")
        if rid is None or rid in suppress:
            continue
        item = dict(row)
        item["label_source"] = row.get("label_source") or "alert"
        ordered.append(item)
    return ordered
