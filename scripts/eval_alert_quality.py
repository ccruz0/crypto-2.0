#!/usr/bin/env python3
"""Offline Phase 1 alert-quality scorecard (M1–M5 / M7).

Reads sent BUY/SELL alerts from DB, HTTP API, or a JSON fixture; re-fetches
public Binance OHLCV for forward labeling; writes markdown + JSON under
docs/analysis/.

Does NOT mutate trading_config, Auto UI, or production runtime.

Usage examples:
  python scripts/eval_alert_quality.py --alerts-json path/to/alerts.json --fixture-candles
  python scripts/eval_alert_quality.py --api-url https://dashboard.hilovivo.com --days 14
  python scripts/eval_alert_quality.py --database-url "$DATABASE_URL" --days 14

See: docs/project-history/alert-quality-eval-phase1-2026-07-22.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

# Repo imports: metrics live beside this script; backend optional for DB.
_SCRIPTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_DIR.parent
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from alert_quality_metrics import (  # noqa: E402
    DEFAULT_DELTA,
    DEFAULT_MFE_HORIZON_MIN,
    Candle,
    label_alert,
    parse_context_json,
    parse_side_from_message,
    parse_strategy_from_message,
    resolve_entry_price,
    rollup_segment,
    strategy_key,
    to_utc_ms,
)

BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
DEFAULT_API_PATH = "/api/monitoring/telegram-messages"


def _repo_root() -> Path:
    return _REPO_ROOT


def to_binance_symbol(symbol: str) -> str:
    sym = (symbol or "").strip().upper()
    if not sym:
        return sym
    if "_" not in sym:
        return f"{sym}USDT"
    if sym.endswith("_USDT"):
        return sym[:-5] + "USDT"
    if sym.endswith("_USD"):
        return sym[:-4] + "USDT"
    return sym.replace("_", "")


def fetch_binance_klines(
    symbol: str,
    *,
    interval: str = "15m",
    start_ms: int,
    end_ms: int,
    limit: int = 1000,
    sleep_s: float = 0.15,
) -> list[Candle]:
    """Public Binance klines for [start_ms, end_ms]. Paginate if needed."""
    bsym = to_binance_symbol(symbol)
    out: list[Candle] = []
    cursor = start_ms
    while cursor < end_ms:
        params = urllib.parse.urlencode(
            {
                "symbol": bsym,
                "interval": interval,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": min(limit, 1000),
            }
        )
        url = f"{BINANCE_KLINES}?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "atp-alert-quality-eval/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")[:200]
            raise RuntimeError(f"Binance HTTP {e.code} for {bsym}: {body}") from e
        except Exception as e:
            raise RuntimeError(f"Binance fetch failed for {bsym}: {e}") from e

        if not data:
            break
        for k in data:
            out.append(
                Candle(
                    t=int(k[0]),
                    o=float(k[1]),
                    h=float(k[2]),
                    l=float(k[3]),
                    c=float(k[4]),
                    v=float(k[5]),
                )
            )
        last_open = int(data[-1][0])
        nxt = last_open + 1
        if nxt <= cursor:
            break
        cursor = nxt
        if len(data) < min(limit, 1000):
            break
        time.sleep(sleep_s)
    # Deduplicate by open time
    by_t = {c.t: c for c in out}
    return [by_t[t] for t in sorted(by_t)]


def load_alerts_from_api(
    api_url: str,
    *,
    days: int,
    token: Optional[str] = None,
    path: str = DEFAULT_API_PATH,
) -> list[dict[str, Any]]:
    base = api_url.rstrip("/")
    url = f"{base}{path}?blocked=false"
    headers = {"User-Agent": "atp-alert-quality-eval/1.0", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    messages = payload.get("messages") if isinstance(payload, dict) else payload
    if not isinstance(messages, list):
        raise RuntimeError("Unexpected API payload for telegram messages")
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if msg.get("blocked") is True:
            continue
        ts = msg.get("timestamp")
        ts_ms = to_utc_ms(ts)
        if ts_ms is None:
            continue
        if datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc) < cutoff:
            continue
        side = parse_side_from_message(str(msg.get("message") or ""))
        if side is None:
            continue
        rows.append(msg)
    return rows


def load_alerts_from_db(database_url: str, *, days: int, limit: int = 2000) -> list[dict[str, Any]]:
    """Read telegram_messages via SQLAlchemy text (no ORM secrets logged)."""
    try:
        from sqlalchemy import create_engine, text
    except ImportError as e:
        raise RuntimeError("sqlalchemy required for --database-url") from e

    # Never print the URL (may contain credentials).
    engine = create_engine(database_url)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    sql = text(
        """
        SELECT id, symbol, message, blocked, order_skipped, timestamp,
               context_json, correlation_id, throttle_reason
        FROM telegram_messages
        WHERE blocked = false
          AND timestamp >= :cutoff
          AND (
            message ILIKE '%BUY SIGNAL%'
            OR message ILIKE '%SELL SIGNAL%'
            OR message LIKE '%🟢%'
            OR message LIKE '%🔴%'
          )
        ORDER BY timestamp DESC
        LIMIT :lim
        """
    )
    # SQLite fallback without ILIKE
    sql_sqlite = text(
        """
        SELECT id, symbol, message, blocked, order_skipped, timestamp,
               context_json, correlation_id, throttle_reason
        FROM telegram_messages
        WHERE blocked = 0
          AND timestamp >= :cutoff
          AND (
            lower(message) LIKE '%buy signal%'
            OR lower(message) LIKE '%sell signal%'
            OR message LIKE '%🟢%'
            OR message LIKE '%🔴%'
          )
        ORDER BY timestamp DESC
        LIMIT :lim
        """
    )
    rows: list[dict[str, Any]] = []
    with engine.connect() as conn:
        dialect = engine.dialect.name
        q = sql_sqlite if dialect == "sqlite" else sql
        result = conn.execute(q, {"cutoff": cutoff, "lim": limit})
        for row in result:
            rows.append(dict(row._mapping))
    return rows


def load_alerts_from_json(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "messages" in data:
        data = data["messages"]
    if not isinstance(data, list):
        raise RuntimeError("--alerts-json must be a list or {messages: [...]}")
    return [m for m in data if isinstance(m, dict)]


def synthetic_candles(
    entry: float,
    entry_ts_ms: int,
    side: str,
    *,
    bars: int = 20,
    step_min: int = 15,
    drift: float = 0.002,
) -> list[Candle]:
    """Deterministic candles for --fixture-candles / unit demos (no network)."""
    out: list[Candle] = []
    price = entry
    sign = 1.0 if side == "BUY" else -1.0
    for i in range(bars):
        t = entry_ts_ms + i * step_min * 60_000
        move = drift * sign
        o = price
        c = price * (1.0 + move)
        h = max(o, c) * (1.0 + abs(drift) * 0.5)
        l = min(o, c) * (1.0 - abs(drift) * 0.5)
        out.append(Candle(t=t, o=o, h=h, l=l, c=c, v=1.0))
        price = c
    return out


def _preset_sl_tp_params(strategy: Optional[str], approach: Optional[str]) -> dict[str, float]:
    """Lightweight defaults mirroring swing-conservative when config absent."""
    key = strategy_key(strategy, approach)
    # scalp → shorter MFE horizon handled by caller; SL/TP defaults:
    if "scalp" in key and "aggressive" in key:
        return {"atr_mult": 0.8, "fallback_pct": 0.02, "rr": 1.0}
    if "scalp" in key:
        return {"atr_mult": 1.0, "fallback_pct": 0.02, "rr": 1.2}
    if "aggressive" in key:
        return {"atr_mult": 1.0, "fallback_pct": 0.025, "rr": 1.2}
    return {"atr_mult": 1.5, "fallback_pct": 0.03, "rr": 1.5}


def normalize_alert(raw: dict[str, Any]) -> Optional[dict[str, Any]]:
    message = str(raw.get("message") or "")
    side = parse_side_from_message(message)
    if side is None:
        return None
    symbol = (raw.get("symbol") or "").strip()
    if not symbol:
        return None
    ctx = parse_context_json(raw.get("context_json"))
    strat, approach = parse_strategy_from_message(message)
    if not strat and ctx.get("strategy_type"):
        strat = str(ctx.get("strategy_type"))
    if not approach and ctx.get("risk_approach"):
        approach = str(ctx.get("risk_approach"))
    if ctx.get("strategy_key"):
        sk = str(ctx["strategy_key"])
    else:
        sk = strategy_key(strat, approach)

    entry = resolve_entry_price(
        message=message,
        context=ctx,
        trade_entry=raw.get("entry_price") or ctx.get("entry_price"),
        fill_price=raw.get("fill_price"),
    )
    ts_ms = to_utc_ms(raw.get("timestamp") or raw.get("entry_ts"))
    if entry is None or ts_ms is None:
        return None

    atr = None
    for key in ("atr", "ATR"):
        if ctx.get(key) is not None:
            try:
                atr = float(ctx[key])
            except (TypeError, ValueError):
                atr = None
            break

    return {
        "id": raw.get("id"),
        "symbol": symbol,
        "side": side,
        "strategy_key": sk,
        "strategy_type": strat,
        "risk_approach": approach,
        "entry_price": entry,
        "entry_ts_ms": ts_ms,
        "atr": atr,
        "correlation_id": raw.get("correlation_id"),
        "message": message,
    }


def evaluate_alerts(
    alerts: list[dict[str, Any]],
    *,
    fixture_candles: bool = False,
    delta: float = DEFAULT_DELTA,
    candle_cache: Optional[dict[str, list[Candle]]] = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cache = candle_cache if candle_cache is not None else {}
    labeled: list[dict[str, Any]] = []
    skipped = 0

    for raw in alerts:
        norm = normalize_alert(raw)
        if norm is None:
            skipped += 1
            continue

        params = _preset_sl_tp_params(norm.get("strategy_type"), norm.get("risk_approach"))
        mfe_h = 60 if "scalp" in norm["strategy_key"] else DEFAULT_MFE_HORIZON_MIN
        end_ms = norm["entry_ts_ms"] + mfe_h * 60_000 + 15 * 60_000
        cache_key = f"{norm['symbol']}|{norm['entry_ts_ms']}|{end_ms}"

        if fixture_candles:
            candles = synthetic_candles(
                norm["entry_price"],
                norm["entry_ts_ms"],
                norm["side"],
            )
            source = "fixture"
        else:
            if cache_key not in cache:
                try:
                    cache[cache_key] = fetch_binance_klines(
                        norm["symbol"],
                        interval="15m",
                        start_ms=norm["entry_ts_ms"],
                        end_ms=end_ms,
                    )
                except Exception as e:
                    labeled.append(
                        {
                            **norm,
                            "error": str(e),
                            "composite_score": None,
                        }
                    )
                    continue
            candles = cache[cache_key]
            source = "binance"

        metrics = label_alert(
            side=norm["side"],
            entry=norm["entry_price"],
            entry_ts_ms=norm["entry_ts_ms"],
            candles=candles,
            atr=norm.get("atr"),
            atr_mult=params["atr_mult"],
            fallback_pct=params["fallback_pct"],
            rr=params["rr"],
            delta=delta,
            mfe_horizon_min=mfe_h,
        )
        labeled.append({**norm, **metrics, "candle_source": source, "n_candles": len(candles)})

    # Segment rollups
    segments: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in labeled:
        if row.get("error"):
            continue
        key = (row["symbol"], row["strategy_key"], row["side"])
        segments[key].append(row)

    rollups = []
    for (sym, sk, side), rows in sorted(segments.items()):
        agg = rollup_segment(rows)
        rollups.append({"symbol": sym, "strategy_key": sk, "side": side, **agg})

    summary = {
        "n_input": len(alerts),
        "n_labeled": sum(1 for r in labeled if not r.get("error")),
        "n_errors": sum(1 for r in labeled if r.get("error")),
        "n_skipped": skipped,
        "segments": rollups,
        "global": _global_summary(labeled, rollups),
    }
    return labeled, summary


def _global_summary(labeled: list[dict[str, Any]], rollups: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [r for r in labeled if not r.get("error") and r.get("composite_score") is not None]
    by_side: dict[str, list[float]] = defaultdict(list)
    for r in ok:
        by_side[r["side"]].append(float(r["composite_score"]))

    def avg(xs: list[float]) -> Optional[float]:
        return sum(xs) / len(xs) if xs else None

    ranked = sorted(
        [s for s in rollups if s.get("mean_composite") is not None],
        key=lambda s: s["mean_composite"],
        reverse=True,
    )
    return {
        "mean_composite": avg([float(r["composite_score"]) for r in ok]),
        "buy_mean_composite": avg(by_side.get("BUY", [])),
        "sell_mean_composite": avg(by_side.get("SELL", [])),
        "top_segments": ranked[:5],
        "bottom_segments": list(reversed(ranked[-5:])) if ranked else [],
    }


def render_markdown(summary: dict[str, Any], labeled: list[dict[str, Any]], *, meta: dict[str, Any]) -> str:
    lines = [
        "# Alert quality scorecard (Phase 1 offline)",
        "",
        f"**Generated:** {meta.get('generated_at')}",
        f"**Source:** {meta.get('source')}",
        f"**Delta (M1):** {meta.get('delta')}",
        f"**Alerts labeled:** {summary.get('n_labeled')} / input {summary.get('n_input')} "
        f"(skipped {summary.get('n_skipped')}, errors {summary.get('n_errors')})",
        "",
        "Metrics: M1 trend hit · M2 direction · M3 MFE/MAE · M4 TP before SL · "
        "M5 expectancy proxy · M7 composite. M6 (alert→fill) not computed here.",
        "",
        "## Global",
        "",
    ]
    g = summary.get("global") or {}
    lines.append(f"- Mean composite (M7): {_fmt_pct_or_num(g.get('mean_composite'))}")
    lines.append(f"- BUY mean composite: {_fmt_pct_or_num(g.get('buy_mean_composite'))}")
    lines.append(f"- SELL mean composite: {_fmt_pct_or_num(g.get('sell_mean_composite'))}")
    lines.append("")
    lines.append("## Segments (symbol × strategy × side)")
    lines.append("")
    lines.append("| Symbol | Strategy | Side | n | dir@1h | trend@4h | TP<SL | med MFE | med MAE | composite | expectancy |")
    lines.append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for s in summary.get("segments") or []:
        rank = "" if s.get("rankable") else "*"
        lines.append(
            "| {symbol} | {strategy_key} | {side} | {n}{rank} | {dir} | {tr} | {tp} | {mfe} | {mae} | {comp} | {exp} |".format(
                symbol=s.get("symbol"),
                strategy_key=s.get("strategy_key"),
                side=s.get("side"),
                n=s.get("n"),
                rank=rank,
                dir=_fmt_rate(s.get("dir_acc_1h")),
                tr=_fmt_rate(s.get("trend_hit_4h")),
                tp=_fmt_rate(s.get("tp_before_sl_rate")),
                mfe=_fmt_pct(s.get("median_mfe")),
                mae=_fmt_pct(s.get("median_mae")),
                comp=_fmt_pct_or_num(s.get("mean_composite")),
                exp=_fmt_pct(s.get("expectancy_proxy")),
            )
        )
    lines.append("")
    lines.append("\\* n < 20 — segment not rankable per Phase 1 design.")
    lines.append("")
    lines.append("## Sample labeled alerts (first 25)")
    lines.append("")
    lines.append("| id | symbol | side | entry | dir@1h | trend@4h | MFE | MAE | TP<SL | M7 |")
    lines.append("|---|---|---|---:|---|---|---:|---:|---|---:|")
    for r in labeled[:25]:
        if r.get("error"):
            continue
        lines.append(
            "| {id} | {symbol} | {side} | {entry:.4f} | {d} | {t} | {mfe} | {mae} | {tp} | {c} |".format(
                id=r.get("id"),
                symbol=r.get("symbol"),
                side=r.get("side"),
                entry=float(r.get("entry_price") or 0),
                d=_fmt_bool(r.get("dir_acc_1h")),
                t=_fmt_bool(r.get("trend_hit_4h")),
                mfe=_fmt_pct(r.get("mfe_pct")),
                mae=_fmt_pct(r.get("mae_pct")),
                tp=_fmt_bool(r.get("tp_before_sl")),
                c=_fmt_pct_or_num(r.get("composite_score")),
            )
        )
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- Offline only; OHLCV re-fetched from public Binance (or fixture).")
    lines.append("- No secrets written; no HostSwapHigh / trading_config / Auto UI changes.")
    lines.append("- Design: `docs/project-history/alert-quality-eval-phase1-2026-07-22.md`")
    lines.append("")
    return "\n".join(lines)


def _fmt_bool(v: Any) -> str:
    if v is None:
        return "—"
    return "Y" if v else "N"


def _fmt_rate(v: Any) -> str:
    if v is None:
        return "—"
    return f"{100.0 * float(v):.1f}%"


def _fmt_pct(v: Any) -> str:
    if v is None:
        return "—"
    return f"{100.0 * float(v):.2f}%"


def _fmt_pct_or_num(v: Any) -> str:
    if v is None:
        return "—"
    return f"{float(v):.3f}"


def write_outputs(
    out_dir: Path,
    summary: dict[str, Any],
    labeled: list[dict[str, Any]],
    *,
    meta: dict[str, Any],
    write_raw: bool,
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    md_path = out_dir / f"alert-quality-scorecard-{stamp}.md"
    json_path = out_dir / f"alert-quality-scorecard-{stamp}.json"
    md_path.write_text(render_markdown(summary, labeled, meta=meta), encoding="utf-8")

    # Strip bulky message bodies from JSON artifact to keep scorecard lean.
    slim_rows = []
    for r in labeled:
        slim = {k: v for k, v in r.items() if k != "message"}
        slim_rows.append(slim)

    payload = {
        "meta": meta,
        "summary": summary,
        "alerts": slim_rows if write_raw else slim_rows[:200],
    }
    json_path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    return md_path, json_path


def build_demo_alerts() -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc) - timedelta(hours=6)
    return [
        {
            "id": 1,
            "symbol": "BTC_USDT",
            "message": "🟢 BUY SIGNAL DETECTED\n📈 Symbol: BTC_USDT\n💵 Price: $65000.0000\n🎯 Strategy: Swing\n⚖️ Approach: Conservative",
            "blocked": False,
            "timestamp": now.isoformat(),
            "context_json": {"entry_price": 65000.0, "atr": 800.0},
        },
        {
            "id": 2,
            "symbol": "ETH_USDT",
            "message": "🔴 SELL SIGNAL DETECTED\n📈 Symbol: ETH_USDT\n💵 Price: $3200.0000\n🎯 Strategy: Swing\n⚖️ Approach: Aggressive",
            "blocked": False,
            "timestamp": (now + timedelta(minutes=5)).isoformat(),
            "context_json": {"price": 3200.0, "atr": 40.0},
        },
    ]


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Offline alert quality scorecard (Phase 1)")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--database-url", default=os.environ.get("DATABASE_URL"), help="Postgres/SQLite URL (never logged)")
    src.add_argument("--api-url", help="Base URL for dashboard API (telegram messages)")
    src.add_argument("--alerts-json", type=Path, help="Local alerts fixture JSON")
    src.add_argument("--demo", action="store_true", help="Built-in tiny demo alerts + fixture candles")
    p.add_argument("--days", type=int, default=14, help="Lookback days for DB/API")
    p.add_argument("--delta", type=float, default=DEFAULT_DELTA, help="M1 trend-hit δ (default 0.005)")
    p.add_argument("--fixture-candles", action="store_true", help="Use synthetic candles (no network)")
    p.add_argument("--out-dir", type=Path, default=_repo_root() / "docs" / "analysis")
    p.add_argument("--write-raw", action="store_true", help="Include all labeled rows in JSON (still no message text)")
    p.add_argument("--api-token", default=os.environ.get("ATP_API_TOKEN"), help="Optional Bearer token (not written to outputs)")
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    fixture = bool(args.fixture_candles or args.demo)
    source = "demo"
    alerts: list[dict[str, Any]]

    if args.demo:
        alerts = build_demo_alerts()
        fixture = True
        source = "demo+fixture"
    elif args.alerts_json:
        alerts = load_alerts_from_json(args.alerts_json)
        source = f"json:{args.alerts_json}"
    elif args.api_url:
        alerts = load_alerts_from_api(args.api_url, days=args.days, token=args.api_token)
        source = f"api:{args.api_url}"
    elif args.database_url:
        alerts = load_alerts_from_db(args.database_url, days=args.days)
        source = "database"
    else:
        print(
            "No alert source. Use --demo, --alerts-json, --api-url, or --database-url / DATABASE_URL.",
            file=sys.stderr,
        )
        return 2

    labeled, summary = evaluate_alerts(
        alerts,
        fixture_candles=fixture,
        delta=args.delta,
    )
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "delta": args.delta,
        "fixture_candles": fixture,
        "phase": "1-offline",
    }
    md_path, json_path = write_outputs(
        args.out_dir,
        summary,
        labeled,
        meta=meta,
        write_raw=args.write_raw,
    )
    print(f"Wrote {md_path}")
    print(f"Wrote {json_path}")
    print(
        f"Labeled {summary['n_labeled']} alerts "
        f"(skipped {summary['n_skipped']}, errors {summary['n_errors']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
