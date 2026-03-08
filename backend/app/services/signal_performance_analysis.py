"""
Analysis-only callback for historical signal-performance review and proposal generation.

Safety:
- reads local project files/data only
- writes markdown artifacts under docs/analysis/
- does not modify production runtime/trading/infrastructure behavior
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.agent_versioning import build_version_summary

logger = logging.getLogger(__name__)

_ELIGIBILITY_KEYWORDS = (
    "signal performance",
    "signal quality",
    "historical signal review",
    "false positive",
    "false negatives",
    "false negative",
    "threshold tuning",
    "volume filter tuning",
    "lookback tuning",
    "trend confirmation tuning",
    "alert precision improvement",
)

_REQUIRED_SECTIONS = (
    "## Title",
    "## Task ID",
    "## Current Version",
    "## Proposed Version",
    "## Signals Analysed",
    "## Data Sources Used",
    "## Methodology",
    "## Historical Performance Summary",
    "## Segment Observations",
    "## Problem Observed",
    "## Proposed Improvement",
    "## Expected Benefit",
    "## Affected Files",
    "## Validation Plan",
    "## Risk Level",
    "## Confidence Score",
)


def _repo_root() -> Path:
    from app.services._paths import workspace_root
    return workspace_root()


def _safe_task_id(prepared_task: dict[str, Any]) -> str:
    task = (prepared_task or {}).get("task") or {}
    return str(task.get("id") or "").strip()


def _safe_task_title(prepared_task: dict[str, Any]) -> str:
    task = (prepared_task or {}).get("task") or {}
    return str(task.get("task") or "").strip()


def _is_eligible(prepared_task: dict[str, Any]) -> bool:
    task = (prepared_task or {}).get("task") or {}
    repo_area = (prepared_task or {}).get("repo_area") or {}
    blob = " ".join(
        [
            str(task.get("task") or ""),
            str(task.get("details") or ""),
            str(task.get("type") or ""),
            str(task.get("project") or ""),
            str(repo_area.get("area_name") or ""),
            " ".join(str(x) for x in (repo_area.get("matched_rules") or [])),
        ]
    ).lower()
    return any(k in blob for k in _ELIGIBILITY_KEYWORDS)


def _read_text_safe(path: Path, max_chars: int = 10000) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
    except Exception:
        return ""


def _markdown_links(text: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", text or "")]


def _line_count(path: Path) -> int:
    if not path.exists() or not path.is_file():
        return 0
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def _sqlite_tables(conn: sqlite3.Connection) -> list[str]:
    try:
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        return [str(r[0]) for r in cur.fetchall()]
    except Exception:
        return []


def _sqlite_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    try:
        cur = conn.execute(f"PRAGMA table_info('{table}')")
        return [str(r[1]) for r in cur.fetchall()]
    except Exception:
        return []


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _to_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    if s in ("true", "yes", "1", "win", "success", "passed"):
        return True
    if s in ("false", "no", "0", "loss", "fail", "failed"):
        return False
    return None


def _compute_quantile_split(values: list[float]) -> float | None:
    if not values:
        return None
    sorted_vals = sorted(values)
    return sorted_vals[len(sorted_vals) // 2]


def _scan_signal_records_from_sqlite(path: Path) -> dict[str, Any]:
    """
    Best-effort extraction from local sqlite files.
    Handles partial schemas; unavailable metrics are reported downstream.
    """
    out = {
        "signals_analysed": 0,
        "success_count": 0,
        "move_after_1h_values": [],
        "move_after_4h_values": [],
        "move_after_24h_values": [],
        "drawdown_values": [],
        "volume_low_total": 0,
        "volume_low_success": 0,
        "volume_high_total": 0,
        "volume_high_success": 0,
        "rsi_low_total": 0,
        "rsi_low_success": 0,
        "rsi_mid_total": 0,
        "rsi_mid_success": 0,
        "rsi_high_total": 0,
        "rsi_high_success": 0,
        "trend_aligned_total": 0,
        "trend_aligned_success": 0,
        "non_trend_total": 0,
        "non_trend_success": 0,
        "lookback_short_total": 0,
        "lookback_short_success": 0,
        "lookback_long_total": 0,
        "lookback_long_success": 0,
        "sources": [],
    }
    if not path.exists():
        return out

    try:
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
    except Exception:
        return out
    try:
        tables = _sqlite_tables(conn)
        signal_tables = [t for t in tables if "signal" in t.lower()]
        for table in signal_tables[:5]:
            cols = _sqlite_columns(conn, table)
            lower_cols = {c.lower(): c for c in cols}
            selectable = cols[:]
            if not selectable:
                continue
            sql = f"SELECT {', '.join([f'\"{c}\"' for c in selectable])} FROM \"{table}\" LIMIT 5000"
            try:
                rows = conn.execute(sql).fetchall()
            except Exception:
                continue
            if not rows:
                continue
            out["sources"].append(f"{path.name}:{table} ({len(rows)} rows)")

            volumes: list[float] = []
            for r in rows:
                for key in ("volume", "quote_volume", "base_volume"):
                    col = lower_cols.get(key)
                    if col:
                        v = _to_float(r[col])
                        if v is not None:
                            volumes.append(v)
                        break
            vol_split = _compute_quantile_split(volumes)

            lookbacks: list[float] = []
            for r in rows:
                for key in ("lookback", "lookback_window", "window"):
                    col = lower_cols.get(key)
                    if col:
                        v = _to_float(r[col])
                        if v is not None:
                            lookbacks.append(v)
                        break
            lookback_split = _compute_quantile_split(lookbacks)

            for row in rows:
                out["signals_analysed"] += 1
                success_flag = None

                for key in ("is_success", "success"):
                    col = lower_cols.get(key)
                    if col:
                        success_flag = _to_bool(row[col])
                        if success_flag is not None:
                            break
                if success_flag is None:
                    for key in ("outcome", "result", "status"):
                        col = lower_cols.get(key)
                        if col:
                            success_flag = _to_bool(row[col])
                            if success_flag is not None:
                                break
                if success_flag is None:
                    for key in ("pnl", "return_pct", "move_after_24h"):
                        col = lower_cols.get(key)
                        if col:
                            v = _to_float(row[col])
                            if v is not None:
                                success_flag = v > 0
                                break

                if success_flag:
                    out["success_count"] += 1

                for key, target in (
                    ("move_after_1h", "move_after_1h_values"),
                    ("move_1h", "move_after_1h_values"),
                    ("move_after_4h", "move_after_4h_values"),
                    ("move_4h", "move_after_4h_values"),
                    ("move_after_24h", "move_after_24h_values"),
                    ("move_24h", "move_after_24h_values"),
                    ("drawdown", "drawdown_values"),
                    ("max_drawdown", "drawdown_values"),
                ):
                    col = lower_cols.get(key)
                    if col:
                        v = _to_float(row[col])
                        if v is not None:
                            out[target].append(v)

                vol_value = None
                for key in ("volume", "quote_volume", "base_volume"):
                    col = lower_cols.get(key)
                    if col:
                        vol_value = _to_float(row[col])
                        if vol_value is not None:
                            break
                if vol_value is not None and vol_split is not None:
                    if vol_value <= vol_split:
                        out["volume_low_total"] += 1
                        if success_flag:
                            out["volume_low_success"] += 1
                    else:
                        out["volume_high_total"] += 1
                        if success_flag:
                            out["volume_high_success"] += 1

                rsi_value = None
                for key in ("rsi", "rsi_value"):
                    col = lower_cols.get(key)
                    if col:
                        rsi_value = _to_float(row[col])
                        if rsi_value is not None:
                            break
                if rsi_value is not None:
                    if rsi_value < 35:
                        out["rsi_low_total"] += 1
                        if success_flag:
                            out["rsi_low_success"] += 1
                    elif rsi_value <= 65:
                        out["rsi_mid_total"] += 1
                        if success_flag:
                            out["rsi_mid_success"] += 1
                    else:
                        out["rsi_high_total"] += 1
                        if success_flag:
                            out["rsi_high_success"] += 1

                trend_value = None
                for key in ("trend_aligned", "is_trend_aligned"):
                    col = lower_cols.get(key)
                    if col:
                        trend_value = _to_bool(row[col])
                        if trend_value is not None:
                            break
                if trend_value is not None:
                    if trend_value:
                        out["trend_aligned_total"] += 1
                        if success_flag:
                            out["trend_aligned_success"] += 1
                    else:
                        out["non_trend_total"] += 1
                        if success_flag:
                            out["non_trend_success"] += 1

                lookback_value = None
                for key in ("lookback", "lookback_window", "window"):
                    col = lower_cols.get(key)
                    if col:
                        lookback_value = _to_float(row[col])
                        if lookback_value is not None:
                            break
                if lookback_value is not None and lookback_split is not None:
                    if lookback_value <= lookback_split:
                        out["lookback_short_total"] += 1
                        if success_flag:
                            out["lookback_short_success"] += 1
                    else:
                        out["lookback_long_total"] += 1
                        if success_flag:
                            out["lookback_long_success"] += 1
    finally:
        conn.close()
    return out


def _scan_local_sources() -> tuple[list[str], dict[str, Any]]:
    root = _repo_root()
    data_sources_used: list[str] = []

    aggregate = {
        "signals_analysed": 0,
        "success_count": 0,
        "move_after_1h_values": [],
        "move_after_4h_values": [],
        "move_after_24h_values": [],
        "drawdown_values": [],
        "volume_low_total": 0,
        "volume_low_success": 0,
        "volume_high_total": 0,
        "volume_high_success": 0,
        "rsi_low_total": 0,
        "rsi_low_success": 0,
        "rsi_mid_total": 0,
        "rsi_mid_success": 0,
        "rsi_high_total": 0,
        "rsi_high_success": 0,
        "trend_aligned_total": 0,
        "trend_aligned_success": 0,
        "non_trend_total": 0,
        "non_trend_success": 0,
        "lookback_short_total": 0,
        "lookback_short_success": 0,
        "lookback_long_total": 0,
        "lookback_long_success": 0,
        "sources": [],
    }

    # Model/service files as known local sources.
    for rel in (
        "backend/app/models/trade_signal.py",
        "backend/app/models/exchange_order.py",
        "backend/app/services/order_history_db.py",
        "backend/app/services/signal_monitor.py",
    ):
        p = root / rel
        if p.exists():
            data_sources_used.append(f"{rel} ({_line_count(p)} lines)")

    runtime_history = root / "runtime-history"
    if runtime_history.exists() and runtime_history.is_dir():
        sample = ", ".join(sorted([x.name for x in runtime_history.iterdir()][:5])) or "(empty)"
        data_sources_used.append(f"runtime-history/ (sample entries: {sample})")

    logs_dir = root / "logs"
    if logs_dir.exists() and logs_dir.is_dir():
        jsonl_files = sorted([p.name for p in logs_dir.glob("*.jsonl")][:8])
        if jsonl_files:
            data_sources_used.append(f"logs/ ({', '.join(jsonl_files)})")

    # SQLite signals extraction if files exist
    sqlite_candidates = [
        root / "order_history.db",
        root / "test_alert_to_buy_flow.db",
    ]
    for db_path in sqlite_candidates:
        stats = _scan_signal_records_from_sqlite(db_path)
        if stats["signals_analysed"] > 0 or stats["sources"]:
            data_sources_used.append(f"{db_path.name} (signal tables found)")
            aggregate["sources"].extend(stats["sources"])
        for key in aggregate.keys():
            if key == "sources":
                continue
            if isinstance(aggregate[key], list):
                aggregate[key].extend(stats.get(key, []))
            elif isinstance(aggregate[key], int):
                aggregate[key] += int(stats.get(key, 0))

    # Include generic file if present, even when no signal rows extracted.
    for rel in ("orders_history.csv", "logs/agent_activity.jsonl"):
        p = root / rel
        if p.exists():
            data_sources_used.append(f"{rel} ({p.stat().st_size} bytes)")

    # De-dup preserve order
    dedup: list[str] = []
    seen: set[str] = set()
    for x in data_sources_used:
        if x in seen:
            continue
        seen.add(x)
        dedup.append(x)
    return dedup, aggregate


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / float(len(values))


def _rate(success: int, total: int) -> float | None:
    if total <= 0:
        return None
    return float(success) / float(total)


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "N/A (data unavailable)"
    return f"{value * 100.0:.2f}%"


def _fmt_num(value: float | None) -> str:
    if value is None:
        return "N/A (data unavailable)"
    return f"{value:.6f}"


def _confidence_score(
    *,
    sample_count: int,
    segment_deltas: list[float],
    has_direct_mapping: bool,
    missing_data_flags: int,
) -> float:
    """
    Rule-based confidence heuristic:
    - more samples => higher confidence
    - stronger segment separation => higher confidence
    - direct mapping from observed issue to proposal => slight boost
    - missing key data => penalty
    """
    score = 0.25
    if sample_count >= 5000:
        score += 0.30
    elif sample_count >= 1000:
        score += 0.24
    elif sample_count >= 200:
        score += 0.16
    elif sample_count >= 50:
        score += 0.10
    elif sample_count > 0:
        score += 0.04

    if segment_deltas:
        strongest = max(segment_deltas)
        if strongest >= 0.20:
            score += 0.18
        elif strongest >= 0.10:
            score += 0.12
        elif strongest >= 0.05:
            score += 0.07
        else:
            score += 0.03

    if has_direct_mapping:
        score += 0.10

    score -= min(0.35, 0.07 * max(0, missing_data_flags))
    return max(0.0, min(1.0, round(score, 3)))


def _ensure_analysis_index(path: Path, task_id: str, title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# Analysis Notes (Agent)\n\n"
        "Analysis-only business-logic proposals generated by agent callbacks.\n"
        "These notes do not modify production logic by themselves.\n\n"
    )
    if not path.exists():
        path.write_text(header, encoding="utf-8")
    line = f"- [Signal performance {task_id}: {title}](signal-performance-{task_id}.md)"
    content = path.read_text(encoding="utf-8", errors="ignore")
    if line not in content:
        with path.open("a", encoding="utf-8") as f:
            if not content.endswith("\n"):
                f.write("\n")
            f.write(line + "\n")


def _risk_level() -> str:
    return "low"


def apply_signal_performance_analysis_task(prepared_task: dict[str, Any]) -> dict[str, Any]:
    try:
        if not _is_eligible(prepared_task):
            return {
                "success": False,
                "summary": "task not eligible for signal performance analysis callback",
            }

        task_id = _safe_task_id(prepared_task)
        title = _safe_task_title(prepared_task) or "Signal performance analysis task"
        if not task_id:
            return {"success": False, "summary": "missing task.id"}

        versioning = build_version_summary(prepared_task, analysis_result={"change_type": "minor"})
        versioning["version_status"] = "proposed"

        data_sources_used, stats = _scan_local_sources()
        signals_analysed = int(stats.get("signals_analysed", 0))
        success_rate = _rate(stats.get("success_count", 0), signals_analysed)

        move_1h = _avg(stats.get("move_after_1h_values", []))
        move_4h = _avg(stats.get("move_after_4h_values", []))
        move_24h = _avg(stats.get("move_after_24h_values", []))
        drawdown = _avg(stats.get("drawdown_values", []))

        vol_low_rate = _rate(stats.get("volume_low_success", 0), stats.get("volume_low_total", 0))
        vol_high_rate = _rate(stats.get("volume_high_success", 0), stats.get("volume_high_total", 0))
        rsi_low_rate = _rate(stats.get("rsi_low_success", 0), stats.get("rsi_low_total", 0))
        rsi_mid_rate = _rate(stats.get("rsi_mid_success", 0), stats.get("rsi_mid_total", 0))
        rsi_high_rate = _rate(stats.get("rsi_high_success", 0), stats.get("rsi_high_total", 0))
        trend_rate = _rate(stats.get("trend_aligned_success", 0), stats.get("trend_aligned_total", 0))
        non_trend_rate = _rate(stats.get("non_trend_success", 0), stats.get("non_trend_total", 0))
        short_lb_rate = _rate(stats.get("lookback_short_success", 0), stats.get("lookback_short_total", 0))
        long_lb_rate = _rate(stats.get("lookback_long_success", 0), stats.get("lookback_long_total", 0))

        segment_deltas: list[float] = []
        for a, b in (
            (vol_low_rate, vol_high_rate),
            (trend_rate, non_trend_rate),
            (short_lb_rate, long_lb_rate),
        ):
            if a is not None and b is not None:
                segment_deltas.append(abs(a - b))
        if rsi_low_rate is not None and rsi_mid_rate is not None:
            segment_deltas.append(abs(rsi_low_rate - rsi_mid_rate))
        if rsi_mid_rate is not None and rsi_high_rate is not None:
            segment_deltas.append(abs(rsi_mid_rate - rsi_high_rate))

        missing_flags = 0
        for val in (move_1h, move_4h, move_24h, drawdown, success_rate):
            if val is None:
                missing_flags += 1
        if not segment_deltas:
            missing_flags += 1
        if signals_analysed == 0:
            missing_flags += 2

        task_blob = (
            str(((prepared_task or {}).get("task") or {}).get("task") or "") + " "
            + str(((prepared_task or {}).get("task") or {}).get("details") or "")
        ).lower()
        direct_mapping = any(
            k in task_blob for k in ("false positive", "false negative", "threshold", "volume", "lookback", "trend")
        )
        confidence = _confidence_score(
            sample_count=signals_analysed,
            segment_deltas=segment_deltas,
            has_direct_mapping=direct_mapping,
            missing_data_flags=missing_flags,
        )

        affected_files = [
            "backend/app/services/signal_monitor.py",
            "backend/app/services/trading_signals.py",
            "backend/app/models/trade_signal.py",
        ]
        # Add sources-derived tables as contextual affected files (doc-level proposal scope).
        for src in (stats.get("sources") or [])[:5]:
            affected_files.append(f"data-source:{src}")

        proposal_points = [
            "Propose threshold adjustments based on underperforming historical segments while keeping core strategy behavior unchanged in this step.",
            "Propose volume-filter refinements when low-volume subsets materially underperform high-volume subsets.",
            "Propose lookback/trend-confirmation tuning when segment separation suggests better precision trade-offs.",
        ]
        validation_plan = [
            "Re-run signal-performance analysis after applying candidate logic in a controlled branch.",
            "Compare success-rate and move distributions for baseline vs tuned proposal cohorts.",
            "Confirm proposed changes remain aligned with business-logic intent documented in docs and runbooks.",
        ]

        versioning["affected_files"] = affected_files
        versioning["validation_plan"] = validation_plan
        if not str(versioning.get("change_summary") or "").strip():
            versioning["change_summary"] = "Signal-performance analysis proposal from historical outcomes."

        perf_lines = [
            f"- Signals analysed: `{signals_analysed}`",
            f"- Success rate: `{_fmt_pct(success_rate)}`",
            f"- Average move after 1h: `{_fmt_num(move_1h)}`",
            f"- Average move after 4h: `{_fmt_num(move_4h)}`",
            f"- Average move after 24h: `{_fmt_num(move_24h)}`",
            f"- Average drawdown after signal: `{_fmt_num(drawdown)}`",
        ]

        segment_lines = [
            f"- Low volume success rate: `{_fmt_pct(vol_low_rate)}` vs high volume: `{_fmt_pct(vol_high_rate)}`",
            f"- RSI buckets success: low `{_fmt_pct(rsi_low_rate)}`, mid `{_fmt_pct(rsi_mid_rate)}`, high `{_fmt_pct(rsi_high_rate)}`",
            f"- Trend aligned success: `{_fmt_pct(trend_rate)}` vs non-trend aligned: `{_fmt_pct(non_trend_rate)}`",
            f"- Short lookback success: `{_fmt_pct(short_lb_rate)}` vs long lookback: `{_fmt_pct(long_lb_rate)}`",
        ]

        methodology_lines = [
            "Use local repository data only: signal-related models/files, runtime-history, logs, and existing sqlite files if available.",
            "Extract signal-like records from sqlite tables containing 'signal' and compute best-effort aggregates.",
            "Compute metrics opportunistically; when fields are unavailable, report explicit data gaps.",
            "Derive confidence score from sample size, segment separation, mapping clarity, and missing-data penalties.",
        ]

        confidence_explain = (
            f"{confidence:.3f} (rule-based: sample coverage + segment separation + task-to-proposal mapping - missing-data penalties)"
        )
        problem_observed = (
            "Historical signal outcomes show uneven or partially measurable quality across segments; additional tuning candidates are identified where separation exists."
            if signals_analysed > 0
            else "Historical signal outcome records were limited/unavailable for full metric computation; proposal focuses on structured measurement improvements and conservative tuning hypotheses."
        )

        root = _repo_root()
        out_dir = root / "docs" / "analysis"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"signal-performance-{task_id}.md"

        content = "\n".join(
            [
                "## Title",
                title,
                "",
                "## Task ID",
                f"`{task_id}`",
                "",
                "## Current Version",
                f"`v{versioning.get('current_version', '0.1.0')}`",
                "",
                "## Proposed Version",
                f"`v{versioning.get('proposed_version', '')}`",
                "",
                "## Signals Analysed",
                str(signals_analysed),
                "",
                "## Data Sources Used",
                *([f"- {x}" for x in data_sources_used] or ["- No local sources found"]),
                "",
                "## Methodology",
                *[f"- {x}" for x in methodology_lines],
                "",
                "## Historical Performance Summary",
                *perf_lines,
                "",
                "## Segment Observations",
                *segment_lines,
                "",
                "## Problem Observed",
                problem_observed,
                "",
                "## Proposed Improvement",
                *[f"- {x}" for x in proposal_points],
                "",
                "## Expected Benefit",
                "Improve alert precision and signal quality by prioritizing parameter changes with stronger historical support while reducing likely false positives/negatives.",
                "",
                "## Affected Files",
                *[f"- `{x}`" for x in affected_files],
                "",
                "## Validation Plan",
                *[f"- {x}" for x in validation_plan],
                "",
                "## Risk Level",
                _risk_level(),
                "",
                "## Confidence Score",
                confidence_explain,
                "",
                f"_Generated at {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}_",
            ]
        ).strip() + "\n"

        out_file.write_text(content, encoding="utf-8")
        _ensure_analysis_index(out_dir / "README.md", task_id, title)

        try:
            from app.services.agent_activity_log import log_agent_event

            log_agent_event(
                "signal_performance_analysis_generated",
                task_id=task_id,
                task_title=title,
                details={
                    "analysis_file": f"docs/analysis/signal-performance-{task_id}.md",
                    "proposed_version": versioning.get("proposed_version", ""),
                    "change_summary": versioning.get("change_summary", ""),
                    "confidence_score": confidence,
                    "signals_analysed": signals_analysed,
                },
            )
        except Exception:
            pass

        return {
            "success": True,
            "summary": f"signal performance analysis generated at docs/analysis/signal-performance-{task_id}.md",
            "analysis_file": f"docs/analysis/signal-performance-{task_id}.md",
            "current_version": versioning.get("current_version", ""),
            "proposed_version": versioning.get("proposed_version", ""),
            "version_status": "proposed",
            "change_summary": versioning.get("change_summary", ""),
            "affected_files": affected_files,
            "validation_plan": validation_plan,
            "risk_level": _risk_level(),
            "confidence_score": confidence,
            "data_sources_used": data_sources_used,
            "signals_analysed": signals_analysed,
        }
    except Exception as e:
        logger.exception("apply_signal_performance_analysis_task failed: %s", e)
        return {"success": False, "summary": str(e)}


def validate_signal_performance_analysis_task(prepared_task: dict[str, Any]) -> dict[str, Any]:
    try:
        task_id = _safe_task_id(prepared_task)
        if not task_id:
            return {"success": False, "summary": "missing task.id"}

        path = _repo_root() / "docs" / "analysis" / f"signal-performance-{task_id}.md"
        if not path.exists():
            return {"success": False, "summary": f"missing analysis file: {path.as_posix()}"}

        content = _read_text_safe(path, max_chars=300000)
        if not content.strip():
            return {"success": False, "summary": "analysis markdown is empty"}

        for marker in _REQUIRED_SECTIONS:
            if marker not in content:
                msg = f"missing required section: {marker}"
                try:
                    from app.services.agent_activity_log import log_agent_event
                    log_agent_event("signal_performance_analysis_validation_failed", task_id=task_id, details={"reason": msg})
                except Exception:
                    pass
                return {"success": False, "summary": msg}

        # At least one data source listed
        data_block = content.split("## Data Sources Used", 1)[1].split("## Methodology", 1)[0]
        data_lines = [ln.strip() for ln in data_block.splitlines() if ln.strip().startswith("- ")]
        if not data_lines:
            msg = "at least one data source must be listed"
            try:
                from app.services.agent_activity_log import log_agent_event
                log_agent_event("signal_performance_analysis_validation_failed", task_id=task_id, details={"reason": msg})
            except Exception:
                pass
            return {"success": False, "summary": msg}

        proposed_block = content.split("## Proposed Improvement", 1)[1].split("## Expected Benefit", 1)[0]
        proposed_lines = [ln.strip() for ln in proposed_block.splitlines() if ln.strip().startswith("- ")]
        if not proposed_lines:
            msg = "at least one concrete proposed improvement is required"
            try:
                from app.services.agent_activity_log import log_agent_event
                log_agent_event("signal_performance_analysis_validation_failed", task_id=task_id, details={"reason": msg})
            except Exception:
                pass
            return {"success": False, "summary": msg}

        affected_block = content.split("## Affected Files", 1)[1].split("## Validation Plan", 1)[0]
        affected_lines = [ln.strip() for ln in affected_block.splitlines() if ln.strip().startswith("- ")]
        if not affected_lines:
            msg = "at least one affected file must be listed"
            try:
                from app.services.agent_activity_log import log_agent_event
                log_agent_event("signal_performance_analysis_validation_failed", task_id=task_id, details={"reason": msg})
            except Exception:
                pass
            return {"success": False, "summary": msg}

        conf_block = content.split("## Confidence Score", 1)[1]
        if not conf_block.strip():
            msg = "confidence score is missing"
            try:
                from app.services.agent_activity_log import log_agent_event
                log_agent_event("signal_performance_analysis_validation_failed", task_id=task_id, details={"reason": msg})
            except Exception:
                pass
            return {"success": False, "summary": msg}

        # Validate relative links
        for link in _markdown_links(content):
            if not link or "://" in link or link.startswith("#"):
                continue
            target_rel = link.split("#", 1)[0].strip()
            if not target_rel:
                continue
            resolved = (path.parent / target_rel).resolve()
            if not resolved.exists():
                msg = f"broken relative markdown link: {link}"
                try:
                    from app.services.agent_activity_log import log_agent_event
                    log_agent_event("signal_performance_analysis_validation_failed", task_id=task_id, details={"reason": msg})
                except Exception:
                    pass
                return {"success": False, "summary": msg}

        return {"success": True, "summary": "signal performance analysis note validated (sections, data sources, confidence, links)"}
    except Exception as e:
        logger.exception("validate_signal_performance_analysis_task failed: %s", e)
        try:
            task_id = _safe_task_id(prepared_task)
            from app.services.agent_activity_log import log_agent_event
            log_agent_event("signal_performance_analysis_validation_failed", task_id=task_id or None, details={"reason": str(e)})
        except Exception:
            pass
        return {"success": False, "summary": str(e)}

