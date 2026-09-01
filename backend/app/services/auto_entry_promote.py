"""Auto entry model promote decisions (PR-ML-C).

Compares candidate holdout metrics to the current manifest and, when allowed,
promotes `current.joblib`. No Approval Center path — gated by
AUTO_ML_AUTONOMOUS_PROMOTE (default false), AUTO_ML_HUMAN_PROMOTE (process env,
default false), POST /api/config/auto-ml/promote (explicit human gate), or
--force-promote CLI.
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


def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def autonomous_promote_enabled() -> bool:
    return _env_bool("AUTO_ML_AUTONOMOUS_PROMOTE", False)


def human_promote_enabled() -> bool:
    """Explicit operator merit gate (e.g. workflow_dispatch dry_run_only=false)."""
    return _env_bool("AUTO_ML_HUMAN_PROMOTE", False)


def promote_gate_enabled() -> bool:
    return autonomous_promote_enabled() or human_promote_enabled()


def min_promote_rows() -> int:
    raw = (os.environ.get("AUTO_ML_PROMOTE_MIN_ROWS") or "20").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 20


def min_promote_delta() -> float:
    raw = (os.environ.get("AUTO_ML_PROMOTE_MIN_DELTA") or "0.0").strip()
    try:
        return float(raw)
    except ValueError:
        return 0.0


def primary_metric(metrics: Optional[dict[str, Any]]) -> Optional[float]:
    """Prefer holdout roc_auc; else accuracy. None if unusable."""
    if not isinstance(metrics, dict):
        return None
    if metrics.get("holdout") is False and metrics.get("note") == "single_class_fit_on_all":
        return None
    auc = metrics.get("roc_auc")
    if auc is not None:
        try:
            return float(auc)
        except (TypeError, ValueError):
            pass
    acc = metrics.get("accuracy")
    if acc is not None:
        try:
            return float(acc)
        except (TypeError, ValueError):
            return None
    return None


@dataclass
class PromoteDecision:
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
        logger.warning("Failed to read manifest %s: %s", path, e)
        return None


def should_promote(
    candidate: dict[str, Any],
    current: Optional[dict[str, Any]],
    *,
    min_rows: Optional[int] = None,
    min_delta: Optional[float] = None,
    allow_single_class: bool = False,
    autonomous: Optional[bool] = None,
    human: Optional[bool] = None,
    force: bool = False,
    merit_only: bool = False,
) -> PromoteDecision:
    rows_floor = min_promote_rows() if min_rows is None else min_rows
    delta = min_promote_delta() if min_delta is None else min_delta
    auto = autonomous_promote_enabled() if autonomous is None else autonomous
    human_ok = human_promote_enabled() if human is None else human
    gate_open = auto or human_ok

    n_fit = int(candidate.get("n_fit_rows") or 0)
    cand_metrics = candidate.get("metrics") if isinstance(candidate.get("metrics"), dict) else {}
    cand_metric = primary_metric(cand_metrics)

    if force:
        return PromoteDecision(
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
        return PromoteDecision(
            should_promote=False,
            reason="autonomous_promote_disabled",
            candidate_metric=cand_metric,
            current_metric=primary_metric((current or {}).get("metrics")),
            min_rows=rows_floor,
            min_delta=delta,
            autonomous=auto,
            human_promote=human_ok,
        )

    if n_fit < rows_floor:
        return PromoteDecision(
            should_promote=False,
            reason=f"n_fit_rows={n_fit}<{rows_floor}",
            candidate_metric=cand_metric,
            current_metric=primary_metric((current or {}).get("metrics")),
            min_rows=rows_floor,
            min_delta=delta,
            autonomous=auto,
            human_promote=human_ok,
        )

    if cand_metrics.get("holdout") is False and not allow_single_class:
        return PromoteDecision(
            should_promote=False,
            reason="single_class_or_no_holdout",
            candidate_metric=cand_metric,
            current_metric=primary_metric((current or {}).get("metrics")),
            min_rows=rows_floor,
            min_delta=delta,
            autonomous=auto,
            human_promote=human_ok,
        )

    if cand_metric is None:
        return PromoteDecision(
            should_promote=False,
            reason="candidate_metric_missing",
            candidate_metric=None,
            current_metric=primary_metric((current or {}).get("metrics")),
            min_rows=rows_floor,
            min_delta=delta,
            autonomous=auto,
            human_promote=human_ok,
        )

    if current is None:
        return PromoteDecision(
            should_promote=True,
            reason="no_current_baseline",
            candidate_metric=cand_metric,
            current_metric=None,
            min_rows=rows_floor,
            min_delta=delta,
            autonomous=auto,
            human_promote=human_ok,
        )

    cur_metric = primary_metric(current.get("metrics") if isinstance(current.get("metrics"), dict) else {})
    if cur_metric is None:
        return PromoteDecision(
            should_promote=True,
            reason="current_metric_missing",
            candidate_metric=cand_metric,
            current_metric=None,
            min_rows=rows_floor,
            min_delta=delta,
            autonomous=auto,
            human_promote=human_ok,
        )

    if cand_metric + 1e-12 >= cur_metric + delta:
        return PromoteDecision(
            should_promote=True,
            reason=f"metric_improved:{cur_metric:.4f}->{cand_metric:.4f}(delta>={delta})",
            candidate_metric=cand_metric,
            current_metric=cur_metric,
            min_rows=rows_floor,
            min_delta=delta,
            autonomous=auto,
            human_promote=human_ok,
        )

    return PromoteDecision(
        should_promote=False,
        reason=f"metric_not_improved:{cur_metric:.4f}->{cand_metric:.4f}(need+{delta})",
        candidate_metric=cand_metric,
        current_metric=cur_metric,
        min_rows=rows_floor,
        min_delta=delta,
        autonomous=auto,
        human_promote=human_ok,
    )


def apply_promote(
    out_dir: Path,
    *,
    candidate_model: Path,
    candidate_manifest: dict[str, Any],
    decision: PromoteDecision,
) -> dict[str, Any]:
    """Copy candidate → current.joblib and write promoted manifest.json."""
    out_dir.mkdir(parents=True, exist_ok=True)
    current_model = out_dir / "current.joblib"
    # Snapshot previous manifest for Telegram "what changed"
    prev_manifest = load_manifest(out_dir / "manifest.json")
    if prev_manifest is not None:
        (out_dir / "manifest.prev.json").write_text(
            json.dumps(prev_manifest, indent=2) + "\n", encoding="utf-8"
        )
    shutil.copy2(candidate_model, current_model)

    promoted = dict(candidate_manifest)
    promoted["autonomous_promote"] = bool(decision.autonomous)
    promoted["human_promote"] = bool(decision.human_promote)
    promoted["promoted_at"] = datetime.now(timezone.utc).isoformat()
    promoted["promote_reason"] = decision.reason
    promoted["promote_decision"] = asdict(decision)
    promoted["live_gate_enabled"] = _env_bool("AUTO_ML_ENABLED", False)
    promoted["previous_version"] = (prev_manifest or {}).get("version")
    promoted["note"] = "PR-ML-C promoted current.joblib"
    (out_dir / "manifest.json").write_text(
        json.dumps(promoted, indent=2) + "\n", encoding="utf-8"
    )
    # Keep candidate manifest for audit
    (out_dir / "candidate_manifest.json").write_text(
        json.dumps(candidate_manifest, indent=2) + "\n", encoding="utf-8"
    )
    return promoted


PENDING_PROMOTE_FILENAME = "pending_promote.json"


def model_out_dir(model_path: Optional[Path] = None) -> Path:
    """Directory holding current.joblib, candidate artifacts, and pending promote."""
    if model_path is None:
        from app.services.auto_entry_model import default_model_path

        model_path = default_model_path()
    return model_path.parent


def write_pending_promote(
    out_dir: Path,
    *,
    candidate: dict[str, Any],
    decision: PromoteDecision,
) -> dict[str, Any]:
    """Persist merit-passing candidate awaiting explicit human promote."""
    payload = {
        "pending_at": datetime.now(timezone.utc).isoformat(),
        "candidate_version": candidate.get("version"),
        "quality_gate_passed": bool(decision.should_promote),
        "decision": asdict(decision),
        "candidate_manifest": candidate,
        "note": (
            "Quality gate passed; awaiting AUTO_ML_HUMAN_PROMOTE or "
            "POST /api/config/auto-ml/promote"
        ),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / PENDING_PROMOTE_FILENAME).write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def clear_pending_promote(out_dir: Path) -> None:
    pending = out_dir / PENDING_PROMOTE_FILENAME
    if pending.is_file():
        pending.unlink()


def load_pending_promote(out_dir: Path) -> Optional[dict[str, Any]]:
    path = out_dir / PENDING_PROMOTE_FILENAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception as e:
        logger.warning("Failed to read pending promote %s: %s", path, e)
        return None


def promote_candidate_from_disk(
    out_dir: Path,
    *,
    human: bool = True,
    force: bool = False,
    send_telegram: bool = True,
    allow_single_class: bool = False,
    min_rows: Optional[int] = None,
    min_delta: Optional[float] = None,
) -> dict[str, Any]:
    """Promote on-disk candidate when merit + permission gates pass."""
    candidate_model = out_dir / "candidate.joblib"
    candidate = load_manifest(out_dir / "candidate_manifest.json")
    if candidate is None or not candidate_model.is_file():
        return {
            "ok": False,
            "error": "candidate_missing",
            "detail": "candidate.joblib or candidate_manifest.json not found",
        }

    current = load_manifest(out_dir / "manifest.json")
    auto = autonomous_promote_enabled()
    human_ok = human if human is not None else human_promote_enabled()
    quality = should_promote(
        candidate,
        current,
        min_rows=min_rows,
        min_delta=min_delta,
        allow_single_class=allow_single_class,
        merit_only=True,
        force=force,
    )
    if not quality.should_promote and not force:
        return {
            "ok": False,
            "error": "quality_gate_failed",
            "decision": asdict(quality),
        }

    permission = should_promote(
        candidate,
        current,
        min_rows=min_rows,
        min_delta=min_delta,
        allow_single_class=allow_single_class,
        autonomous=auto,
        human=human_ok,
        force=force,
    )
    if not permission.should_promote:
        return {
            "ok": False,
            "error": "promote_permission_denied",
            "decision": asdict(permission),
            "quality_decision": asdict(quality),
        }

    previous = current
    promoted = apply_promote(
        out_dir,
        candidate_model=candidate_model,
        candidate_manifest=candidate,
        decision=permission,
    )
    clear_pending_promote(out_dir)
    telegram_sent = False
    if send_telegram:
        telegram_sent = notify_model_version_update(
            out_dir=out_dir,
            promoted=promoted,
            decision=permission,
            previous=previous,
        )
    return {
        "ok": True,
        "promoted": True,
        "promoted_manifest": {
            "version": promoted.get("version"),
            "previous_version": promoted.get("previous_version"),
            "promoted_at": promoted.get("promoted_at"),
            "promote_reason": promoted.get("promote_reason"),
        },
        "decision": asdict(permission),
        "telegram_sent": telegram_sent,
    }


def _human_reason(reason: str) -> str:
    if reason == "force":
        return "Promote forzado por operador (--force-promote)."
    if reason == "no_current_baseline":
        return "Primera versión en producción (no había modelo current previo)."
    if reason == "current_metric_missing":
        return "El modelo actual no tenía métrica usable; se adopta el candidato."
    if reason.startswith("metric_improved:"):
        return "El candidato mejoró la métrica de holdout vs el modelo actual."
    if reason.startswith("metric_not_improved:"):
        return "El candidato no mejoró lo suficiente vs el modelo actual."
    if reason.startswith("n_fit_rows="):
        return "Insuficientes filas etiquetadas para promover."
    if reason == "single_class_or_no_holdout":
        return "Entrenamiento sin holdout / una sola clase (bloqueado salvo allow-single-class)."
    if reason == "autonomous_promote_disabled":
        return "AUTO_ML_AUTONOMOUS_PROMOTE y AUTO_ML_HUMAN_PROMOTE están desactivados."
    if reason == "candidate_metric_missing":
        return "El candidato no reportó métrica primaria."
    if reason == "train_direct_current":
        return "Entrenamiento escribió current.joblib directamente (train_auto_entry_model)."
    return reason


def format_promote_telegram(
    promoted: dict[str, Any],
    decision: PromoteDecision,
    *,
    previous: Optional[dict[str, Any]] = None,
) -> str:
    """Rich Telegram body: version delta, what changed, and why."""
    prev = previous or {}
    ver = promoted.get("version")
    prev_ver = prev.get("version")
    ver_line = (
        f"v{prev_ver} → v{ver}" if prev_ver is not None and prev_ver != ver else f"v{ver}"
    )

    cm = decision.candidate_metric
    pm = decision.current_metric
    cm_s = f"{cm:.4f}" if cm is not None else "n/a"
    pm_s = f"{pm:.4f}" if pm is not None else "n/a"

    metrics = promoted.get("metrics") if isinstance(promoted.get("metrics"), dict) else {}
    ds = promoted.get("dataset_meta") if isinstance(promoted.get("dataset_meta"), dict) else {}
    prev_metrics = prev.get("metrics") if isinstance(prev.get("metrics"), dict) else {}

    changes: list[str] = []
    if prev_ver is None:
        changes.append("• Se instaló el primer artefacto <code>current.joblib</code>")
    else:
        changes.append(f"• Versión de modelo: <code>v{prev_ver}</code> → <code>v{ver}</code>")
    changes.append(
        f"• Métrica primaria (holdout auc/acc): <code>{pm_s}</code> → <code>{cm_s}</code>"
    )
    if metrics.get("accuracy") is not None or prev_metrics.get("accuracy") is not None:
        pa = prev_metrics.get("accuracy")
        ca = metrics.get("accuracy")
        pa_s = f"{float(pa):.4f}" if pa is not None else "n/a"
        ca_s = f"{float(ca):.4f}" if ca is not None else "n/a"
        changes.append(f"• Accuracy holdout: <code>{pa_s}</code> → <code>{ca_s}</code>")
    if metrics.get("roc_auc") is not None or prev_metrics.get("roc_auc") is not None:
        pr = prev_metrics.get("roc_auc")
        cr = metrics.get("roc_auc")
        pr_s = f"{float(pr):.4f}" if pr is not None else "n/a"
        cr_s = f"{float(cr):.4f}" if cr is not None else "n/a"
        changes.append(f"• ROC-AUC holdout: <code>{pr_s}</code> → <code>{cr_s}</code>")
    n_fit = promoted.get("n_fit_rows")
    n_pos = ds.get("n_positive")
    n_neg = ds.get("n_negative")
    changes.append(
        f"• Dataset: source=<code>{ds.get('source') or 'n/a'}</code> "
        f"rows=<code>{n_fit}</code> (pos={n_pos} neg={n_neg})"
    )
    changes.append(
        f"• Gate live: AUTO_ML_ENABLED=<code>{promoted.get('live_gate_enabled')}</code> "
        f"threshold usa env <code>AUTO_ML_THRESHOLD</code>"
    )
    if promoted.get("feature_version") is not None:
        changes.append(f"• feature_version=<code>{promoted.get('feature_version')}</code>")

    why = _human_reason(str(decision.reason or ""))
    promoted_at = promoted.get("promoted_at") or promoted.get("trained_at") or ""

    return (
        "🤖 <b>AUTO ML — NUEVA VERSIÓN</b>\n"
        f"<b>Versión:</b> <code>{ver_line}</code>\n"
        f"<b>Cuándo:</b> <code>{promoted_at}</code>\n"
        f"<b>Por qué:</b> {why}\n"
        f"<b>Motivo técnico:</b> <code>{decision.reason}</code>\n"
        f"<b>Cambios aplicados:</b>\n"
        + "\n".join(changes)
        + "\n"
        f"source=retrain host=AWS"
    )


def send_promote_telegram(message: str) -> bool:
    """Best-effort Telegram notify. Never logs token/chat secrets."""
    token = (
        (os.environ.get("TELEGRAM_BOT_TOKEN_AWS") or "").strip()
        or (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    )
    chat = (
        (os.environ.get("TELEGRAM_CHAT_ID_AWS") or "").strip()
        or (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
        or (os.environ.get("TELEGRAM_CHAT_ID_OPS") or "").strip()
    )
    if not token or not chat:
        logger.info("Telegram promote notify skipped (token/chat not configured)")
        return False
    try:
        from app.utils.http_client import http_post

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        response = http_post(
            url,
            json={
                "chat_id": chat,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
            calling_module="auto_entry_promote.send_promote_telegram",
        )
        ok = 200 <= int(getattr(response, "status_code", 0) or 0) < 300
        if ok:
            logger.info("Telegram promote notify sent")
        return bool(ok)
    except Exception as e:
        logger.warning("Telegram promote notify failed: %s", type(e).__name__)
        return False


def notify_model_version_update(
    *,
    out_dir: Path,
    promoted: dict[str, Any],
    decision: PromoteDecision,
    previous: Optional[dict[str, Any]] = None,
) -> bool:
    """Format + send Telegram for a version update. Returns send success."""
    prev = previous
    if prev is None:
        # Prefer audit file written just before promote when available
        bak = out_dir / "manifest.prev.json"
        prev = load_manifest(bak)
    msg = format_promote_telegram(promoted, decision, previous=prev)
    return send_promote_telegram(msg)
