"""Auto entry ML model load + score (PR-ML-B).

Gate is off unless AUTO_ML_ENABLED=true. Missing model/deps → fail-open
(allow rule BUY) with a warning. Shadow scores are logged for Auto candidates
even when the gate is disabled.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from app.services.auto_entry_features import (
    FEATURE_NAMES,
    FEATURE_VERSION,
    extract_features,
    feature_vector,
)

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {
    "model": None,
    "path": None,
    "mtime": None,
    "version": None,
    "feature_names": None,
    "feature_version": None,
    "load_error": None,
}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def auto_ml_enabled() -> bool:
    return _env_bool("AUTO_ML_ENABLED", False)


def auto_ml_autonomous_promote() -> bool:
    return _env_bool("AUTO_ML_AUTONOMOUS_PROMOTE", False)


def auto_ml_shadow_log() -> bool:
    # Default on so operators can see scores before enabling the gate.
    return _env_bool("AUTO_ML_SHADOW_LOG", True)


def auto_ml_threshold() -> float:
    raw = (os.environ.get("AUTO_ML_THRESHOLD") or "0.5").strip()
    try:
        return float(raw)
    except ValueError:
        return 0.5


def default_model_path() -> Path:
    override = (os.environ.get("AUTO_ML_MODEL_PATH") or "").strip()
    if override:
        return Path(override)
    # Prefer repo models/auto_entry/current.joblib; fall back beside backend/
    here = Path(__file__).resolve()
    repo_root = here.parents[3]  # backend/app/services -> repo
    candidates = [
        repo_root / "models" / "auto_entry" / "current.joblib",
        here.parents[2] / "models" / "auto_entry" / "current.joblib",  # backend/models
    ]
    for p in candidates:
        if p.is_file():
            return p
    return candidates[0]


@dataclass
class AutoEntryScore:
    score: Optional[float]
    version: Optional[int]
    threshold: float
    gate_enabled: bool
    passed: Optional[bool]  # None = no score / fail-open
    reason: str
    features: Optional[dict[str, float]] = None


def _load_model(force: bool = False) -> Any:
    path = default_model_path()
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
            and _CACHE["model"] is not None
            and _CACHE["path"] == path_s
            and _CACHE.get("mtime") == mtime
        ):
            return _CACHE["model"]
        if not path.is_file():
            _CACHE.update(
                {
                    "model": None,
                    "path": path_s,
                    "mtime": None,
                    "version": None,
                    "load_error": f"model_missing:{path_s}",
                }
            )
            return None
        try:
            import joblib  # optional runtime dep
        except ImportError as e:
            _CACHE.update(
                {
                    "model": None,
                    "path": path_s,
                    "mtime": None,
                    "load_error": f"joblib_missing:{e}",
                }
            )
            return None
        try:
            payload = joblib.load(path)
            if isinstance(payload, dict) and "model" in payload:
                model = payload["model"]
                names = payload.get("feature_names") or list(FEATURE_NAMES)
                fver = payload.get("feature_version", FEATURE_VERSION)
                version = payload.get("version")
            else:
                model = payload
                names = list(FEATURE_NAMES)
                fver = FEATURE_VERSION
                version = None
            if list(names) != list(FEATURE_NAMES):
                logger.warning(
                    "Auto ML feature_names mismatch (model=%s runtime=%s) — scoring disabled",
                    names,
                    list(FEATURE_NAMES),
                )
                _CACHE.update(
                    {
                        "model": None,
                        "path": path_s,
                        "mtime": None,
                        "load_error": "feature_names_mismatch",
                    }
                )
                return None
            if int(fver) != int(FEATURE_VERSION):
                logger.warning(
                    "Auto ML feature_version mismatch (model=%s runtime=%s) — scoring disabled",
                    fver,
                    FEATURE_VERSION,
                )
                _CACHE.update(
                    {
                        "model": None,
                        "path": path_s,
                        "mtime": None,
                        "load_error": "feature_version_mismatch",
                    }
                )
                return None
            _CACHE.update(
                {
                    "model": model,
                    "path": path_s,
                    "mtime": mtime,
                    "version": version,
                    "feature_names": names,
                    "feature_version": fver,
                    "load_error": None,
                }
            )
            logger.info(
                "Loaded Auto entry model path=%s version=%s feature_version=%s",
                path_s,
                version,
                fver,
            )
            return model
        except Exception as e:
            logger.warning("Failed to load Auto entry model from %s: %s", path_s, e)
            _CACHE.update(
                {
                    "model": None,
                    "path": path_s,
                    "mtime": None,
                    "load_error": str(e),
                }
            )
            return None


def reset_model_cache() -> None:
    """Test helper."""
    with _LOCK:
        _CACHE.update(
            {
                "model": None,
                "path": None,
                "mtime": None,
                "version": None,
                "feature_names": None,
                "feature_version": None,
                "load_error": None,
            }
        )


def score_auto_buy_candidate(
    *,
    symbol: str,
    price: float,
    rsi: Optional[float] = None,
    ma50: Optional[float] = None,
    ma200: Optional[float] = None,
    ema10: Optional[float] = None,
    volume_ratio: Optional[float] = None,
    atr: Optional[float] = None,
    strategy_index: Optional[float] = None,
    entry_ts_ms: Optional[int] = None,
) -> AutoEntryScore:
    """Score a rule-engine BUY candidate for Auto preset.

    Fail-open: if no model/score, passed=None and gate must not block.
    """
    threshold = auto_ml_threshold()
    gate_on = auto_ml_enabled()
    model = _load_model()
    if model is None:
        err = _CACHE.get("load_error") or "model_unavailable"
        return AutoEntryScore(
            score=None,
            version=_CACHE.get("version"),
            threshold=threshold,
            gate_enabled=gate_on,
            passed=None,
            reason=str(err),
        )

    feats = extract_features(
        side="BUY",
        entry_price=price,
        entry_ts_ms=entry_ts_ms,
        rsi=rsi,
        ma50=ma50,
        ma200=ma200,
        ema10=ema10,
        volume_ratio=volume_ratio,
        atr=atr,
        strategy_index=strategy_index,
    )
    x = [feature_vector(feats)]
    try:
        if hasattr(model, "predict_proba"):
            proba = model.predict_proba(x)
            # Assume class 1 = good entry
            classes = list(getattr(model, "classes_", [0, 1]))
            if 1 in classes:
                idx = classes.index(1)
            else:
                idx = 1 if proba.shape[1] > 1 else 0
            score = float(proba[0][idx])
        else:
            pred = model.predict(x)
            score = float(pred[0])
    except Exception as e:
        logger.warning("Auto ML score failed for %s: %s", symbol, e)
        return AutoEntryScore(
            score=None,
            version=_CACHE.get("version"),
            threshold=threshold,
            gate_enabled=gate_on,
            passed=None,
            reason=f"score_error:{e}",
            features=feats,
        )

    passed = score >= threshold
    return AutoEntryScore(
        score=score,
        version=_CACHE.get("version"),
        threshold=threshold,
        gate_enabled=gate_on,
        passed=passed,
        reason="ok",
        features=feats,
    )


def apply_auto_ml_buy_gate(
    *,
    symbol: str,
    price: float,
    rsi: Optional[float] = None,
    ma50: Optional[float] = None,
    ma200: Optional[float] = None,
    ema10: Optional[float] = None,
    volume_ratio: Optional[float] = None,
    atr: Optional[float] = None,
    strategy_index: Optional[float] = None,
) -> AutoEntryScore:
    """Score + optional shadow log. Caller enforces block when gate_enabled and passed is False."""
    result = score_auto_buy_candidate(
        symbol=symbol,
        price=price,
        rsi=rsi,
        ma50=ma50,
        ma200=ma200,
        ema10=ema10,
        volume_ratio=volume_ratio,
        atr=atr,
        strategy_index=strategy_index,
    )
    if auto_ml_shadow_log() or result.gate_enabled:
        logger.info(
            "[AUTO_ML] symbol=%s score=%s threshold=%.3f gate=%s passed=%s version=%s reason=%s",
            symbol,
            f"{result.score:.4f}" if result.score is not None else "None",
            result.threshold,
            result.gate_enabled,
            result.passed,
            result.version,
            result.reason,
        )
    return result
