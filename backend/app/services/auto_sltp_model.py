"""Auto ML SL/TP runtime resolver (Phase 2 / #623).

Default OFF (`AUTO_ML_SLTP_ENABLED=false`). Uses promoted sltp_manifest.json for
Auto-preset **new** fill protection only — does not amend open legs or invent-heal.

Shadow log compares learned vs watchlist percentages when gate is disabled.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Optional, Tuple

from app.services.config_loader import load_config
from app.services.sl_tp_price_adjust import resolve_watchlist_percentages

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {
    "manifest": None,
    "path": None,
    "mtime": None,
}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def auto_ml_sltp_enabled() -> bool:
    return _env_bool("AUTO_ML_SLTP_ENABLED", False)


def auto_ml_sltp_shadow_log() -> bool:
    return _env_bool("AUTO_ML_SLTP_SHADOW_LOG", True)


def auto_ml_sltp_autonomous_promote() -> bool:
    return _env_bool("AUTO_ML_SLTP_AUTONOMOUS_PROMOTE", False)


def default_sltp_dir() -> Path:
    override = (os.environ.get("AUTO_ML_SLTP_DIR") or "").strip()
    if override:
        return Path(override)
    from app.services.auto_entry_model import default_model_path

    return default_model_path().parent


def _coin_preset(symbol: str) -> str:
    cfg = load_config()
    coin_cfg = cfg.get("coins", {}).get(symbol, {})
    preset = coin_cfg.get("preset") or cfg.get("defaults", {}).get("preset") or "swing"
    return str(preset).lower().split("-")[0]


def _load_manifest(force: bool = False) -> Optional[dict[str, Any]]:
    from app.services.auto_sltp_promote import SLTP_MANIFEST, load_manifest

    path = default_sltp_dir() / SLTP_MANIFEST
    path_s = str(path)
    mtime: Optional[float] = None
    if path.is_file():
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = None
    with _LOCK:
        if (
            not force
            and _CACHE["manifest"] is not None
            and _CACHE["path"] == path_s
            and _CACHE.get("mtime") == mtime
        ):
            return _CACHE["manifest"]
        manifest = load_manifest(path) if path.is_file() else None
        _CACHE.update({"manifest": manifest, "path": path_s, "mtime": mtime})
        return manifest


def reset_sltp_cache() -> None:
    with _LOCK:
        _CACHE.update({"manifest": None, "path": None, "mtime": None})


def get_promoted_sltp_params() -> Optional[dict[str, float]]:
    manifest = _load_manifest()
    if not manifest:
        return None
    try:
        sl = float(manifest["sl_pct"])
        tp = float(manifest["tp_pct"])
    except (KeyError, TypeError, ValueError):
        return None
    if sl <= 0 or tp <= 0:
        return None
    return {"sl_pct": sl, "tp_pct": tp, "version": manifest.get("version")}


def resolve_effective_sltp_percentages(
    symbol: str,
    watchlist_item: Any,
) -> Tuple[float, float, str, dict[str, Any]]:
    """Return (sl_pct, tp_pct, mode, meta) for post-fill protection sizing.

    Applies learned SL/TP only when coin preset is ``auto`` and gate is ON.
    """
    sl_pct, tp_pct, mode = resolve_watchlist_percentages(watchlist_item)
    meta: dict[str, Any] = {
        "source": "watchlist",
        "auto_sltp_applied": False,
        "coin_preset": _coin_preset(symbol),
    }

    if meta["coin_preset"] != "auto":
        return sl_pct, tp_pct, mode, meta

    learned = get_promoted_sltp_params()
    if learned is None:
        return sl_pct, tp_pct, mode, meta

    learned_sl = learned["sl_pct"]
    learned_tp = learned["tp_pct"]
    gate_on = auto_ml_sltp_enabled()

    if auto_ml_sltp_shadow_log() or gate_on:
        logger.info(
            "[AUTO_ML_SLTP] symbol=%s preset=auto gate=%s watchlist=%.2f/%.2f "
            "learned=%.2f/%.2f v=%s applied=%s",
            symbol,
            gate_on,
            sl_pct,
            tp_pct,
            learned_sl,
            learned_tp,
            learned.get("version"),
            gate_on,
        )

    if gate_on:
        meta.update(
            {
                "source": "auto_ml_sltp",
                "auto_sltp_applied": True,
                "learned_sl_pct": learned_sl,
                "learned_tp_pct": learned_tp,
                "learned_version": learned.get("version"),
                "watchlist_sl_pct": sl_pct,
                "watchlist_tp_pct": tp_pct,
            }
        )
        return learned_sl, learned_tp, mode, meta

    return sl_pct, tp_pct, mode, meta


def get_auto_sltp_status() -> dict[str, Any]:
    from app.services.auto_sltp_promote import (
        SLTP_CANDIDATE_MANIFEST,
        SLTP_MANIFEST,
        human_promote_enabled,
        load_manifest,
        load_pending_sltp_promote,
        min_promote_delta,
        min_promote_rows,
    )

    out_dir = default_sltp_dir()
    manifest = load_manifest(out_dir / SLTP_MANIFEST) or {}
    candidate = load_manifest(out_dir / SLTP_CANDIDATE_MANIFEST) or {}
    pending = load_pending_sltp_promote(out_dir) or {}
    metrics = manifest.get("metrics") if isinstance(manifest.get("metrics"), dict) else {}
    cand_metrics = candidate.get("metrics") if isinstance(candidate.get("metrics"), dict) else {}
    dataset_meta = (
        manifest.get("dataset_meta") if isinstance(manifest.get("dataset_meta"), dict) else {}
    )
    cand_meta = (
        candidate.get("dataset_meta") if isinstance(candidate.get("dataset_meta"), dict) else {}
    )
    pending_decision = pending.get("decision") if isinstance(pending.get("decision"), dict) else {}

    return {
        "gate_enabled": auto_ml_sltp_enabled(),
        "shadow_log": auto_ml_sltp_shadow_log(),
        "autonomous_promote": auto_ml_sltp_autonomous_promote(),
        "human_promote": human_promote_enabled(),
        "promote_min_rows": min_promote_rows(),
        "promote_min_delta": min_promote_delta(),
        "manifest_path": str(out_dir / SLTP_MANIFEST),
        "manifest_present": (out_dir / SLTP_MANIFEST).is_file(),
        "sl_pct": manifest.get("sl_pct"),
        "tp_pct": manifest.get("tp_pct"),
        "baseline_sl_pct": manifest.get("baseline_sl_pct"),
        "baseline_tp_pct": manifest.get("baseline_tp_pct"),
        "version": manifest.get("version"),
        "trained_at": manifest.get("trained_at"),
        "promoted_at": manifest.get("promoted_at"),
        "promote_reason": manifest.get("promote_reason"),
        "n_fit_rows": manifest.get("n_fit_rows"),
        "n_holdout_rows": manifest.get("n_holdout_rows"),
        "n_complete": dataset_meta.get("n_complete"),
        "n_long": dataset_meta.get("n_long"),
        "n_short": dataset_meta.get("n_short"),
        "candidate_version": candidate.get("version"),
        "candidate_sl_pct": candidate.get("sl_pct"),
        "candidate_tp_pct": candidate.get("tp_pct"),
        "candidate_n_complete": cand_meta.get("n_complete"),
        "pending_promote": bool(pending.get("quality_gate_passed")),
        "pending_at": pending.get("pending_at"),
        "pending_candidate_version": pending.get("candidate_version"),
        "pending_reason": pending_decision.get("reason"),
        "metrics": {
            "holdout": metrics.get("holdout"),
            "baseline_holdout": metrics.get("baseline_holdout"),
            "merit_delta_expectancy": metrics.get("merit_delta_expectancy"),
        },
        "candidate_metrics": {
            "holdout": cand_metrics.get("holdout"),
            "baseline_holdout": cand_metrics.get("baseline_holdout"),
            "merit_delta_expectancy": cand_metrics.get("merit_delta_expectancy"),
        },
    }
