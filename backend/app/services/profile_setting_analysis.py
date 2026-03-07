"""
Analysis-only callback for profile-based setting improvement proposals.

Focus:
- symbol-level settings
- profile/preset-level tuning
- side-specific (buy/sell) setting proposals

Safety:
- local data sources only
- writes markdown under docs/analysis/
- no production code/runtime/execution modifications
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.agent_versioning import build_version_summary

logger = logging.getLogger(__name__)

_ELIGIBILITY_KEYWORDS = (
    "per-coin settings",
    "per coin settings",
    "profile tuning",
    "conservative optimization",
    "aggressive optimization",
    "scalp optimization",
    "intraday optimization",
    "buy setting tuning",
    "sell setting tuning",
    "per-symbol parameter tuning",
    "per symbol parameter tuning",
    "preset optimization",
    "profile-based false positives",
    "profile-based false negatives",
    "profile-based signal quality",
    "profile setting",
    "settings profile",
)

_REQUIRED_SECTIONS = (
    "## Title",
    "## Task ID",
    "## Symbol",
    "## Profile",
    "## Side",
    "## Current Version",
    "## Proposed Version",
    "## Current Settings",
    "## Historical Results Summary",
    "## Business Logic Intent",
    "## Current Implementation Summary",
    "## Problem Observed",
    "## Proposed Setting Changes",
    "## Expected Benefit",
    "## Affected Files",
    "## Validation Plan",
    "## Risk Level",
    "## Confidence Score",
)

_PROFILE_SYNONYMS: dict[str, tuple[str, ...]] = {
    "conservative": ("conservative",),
    "aggressive": ("aggressive",),
    "scalp": ("scalp",),
    "intraday": ("intraday", "intra-day"),
    "swing": ("swing",),
}

_SIDE_SYNONYMS: dict[str, tuple[str, ...]] = {
    "buy": ("buy", "entry"),
    "sell": ("sell", "exit"),
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _safe_task_id(prepared_task: dict[str, Any]) -> str:
    task = (prepared_task or {}).get("task") or {}
    return str(task.get("id") or "").strip()


def _safe_task_title(prepared_task: dict[str, Any]) -> str:
    task = (prepared_task or {}).get("task") or {}
    return str(task.get("task") or "").strip()


def _blob(prepared_task: dict[str, Any]) -> str:
    task = (prepared_task or {}).get("task") or {}
    repo_area = (prepared_task or {}).get("repo_area") or {}
    return " ".join(
        [
            str(task.get("task") or ""),
            str(task.get("details") or ""),
            str(task.get("type") or ""),
            str(task.get("project") or ""),
            str(repo_area.get("area_name") or ""),
            " ".join(str(x) for x in (repo_area.get("matched_rules") or [])),
        ]
    ).lower()


def _is_eligible(prepared_task: dict[str, Any]) -> bool:
    text = _blob(prepared_task)
    return any(k in text for k in _ELIGIBILITY_KEYWORDS)


def _read_text(path: Path, max_chars: int = 15000) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
    except Exception:
        return ""


def _line_count(path: Path) -> int:
    if not path.exists() or not path.is_file():
        return 0
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def _markdown_links(text: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", text or "")]


def _extract_symbol(text: str) -> tuple[str, bool]:
    # First priority: explicit symbol pair like BTC_USDT / BTC_USD.
    m_pair = re.search(r"\b([A-Z]{2,12}_(?:USDT|USD|USDC|BTC|ETH))\b", text or "")
    if m_pair:
        return m_pair.group(1), True

    # Fallback: standalone token symbol mention.
    candidates = ("BTC", "ETH", "SOL", "DOT", "ADA", "XRP", "DOGE", "LDO", "AVAX", "MATIC", "NEAR", "LINK")
    upper = (text or "").upper()
    for c in candidates:
        if re.search(rf"\b{re.escape(c)}\b", upper):
            return c, False
    return "unknown (uncertain)", False


def _extract_profile(text: str) -> tuple[str, bool]:
    lower = (text or "").lower()
    for canonical, synonyms in _PROFILE_SYNONYMS.items():
        if any(s in lower for s in synonyms):
            return canonical, True
    return "unknown (uncertain)", False


def _extract_side(text: str) -> tuple[str, bool]:
    lower = (text or "").lower()
    for canonical, synonyms in _SIDE_SYNONYMS.items():
        if any(re.search(rf"\b{re.escape(s)}\b", lower) for s in synonyms):
            return canonical, True
    return "unknown (uncertain)", False


def _infer_targets(prepared_task: dict[str, Any]) -> dict[str, Any]:
    text = _blob(prepared_task)
    symbol, symbol_conf = _extract_symbol(text)
    profile, profile_conf = _extract_profile(text)
    side, side_conf = _extract_side(text)
    return {
        "symbol": symbol,
        "profile": profile,
        "side": side,
        "symbol_confident": symbol_conf,
        "profile_confident": profile_conf,
        "side_confident": side_conf,
    }


def profile_setting_preview_metadata(prepared_task: dict[str, Any]) -> dict[str, Any] | None:
    """
    Lightweight metadata for callback selection / approval summary.
    """
    if not _is_eligible(prepared_task):
        return None
    return _infer_targets(prepared_task)


def _get_current_settings(symbol: str, profile: str) -> tuple[dict[str, Any], list[str]]:
    """
    Read current settings from existing config helpers only.
    """
    data_sources: list[str] = []
    settings: dict[str, Any] = {}
    try:
        from app.services.config_loader import get_strategy_rules, load_config

        cfg = load_config()
        data_sources.append("backend/app/services/config_loader.py")
        data_sources.append("backend/trading_config.json via config_loader")

        # Map profile to strategy preset key where possible.
        preset_name = profile if profile in ("swing", "intraday", "scalp") else "swing"
        risk_mode = "Conservative" if profile in ("conservative", "unknown (uncertain)") else "Aggressive"
        rules = get_strategy_rules(preset_name=preset_name, risk_mode=risk_mode)
        if isinstance(rules, dict):
            settings.update(
                {
                    "preset_name": preset_name,
                    "risk_mode": risk_mode,
                    "rsi_buy": ((rules.get("rsi") or {}).get("buyBelow")),
                    "rsi_sell": ((rules.get("rsi") or {}).get("sellAbove")),
                    "volume_min_ratio": rules.get("volumeMinRatio"),
                    "min_price_change_pct": rules.get("minPriceChangePct"),
                    "alert_cooldown_minutes": rules.get("alertCooldownMinutes"),
                }
            )

        # Per-symbol overrides if present
        if symbol and symbol != "unknown (uncertain)" and "_" in symbol:
            coins_cfg = (cfg.get("coins") or {})
            coin_cfg = coins_cfg.get(symbol) or {}
            overrides = coin_cfg.get("overrides") or {}
            if overrides:
                settings["symbol_overrides"] = overrides
    except Exception as e:
        logger.debug("profile_setting_analysis: settings load failed: %s", e)
    return settings, data_sources


def _scan_historical(symbol: str, profile: str, side: str) -> tuple[dict[str, Any], list[str]]:
    """
    Best-effort local historical summary from sqlite/log artifacts.
    """
    root = _repo_root()
    result = {
        "rows": 0,
        "closed_like": 0,
        "open_like": 0,
        "success_like": 0,
        "notes": [],
    }
    sources: list[str] = []

    # Static project sources
    for rel in (
        "backend/app/models/trade_signal.py",
        "backend/app/services/strategy_profiles.py",
        "backend/app/services/signal_monitor.py",
        "backend/app/services/config_loader.py",
    ):
        p = root / rel
        if p.exists():
            sources.append(f"{rel} ({_line_count(p)} lines)")

    runtime_hist = root / "runtime-history"
    if runtime_hist.exists() and runtime_hist.is_dir():
        sample = ", ".join(sorted([x.name for x in runtime_hist.iterdir()][:5])) or "(empty)"
        sources.append(f"runtime-history/ (sample entries: {sample})")

    logs_dir = root / "logs"
    if logs_dir.exists() and logs_dir.is_dir():
        jsonl = sorted([p.name for p in logs_dir.glob("*.jsonl")][:8])
        if jsonl:
            sources.append(f"logs/ ({', '.join(jsonl)})")

    db_paths = [root / "order_history.db", root / "test_alert_to_buy_flow.db"]
    for db_path in db_paths:
        if not db_path.exists():
            continue
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            signal_tables = [t for t in tables if "signal" in str(t).lower()]
            if signal_tables:
                sources.append(f"{db_path.name} (tables: {', '.join(signal_tables[:3])})")
            for table in signal_tables[:4]:
                cols = [r[1] for r in conn.execute(f"PRAGMA table_info('{table}')").fetchall()]
                if not cols:
                    continue
                select_cols = ", ".join([f'"{c}"' for c in cols[:40]])
                rows = conn.execute(f'SELECT {select_cols} FROM "{table}" LIMIT 5000').fetchall()
                if not rows:
                    continue
                for row in rows:
                    row_map = {str(c).lower(): row[c] for c in cols if c in row.keys()}
                    # Symbol filter when available
                    if symbol != "unknown (uncertain)":
                        row_symbol = str(row_map.get("symbol") or row_map.get("pair") or "").upper()
                        if row_symbol and "_" in symbol and row_symbol != symbol:
                            continue
                    # Profile filter when available
                    if profile != "unknown (uncertain)":
                        row_profile = str(row_map.get("sl_profile") or row_map.get("risk_profile") or row_map.get("profile") or "").lower()
                        row_preset = str(row_map.get("preset") or "").lower()
                        if row_profile and profile in ("conservative", "aggressive") and row_profile != profile:
                            continue
                        if row_preset and profile in ("swing", "intraday", "scalp") and row_preset != profile:
                            continue
                    # Side filter when available
                    if side != "unknown (uncertain)":
                        row_side = str(row_map.get("side") or row_map.get("signal_side") or row_map.get("action") or "").lower()
                        if row_side and row_side != side:
                            continue

                    result["rows"] += 1
                    status = str(row_map.get("status") or row_map.get("outcome") or "").lower()
                    if status in ("closed", "filled", "archived", "done"):
                        result["closed_like"] += 1
                    if status in ("pending", "order_placed", "open", "active"):
                        result["open_like"] += 1
                    if status in ("filled", "closed", "success", "win"):
                        result["success_like"] += 1

            conn.close()
        except Exception as e:
            result["notes"].append(f"SQLite read issue in {db_path.name}: {e}")

    # De-dup sources
    dedup: list[str] = []
    seen: set[str] = set()
    for s in sources:
        if s in seen:
            continue
        seen.add(s)
        dedup.append(s)
    return result, dedup


def _build_proposed_setting_changes(
    *,
    side: str,
    settings: dict[str, Any],
    hist: dict[str, Any],
) -> tuple[list[str], bool]:
    """
    Return (proposal_lines, has_numeric_proposal).
    Numeric proposals are only produced when minimally justified.
    """
    proposals: list[str] = []
    has_numeric = False
    rows = int(hist.get("rows") or 0)

    rsi_buy = settings.get("rsi_buy")
    rsi_sell = settings.get("rsi_sell")
    volume_min_ratio = settings.get("volume_min_ratio")
    min_change = settings.get("min_price_change_pct")

    if rows >= 80:
        # We have enough rough historical support to propose conservative numeric nudges.
        if side in ("buy", "unknown (uncertain)") and isinstance(rsi_buy, (int, float)):
            new_val = max(5, int(round(float(rsi_buy) - 2)))
            proposals.append(f"RSI entry threshold: {rsi_buy} -> {new_val}")
            has_numeric = True
        if side in ("sell", "unknown (uncertain)") and isinstance(rsi_sell, (int, float)):
            new_val = min(95, int(round(float(rsi_sell) + 2)))
            proposals.append(f"Exit RSI threshold: {rsi_sell} -> {new_val}")
            has_numeric = True
        if isinstance(volume_min_ratio, (int, float)):
            new_val = round(float(volume_min_ratio) + 0.2, 2)
            proposals.append(f"Volume multiplier: {volume_min_ratio} -> {new_val}")
            has_numeric = True
        if isinstance(min_change, (int, float)):
            new_val = round(float(min_change) + 0.5, 2)
            proposals.append(f"Min price-change threshold: {min_change} -> {new_val}")
            has_numeric = True
    else:
        proposals.append(
            "No safe numeric proposal is made because historical sample coverage is insufficient for symbol/profile/side-specific tuning."
        )
        proposals.append(
            "Collect additional outcome-labeled signal records for this target and re-run analysis before applying numeric setting changes."
        )

    return proposals, has_numeric


def _confidence_score(
    *,
    historical_rows: int,
    mapping_clarity: int,
    has_pattern: bool,
    has_direct_proposal: bool,
    missing_data_flags: int,
) -> float:
    """
    Transparent heuristic:
    - historical sample coverage
    - symbol/profile/side mapping clarity
    - observed pattern strength proxy
    - directness of proposal
    - penalties for missing data
    """
    score = 0.20
    if historical_rows >= 1000:
        score += 0.30
    elif historical_rows >= 300:
        score += 0.22
    elif historical_rows >= 80:
        score += 0.14
    elif historical_rows > 0:
        score += 0.06

    # mapping_clarity: 0..3
    score += 0.08 * max(0, min(3, mapping_clarity))

    if has_pattern:
        score += 0.10
    if has_direct_proposal:
        score += 0.10

    score -= min(0.30, 0.06 * max(0, missing_data_flags))
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
    entry = f"- [Profile settings {task_id}: {title}](profile-settings-{task_id}.md)"
    content = _read_text(path)
    if entry not in content:
        with path.open("a", encoding="utf-8") as f:
            if not content.endswith("\n"):
                f.write("\n")
            f.write(entry + "\n")


def apply_profile_setting_analysis_task(prepared_task: dict) -> dict:
    try:
        if not _is_eligible(prepared_task):
            return {"success": False, "summary": "task not eligible for profile setting analysis callback"}

        task_id = _safe_task_id(prepared_task)
        title = _safe_task_title(prepared_task) or "Profile setting analysis task"
        if not task_id:
            return {"success": False, "summary": "missing task.id"}

        targets = _infer_targets(prepared_task)
        symbol = targets["symbol"]
        profile = targets["profile"]
        side = targets["side"]

        settings, settings_sources = _get_current_settings(symbol, profile)
        historical, historical_sources = _scan_historical(symbol, profile, side)

        # Business intent sources
        root = _repo_root()
        intent_docs = []
        for rel in (
            "docs/agents/task-system.md",
            "docs/monitoring/business_rules_canonical.md",
            "docs/architecture/system-overview.md",
        ):
            p = root / rel
            if p.exists():
                intent_docs.append(rel)

        data_sources_used = []
        for src in (settings_sources + historical_sources + intent_docs):
            if src not in data_sources_used:
                data_sources_used.append(src)

        proposed_changes, has_numeric = _build_proposed_setting_changes(
            side=side,
            settings=settings,
            hist=historical,
        )

        rows = int(historical.get("rows") or 0)
        closed_like = int(historical.get("closed_like") or 0)
        success_like = int(historical.get("success_like") or 0)
        success_rate = (float(success_like) / float(closed_like)) if closed_like > 0 else None

        mapping_clarity = int(targets["symbol_confident"]) + int(targets["profile_confident"]) + int(targets["side_confident"])
        has_pattern = bool(rows >= 80 and closed_like > 20)
        missing_flags = 0
        if rows == 0:
            missing_flags += 2
        if symbol.startswith("unknown"):
            missing_flags += 1
        if profile.startswith("unknown"):
            missing_flags += 1
        if side.startswith("unknown"):
            missing_flags += 1
        if not settings:
            missing_flags += 1
        confidence = _confidence_score(
            historical_rows=rows,
            mapping_clarity=mapping_clarity,
            has_pattern=has_pattern,
            has_direct_proposal=has_numeric,
            missing_data_flags=missing_flags,
        )

        versioning = build_version_summary(prepared_task, analysis_result={"change_type": "minor"})
        versioning["version_status"] = "proposed"
        versioning["confidence_score"] = confidence
        if not str(versioning.get("change_summary") or "").strip():
            versioning["change_summary"] = (
                f"Profile-setting proposal for symbol={symbol}, profile={profile}, side={side}."
            )

        affected_files = [
            "backend/app/services/config_loader.py",
            "backend/app/services/strategy_profiles.py",
            "backend/app/services/signal_monitor.py",
        ]
        validation_plan = [
            "Compare baseline vs proposed settings for target symbol/profile/side over equivalent historical windows.",
            "Check false-positive/false-negative deltas and alert precision changes before any patching stage.",
            "Validate setting proposal consistency with strategy_rules and business-rule documentation.",
        ]

        # Persist for approval summary visibility.
        prepared_task.setdefault("versioning", {})
        prepared_task["versioning"].update(
            {
                "current_version": versioning.get("current_version", ""),
                "proposed_version": versioning.get("proposed_version", ""),
                "version_status": "proposed",
                "change_summary": versioning.get("change_summary", ""),
                "confidence_score": confidence,
                "symbol": symbol,
                "profile": profile,
                "side": side,
            }
        )
        task_obj = prepared_task.get("task") or {}
        task_obj["symbol"] = symbol
        task_obj["profile"] = profile
        task_obj["side"] = side
        task_obj["confidence_score"] = confidence

        lines = [
            "## Title",
            title,
            "",
            "## Task ID",
            f"`{task_id}`",
            "",
            "## Symbol",
            symbol,
            "",
            "## Profile",
            profile,
            "",
            "## Side",
            side,
            "",
            "## Current Version",
            f"`v{versioning.get('current_version', '')}`",
            "",
            "## Proposed Version",
            f"`v{versioning.get('proposed_version', '')}`",
            "",
            "## Current Settings",
        ]
        if settings:
            for k, v in settings.items():
                lines.append(f"- {k}: `{v}`")
        else:
            lines.append("- Current settings could not be resolved confidently from available config sources.")

        lines.extend(
            [
                "",
                "## Historical Results Summary",
                f"- Rows matched for target: `{rows}`",
                f"- Closed-like outcomes: `{closed_like}`",
                f"- Success-like outcomes: `{success_like}`",
                (
                    f"- Success-like ratio: `{success_rate:.3f}`"
                    if success_rate is not None
                    else "- Success-like ratio: `N/A (insufficient closed outcomes)`"
                ),
                *[f"- {n}" for n in (historical.get("notes") or [])],
                "",
                "## Business Logic Intent",
                (
                    "Tune per-symbol/per-profile/per-side settings to improve signal quality and reduce profile-specific false positives/false negatives while preserving existing safety boundaries."
                ),
                "",
                "## Current Implementation Summary",
                "- Settings are resolved from trading config and preset/profile mappings.",
                "- Strategy profile resolution combines symbol preset and risk approach.",
                "- Signal monitor consumes thresholds and signal conditions from existing config/rules.",
                "",
                "## Problem Observed",
                (
                    "Historical coverage and/or target mapping suggest opportunities for profile-specific setting refinement."
                    if rows > 0
                    else "Insufficient symbol/profile/side-labeled historical outcomes to justify precise optimization yet."
                ),
                "",
                "## Proposed Setting Changes",
            ]
        )
        lines.extend([f"- {x}" for x in proposed_changes])
        lines.extend(
            [
                "",
                "## Expected Benefit",
                "Better alignment between profile intent and observed outcomes, improving alert precision and reducing avoidable noise for the targeted side.",
                "",
                "## Affected Files",
            ]
        )
        lines.extend([f"- `{x}`" for x in affected_files])
        lines.extend(
            [
                "",
                "## Validation Plan",
            ]
        )
        lines.extend([f"- {x}" for x in validation_plan])
        lines.extend(
            [
                "",
                "## Risk Level",
                "low",
                "",
                "## Confidence Score",
                (
                    f"{confidence:.3f} (rule-based: data availability + symbol/profile/side mapping clarity + observed pattern strength + proposal directness - missing-data penalties)"
                ),
            ]
        )

        out_dir = _repo_root() / "docs" / "analysis"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"profile-settings-{task_id}.md"
        out_file.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
        _ensure_analysis_index(out_dir / "README.md", task_id=task_id, title=title)

        try:
            from app.services.agent_activity_log import log_agent_event

            log_agent_event(
                "profile_setting_analysis_generated",
                task_id=task_id,
                task_title=title,
                details={
                    "analysis_file": f"docs/analysis/profile-settings-{task_id}.md",
                    "symbol": symbol,
                    "profile": profile,
                    "side": side,
                    "confidence_score": confidence,
                    "proposed_version": versioning.get("proposed_version", ""),
                },
            )
        except Exception:
            pass

        return {
            "success": True,
            "summary": f"profile-setting analysis generated at docs/analysis/profile-settings-{task_id}.md",
            "analysis_file": f"docs/analysis/profile-settings-{task_id}.md",
            "symbol": symbol,
            "profile": profile,
            "side": side,
            "current_version": versioning.get("current_version", ""),
            "proposed_version": versioning.get("proposed_version", ""),
            "version_status": "proposed",
            "change_summary": versioning.get("change_summary", ""),
            "proposed_setting_changes": proposed_changes,
            "affected_files": affected_files,
            "validation_plan": validation_plan,
            "risk_level": "low",
            "confidence_score": confidence,
            "data_sources_used": data_sources_used,
        }
    except Exception as e:
        logger.exception("apply_profile_setting_analysis_task failed: %s", e)
        return {"success": False, "summary": str(e)}


def validate_profile_setting_analysis_task(prepared_task: dict) -> dict:
    try:
        task_id = _safe_task_id(prepared_task)
        if not task_id:
            return {"success": False, "summary": "missing task.id"}

        path = _repo_root() / "docs" / "analysis" / f"profile-settings-{task_id}.md"
        if not path.exists():
            return {"success": False, "summary": f"missing analysis file: {path.as_posix()}"}

        content = _read_text(path, max_chars=300000)
        if not content.strip():
            return {"success": False, "summary": "analysis markdown is empty"}

        for marker in _REQUIRED_SECTIONS:
            if marker not in content:
                msg = f"missing required section: {marker}"
                try:
                    from app.services.agent_activity_log import log_agent_event
                    log_agent_event("profile_setting_analysis_validation_failed", task_id=task_id, details={"reason": msg})
                except Exception:
                    pass
                return {"success": False, "summary": msg}

        # Symbol/profile/side present or explicitly uncertain.
        for sec in ("Symbol", "Profile", "Side"):
            block = _extract_section(content, sec)
            if not block.strip():
                msg = f"{sec.lower()} field missing"
                try:
                    from app.services.agent_activity_log import log_agent_event
                    log_agent_event("profile_setting_analysis_validation_failed", task_id=task_id, details={"reason": msg})
                except Exception:
                    pass
                return {"success": False, "summary": msg}

        # Proposed change presence or explicit safe non-proposal explanation.
        proposed = _extract_section(content, "Proposed Setting Changes")
        has_bullets = any(ln.strip().startswith("- ") for ln in proposed.splitlines())
        explicit_no_numeric = "no safe numeric proposal" in proposed.lower()
        if not (has_bullets and (("->" in proposed) or explicit_no_numeric)):
            msg = "proposed setting changes must include concrete change(s) or explicit no-safe-numeric explanation"
            try:
                from app.services.agent_activity_log import log_agent_event
                log_agent_event("profile_setting_analysis_validation_failed", task_id=task_id, details={"reason": msg})
            except Exception:
                pass
            return {"success": False, "summary": msg}

        affected = _extract_section(content, "Affected Files")
        if not any(ln.strip().startswith("- ") for ln in affected.splitlines()):
            msg = "at least one affected file is required"
            try:
                from app.services.agent_activity_log import log_agent_event
                log_agent_event("profile_setting_analysis_validation_failed", task_id=task_id, details={"reason": msg})
            except Exception:
                pass
            return {"success": False, "summary": msg}

        confidence = _extract_section(content, "Confidence Score")
        if not confidence.strip():
            msg = "confidence score missing"
            try:
                from app.services.agent_activity_log import log_agent_event
                log_agent_event("profile_setting_analysis_validation_failed", task_id=task_id, details={"reason": msg})
            except Exception:
                pass
            return {"success": False, "summary": msg}

        # Validate relative links.
        for link in _markdown_links(content):
            if not link or "://" in link or link.startswith("#"):
                continue
            target = link.split("#", 1)[0].strip()
            if not target:
                continue
            resolved = (path.parent / target).resolve()
            if not resolved.exists():
                msg = f"broken relative markdown link: {link}"
                try:
                    from app.services.agent_activity_log import log_agent_event
                    log_agent_event("profile_setting_analysis_validation_failed", task_id=task_id, details={"reason": msg})
                except Exception:
                    pass
                return {"success": False, "summary": msg}

        return {"success": True, "summary": "profile-setting analysis note validated (sections, targets, proposal/confidence, links)"}
    except Exception as e:
        logger.exception("validate_profile_setting_analysis_task failed: %s", e)
        try:
            task_id = _safe_task_id(prepared_task)
            from app.services.agent_activity_log import log_agent_event
            log_agent_event("profile_setting_analysis_validation_failed", task_id=task_id or None, details={"reason": str(e)})
        except Exception:
            pass
        return {"success": False, "summary": str(e)}


def _extract_section(text: str, section_name: str) -> str:
    marker = f"## {section_name}"
    if marker not in text:
        return ""
    rest = text.split(marker, 1)[1]
    if "\n## " in rest:
        rest = rest.split("\n## ", 1)[0]
    return rest.strip()

