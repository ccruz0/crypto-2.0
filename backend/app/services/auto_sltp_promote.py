"""Auto ML SL/TP promote decisions (Phase 2 / #623).

Human-gated promote of sltp_manifest.json. Never enables autonomous promote.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

PENDING_SLTP_FILENAME = "pending_sltp_promote.json"
SLTP_MANIFEST = "sltp_manifest.json"
SLTP_CANDIDATE_MANIFEST = "sltp_candidate_manifest.json"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def autonomous_promote_enabled() -> bool:
    return _env_bool("AUTO_ML_SLTP_AUTONOMOUS_PROMOTE", False)


def human_promote_enabled() -> bool:
    return _env_bool("AUTO_ML_SLTP_HUMAN_PROMOTE", False)


def promote_gate_enabled() -> bool:
    return autonomous_promote_enabled() or human_promote_enabled()


def min_promote_rows() -> int:
    raw = (os.environ.get("AUTO_ML_SLTP_PROMOTE_MIN_ROWS") or "20").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 20


def min_promote_delta() -> float:
    raw = (os.environ.get("AUTO_ML_SLTP_PROMOTE_MIN_DELTA") or "0.0").strip()
    try:
        return float(raw)
    except ValueError:
        return 0.0


def primary_metric(metrics: Optional[dict[str, Any]]) -> Optional[float]:
    """Holdout expectancy %% vs baseline (positive = learned beats baseline)."""
    if not isinstance(metrics, dict):
        return None
    delta = metrics.get("merit_delta_expectancy")
    if delta is not None:
        try:
            return float(delta)
        except (TypeError, ValueError):
            pass
    hold = metrics.get("holdout")
    if isinstance(hold, dict) and hold.get("expectancy_pct") is not None:
        try:
            return float(hold["expectancy_pct"])
        except (TypeError, ValueError):
            return None
    return None


@dataclass
class SltpPromoteDecision:
    should_promote: bool
    reason: str
    candidate_metric: Optional[float]
    current_metric: Optional[float]
    min_rows: int
    min_delta: float
    autonomous: bool
    human_promote: bool = False


def load_manifest(path: Path) -> Optional[dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception as e:
        logger.warning("Failed to read SL/TP manifest %s: %s", path, e)
        return None


def should_promote_sltp(
    candidate: dict[str, Any],
    current: Optional[dict[str, Any]],
    *,
    min_rows: Optional[int] = None,
    min_delta: Optional[float] = None,
    autonomous: Optional[bool] = None,
    human: Optional[bool] = None,
    force: bool = False,
    merit_only: bool = False,
) -> SltpPromoteDecision:
    rows_floor = min_promote_rows() if min_rows is None else min_rows
    delta = min_promote_delta() if min_delta is None else min_delta
    auto = autonomous_promote_enabled() if autonomous is None else autonomous
    human_ok = human_promote_enabled() if human is None else human
    gate_open = auto or human_ok

    n_fit = int(candidate.get("n_fit_rows") or 0)
    n_holdout = int(candidate.get("n_holdout_rows") or 0)
    cand_metrics = candidate.get("metrics") if isinstance(candidate.get("metrics"), dict) else {}
    cand_metric = primary_metric(cand_metrics)

    if force:
        return SltpPromoteDecision(
            should_promote=True,
            reason="force",
            candidate_metric=cand_metric,
            current_metric=primary_metric((current or {}).get("metrics")),
            min_rows=rows_floor,
            min_delta=delta,
            autonomous=auto,
            human_promote=human_ok,
        )

    if not merit_only and not gate_open:
        return SltpPromoteDecision(
            should_promote=False,
            reason="autonomous_promote_disabled",
            candidate_metric=cand_metric,
            current_metric=primary_metric((current or {}).get("metrics")),
            min_rows=rows_floor,
            min_delta=delta,
            autonomous=auto,
            human_promote=human_ok,
        )

    total = n_fit + n_holdout
    if total < rows_floor:
        return SltpPromoteDecision(
            should_promote=False,
            reason=f"n_rows={total}<{rows_floor}",
            candidate_metric=cand_metric,
            current_metric=primary_metric((current or {}).get("metrics")),
            min_rows=rows_floor,
            min_delta=delta,
            autonomous=auto,
            human_promote=human_ok,
        )

    holdout = cand_metrics.get("holdout") if isinstance(cand_metrics.get("holdout"), dict) else {}
    if not holdout or holdout.get("n", 0) < 1:
        return SltpPromoteDecision(
            should_promote=False,
            reason="holdout_missing",
            candidate_metric=cand_metric,
            current_metric=primary_metric((current or {}).get("metrics")),
            min_rows=rows_floor,
            min_delta=delta,
            autonomous=auto,
            human_promote=human_ok,
        )

    merit_delta = cand_metrics.get("merit_delta_expectancy")
    if merit_delta is None:
        return SltpPromoteDecision(
            should_promote=False,
            reason="merit_delta_missing",
            candidate_metric=None,
            current_metric=primary_metric((current or {}).get("metrics")),
            min_rows=rows_floor,
            min_delta=delta,
            autonomous=auto,
            human_promote=human_ok,
        )

    try:
        merit_delta_f = float(merit_delta)
    except (TypeError, ValueError):
        return SltpPromoteDecision(
            should_promote=False,
            reason="merit_delta_invalid",
            candidate_metric=None,
            current_metric=primary_metric((current or {}).get("metrics")),
            min_rows=rows_floor,
            min_delta=delta,
            autonomous=auto,
            human_promote=human_ok,
        )

    if current is None:
        if merit_delta_f + 1e-12 >= delta:
            return SltpPromoteDecision(
                should_promote=True,
                reason=f"no_current_baseline:delta={merit_delta_f:.4f}",
                candidate_metric=merit_delta_f,
                current_metric=None,
                min_rows=rows_floor,
                min_delta=delta,
                autonomous=auto,
                human_promote=human_ok,
            )
        return SltpPromoteDecision(
            should_promote=False,
            reason=f"baseline_not_beaten:{merit_delta_f:.4f}<{delta}",
            candidate_metric=merit_delta_f,
            current_metric=None,
            min_rows=rows_floor,
            min_delta=delta,
            autonomous=auto,
            human_promote=human_ok,
        )

    cur_metrics = current.get("metrics") if isinstance(current.get("metrics"), dict) else {}
    cur_delta = cur_metrics.get("merit_delta_expectancy")
    cur_metric = float(cur_delta) if cur_delta is not None else primary_metric(cur_metrics)

    if merit_delta_f + 1e-12 >= max(delta, (cur_metric or -1e9) + delta):
        return SltpPromoteDecision(
            should_promote=True,
            reason=f"expectancy_improved:{cur_metric}->{merit_delta_f}(delta>={delta})",
            candidate_metric=merit_delta_f,
            current_metric=cur_metric,
            min_rows=rows_floor,
            min_delta=delta,
            autonomous=auto,
            human_promote=human_ok,
        )

    return SltpPromoteDecision(
        should_promote=False,
        reason=f"expectancy_not_improved:{cur_metric}->{merit_delta_f}(need+{delta})",
        candidate_metric=merit_delta_f,
        current_metric=cur_metric,
        min_rows=rows_floor,
        min_delta=delta,
        autonomous=auto,
        human_promote=human_ok,
    )


def apply_sltp_promote(
    out_dir: Path,
    *,
    candidate_manifest: dict[str, Any],
    decision: SltpPromoteDecision,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    prev = load_manifest(out_dir / SLTP_MANIFEST)
    if prev is not None:
        (out_dir / "sltp_manifest.prev.json").write_text(
            json.dumps(prev, indent=2) + "\n", encoding="utf-8"
        )

    promoted = dict(candidate_manifest)
    promoted["autonomous_promote"] = bool(decision.autonomous)
    promoted["human_promote"] = bool(decision.human_promote)
    promoted["promoted_at"] = datetime.now(timezone.utc).isoformat()
    promoted["promote_reason"] = decision.reason
    promoted["promote_decision"] = asdict(decision)
    promoted["live_gate_enabled"] = _env_bool("AUTO_ML_SLTP_ENABLED", False)
    promoted["previous_version"] = (prev or {}).get("version")
    (out_dir / SLTP_MANIFEST).write_text(json.dumps(promoted, indent=2) + "\n", encoding="utf-8")
    (out_dir / SLTP_CANDIDATE_MANIFEST).write_text(
        json.dumps(candidate_manifest, indent=2) + "\n", encoding="utf-8"
    )
    return promoted


def sltp_out_dir(model_path: Optional[Path] = None) -> Path:
    if model_path is None:
        from app.services.auto_sltp_model import default_sltp_dir

        return default_sltp_dir()
    return model_path


def write_pending_sltp_promote(
    out_dir: Path,
    *,
    candidate: dict[str, Any],
    decision: SltpPromoteDecision,
) -> dict[str, Any]:
    payload = {
        "pending_at": datetime.now(timezone.utc).isoformat(),
        "candidate_version": candidate.get("version"),
        "quality_gate_passed": bool(decision.should_promote),
        "decision": asdict(decision),
        "candidate_manifest": candidate,
        "note": (
            "Quality gate passed; awaiting AUTO_ML_SLTP_HUMAN_PROMOTE or "
            "POST /api/config/auto-ml/sltp/promote"
        ),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / PENDING_SLTP_FILENAME).write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def clear_pending_sltp_promote(out_dir: Path) -> None:
    pending = out_dir / PENDING_SLTP_FILENAME
    if pending.is_file():
        pending.unlink()


def load_pending_sltp_promote(out_dir: Path) -> Optional[dict[str, Any]]:
    path = out_dir / PENDING_SLTP_FILENAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception as e:
        logger.warning("Failed to read pending SL/TP promote %s: %s", path, e)
        return None


def promote_sltp_candidate_from_disk(
    out_dir: Path,
    *,
    human: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    candidate = load_manifest(out_dir / SLTP_CANDIDATE_MANIFEST)
    if candidate is None:
        return {
            "ok": False,
            "error": "candidate_missing",
            "detail": f"{SLTP_CANDIDATE_MANIFEST} not found",
        }

    current = load_manifest(out_dir / SLTP_MANIFEST)
    auto = autonomous_promote_enabled()
    human_ok = human if human is not None else human_promote_enabled()
    decision = should_promote_sltp(
        candidate,
        current,
        autonomous=auto,
        human=human_ok,
        force=force,
    )
    if not decision.should_promote:
        return {
            "ok": False,
            "error": "quality_gate_failed" if not force else "promote_failed",
            "decision": asdict(decision),
        }

    if not force and not human_ok and not auto:
        return {
            "ok": False,
            "error": "promote_permission_denied",
            "detail": "human gate required (POST /api/config/auto-ml/sltp/promote)",
            "decision": asdict(decision),
        }

    promoted = apply_sltp_promote(out_dir, candidate_manifest=candidate, decision=decision)
    clear_pending_sltp_promote(out_dir)
    return {"ok": True, "promoted": promoted, "decision": asdict(decision)}
