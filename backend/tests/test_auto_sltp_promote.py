"""Phase 2 Auto ML SL/TP promote gate tests (#623)."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.auto_sltp_promote import (
    SLTP_CANDIDATE_MANIFEST,
    SLTP_MANIFEST,
    apply_sltp_promote,
    promote_sltp_candidate_from_disk,
    should_promote_sltp,
    write_pending_sltp_promote,
)


def _candidate(*, delta: float = 0.05, n_fit: int = 16, n_holdout: int = 4) -> dict:
    return {
        "version": 2,
        "n_fit_rows": n_fit,
        "n_holdout_rows": n_holdout,
        "sl_pct": 2.5,
        "tp_pct": 4.0,
        "metrics": {
            "holdout": {"n": n_holdout, "expectancy_pct": 0.4},
            "baseline_holdout": {"n": n_holdout, "expectancy_pct": 0.35},
            "merit_delta_expectancy": delta,
        },
    }


def test_should_promote_sltp_disabled_by_default(monkeypatch):
    monkeypatch.delenv("AUTO_ML_SLTP_AUTONOMOUS_PROMOTE", raising=False)
    monkeypatch.delenv("AUTO_ML_SLTP_HUMAN_PROMOTE", raising=False)
    cand = _candidate(delta=0.1)
    d = should_promote_sltp(cand, None)
    assert d.should_promote is False
    assert d.reason == "autonomous_promote_disabled"
    quality = should_promote_sltp(cand, None, merit_only=True)
    assert quality.should_promote is True


def test_should_promote_sltp_with_human_gate(monkeypatch):
    monkeypatch.setenv("AUTO_ML_SLTP_HUMAN_PROMOTE", "true")
    monkeypatch.setenv("AUTO_ML_SLTP_PROMOTE_MIN_ROWS", "15")
    cand = _candidate(delta=0.08)
    cur = _candidate(delta=0.02)
    cur["version"] = 1
    d = should_promote_sltp(cand, cur)
    assert d.should_promote is True
    assert d.human_promote is True
    assert "expectancy_improved" in d.reason


def test_apply_sltp_promote_writes_manifest(tmp_path: Path):
    from app.services.auto_sltp_promote import SltpPromoteDecision

    cand = _candidate()
    decision = SltpPromoteDecision(
        should_promote=True,
        reason="force",
        candidate_metric=0.05,
        current_metric=None,
        min_rows=20,
        min_delta=0.0,
        autonomous=False,
        human_promote=True,
    )
    promoted = apply_sltp_promote(tmp_path, candidate_manifest=cand, decision=decision)
    assert (tmp_path / SLTP_MANIFEST).is_file()
    assert promoted["sl_pct"] == 2.5
    assert promoted["human_promote"] is True


def test_promote_sltp_candidate_from_disk_api_gate(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AUTO_ML_SLTP_HUMAN_PROMOTE", "false")
    cand = _candidate(delta=0.12)
    (tmp_path / SLTP_CANDIDATE_MANIFEST).write_text(
        json.dumps(cand, indent=2) + "\n", encoding="utf-8"
    )
    result = promote_sltp_candidate_from_disk(tmp_path, human=True)
    assert result["ok"] is True
    assert (tmp_path / SLTP_MANIFEST).is_file()


def test_write_pending_sltp_promote(tmp_path: Path):
    from app.services.auto_sltp_promote import SltpPromoteDecision

    cand = _candidate()
    decision = SltpPromoteDecision(
        should_promote=True,
        reason="no_current_baseline:delta=0.0500",
        candidate_metric=0.05,
        current_metric=None,
        min_rows=20,
        min_delta=0.0,
        autonomous=False,
        human_promote=False,
    )
    payload = write_pending_sltp_promote(tmp_path, candidate=cand, decision=decision)
    assert payload["quality_gate_passed"] is True
    assert payload["candidate_version"] == 2
