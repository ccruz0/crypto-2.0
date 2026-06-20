"""Aggregate the read-only A/B replay (replay_objective_aware.json) into the
metrics required by the PR #67 evaluation.

Each per-investigation verdict is grounded in (a) the deterministic flag OFF vs
ON deltas produced by the replay and (b) the analyst root-cause-accuracy score
from the existing baseline evaluation (jarvis_eval/score_and_aggregate.py), which
lets us separate *earned* confidence movement from *inflation*.

Read-only: consumes JSON artifacts only. No production access.
"""

from __future__ import annotations

import json
import os

HERE = os.path.dirname(__file__)

# Analyst root-cause-accuracy (0-10) from the baseline evaluation SCORES table.
# Used only to judge whether a confidence increase is earned (>=7) or inflation (<=4).
RC_ACCURACY = {
    "5b76cf57-80e6-45d0-8640-de0263777864": 9,
    "f79b9ffc-c553-4e58-a41b-3ee63a5bd30c": 8,
    "a5439a76-d6ce-4b2f-900a-f649ed1c45e1": 7,
    "9c6c5879-ad3d-4f0b-91e9-0d38b7e5ca80": 5,
    "fe5f566e-00ea-4065-acc6-409fd2e2a162": 5,
    "e080e0d0-e746-4fcd-8f2d-22f54733f223": 6,
    "4fcd9e28-22b1-43f2-886a-cf21466bc2bb": 6,
    "2616ea25-b02f-40d1-a8b6-91667e9323c9": 6,
    "ada36c20-8323-4160-9d2e-17dbf8cfdca2": 7,
    "3f35a4d6-b8c4-4422-94d4-106daa77c904": 7,
    "c7eae0f4-2522-41a3-b52a-7d8e0b356892": 6,
    "5cb222df-8007-4a0f-91df-b91dee0bac16": 6,
    "a6cf648c-e91a-463a-91d9-5ed492828cff": 3,
    "7652e662-957b-4200-98a2-91bcdc52e9dd": 3,
    "ec30b60b-aeaa-492b-a67b-f23c9fccf235": 2,
    "d3fa6e63-9b96-4822-8181-3ff1be2bd85a": 2,
    "cd4b339b-6cac-4bc2-aed2-8f7403a35961": 3,
    "99e5946a-82f1-42fa-a95a-37e03a68e2f9": 3,
}

GENERIC_MARKERS = (
    "review collected evidence",
    "implement targeted fix",
    "collect additional evidence",
    "review configuration",
    "investigate further",
    "no repair needed",
)


def is_generic(text: str) -> bool:
    low = (text or "").strip().lower()
    return any(m in low for m in GENERIC_MARKERS)


def is_gap_statement(text: str) -> bool:
    return (text or "").strip().lower().startswith("insufficient evidence")


def classify(r: dict) -> dict:
    off, on = r["off"], r["on"]
    acc = RC_ACCURACY[r["investigation_id"]]
    obj_dom = r["objective_domain"]
    obj_dom_conf = r["objective_domain_confidence"]

    dconf = round(on["confidence"] - off["confidence"], 1)
    caps = list(on.get("caps_applied") or (on.get("confidence_breakdown") or {}).get("caps_applied", []))
    legacy_on = on.get("legacy_confidence", off["confidence"])

    flags = []

    # Domain alignment.
    gating_active = obj_dom != "generic" and obj_dom_conf >= 0.4
    if gating_active and on["cause_domain"] == obj_dom and off["cause_domain"] != obj_dom and on["cause_domain"]:
        flags.append("domain_alignment_improved")

    # Cross-domain leakage prevention: OFF asserted a cross-domain cause; ON refuses or realigns.
    off_cross = (
        gating_active
        and off["cause_domain"]
        and off["cause_domain"] != obj_dom
        and off["status"] == "completed"
    )
    if off_cross and (on["status"] == "insufficient_evidence" or on["cause_domain"] == obj_dom):
        flags.append("cross_domain_leakage_prevented")

    # Confidence calibration.
    if dconf <= -10 and (caps or on["status"] == "insufficient_evidence"):
        # Deflation that the analyst agrees was warranted (weak/borderline diagnosis).
        if acc <= 6:
            flags.append("confidence_inflation_reduced")
        else:
            flags.append("confidence_deflation_questionable")
    if dconf >= 10:
        if acc <= 4:
            flags.append("confidence_inflation_introduced")  # overconfidence on weak/wrong diagnosis
        elif acc >= 7:
            flags.append("confidence_increase_earned")
        else:
            flags.append("confidence_increase_borderline")

    # Recommendation quality.
    off_gen = is_generic(off["recommended_fix"])
    on_gap = is_gap_statement(on["recommended_fix"])
    on_gen = is_generic(on["recommended_fix"])
    on_concrete = bool((on.get("recommendation_plan") or {}).get("affected_files")) and not on_gen
    if off_gen and on_concrete:
        flags.append("recommendation_made_concrete")
    elif off_gen and on_gap:
        flags.append("recommendation_generic_to_honest_gap")
    elif (not off_gen) and on_gap:
        flags.append("recommendation_downgraded_to_gap")

    # False-positive handling (auth credential false positives per analyst).
    if acc <= 3 and dconf >= 10:
        flags.append("false_positive_amplified")

    # ACW readiness.
    if on["acw_ready"] and not off["acw_ready"]:
        flags.append("acw_newly_enabled")
    if off["acw_ready"] and not on["acw_ready"]:
        flags.append("acw_newly_blocked")

    # Overall verdict.
    positive = {
        "domain_alignment_improved",
        "cross_domain_leakage_prevented",
        "confidence_inflation_reduced",
        "recommendation_made_concrete",
        "recommendation_generic_to_honest_gap",
        "confidence_increase_earned",
        "acw_newly_blocked",
    }
    negative = {
        "confidence_inflation_introduced",
        "false_positive_amplified",
        "recommendation_downgraded_to_gap",
        "confidence_deflation_questionable",
        "acw_newly_enabled",
    }
    has_pos = any(f in positive for f in flags)
    has_neg = any(f in negative for f in flags)
    if has_neg and not has_pos:
        verdict = "regression"
    elif has_neg and has_pos:
        verdict = "mixed"
    elif has_pos:
        verdict = "improvement"
    else:
        verdict = "neutral"

    return {
        "id": r["investigation_id"][:8],
        "category": r["category"],
        "obj_domain": obj_dom,
        "rc_accuracy": acc,
        "off_conf": off["confidence"],
        "on_conf": on["confidence"],
        "legacy_confidence": legacy_on,
        "dconf": dconf,
        "caps": caps,
        "off_acw": off["acw_ready"],
        "on_acw": on["acw_ready"],
        "status_change": f"{off['status']}->{on['status']}",
        "flags": flags,
        "verdict": verdict,
    }


def main() -> None:
    rows = json.load(open(os.path.join(HERE, "replay_objective_aware.json")))
    verdicts = [classify(r) for r in rows]

    n = len(verdicts)
    counts = {"improvement": 0, "regression": 0, "mixed": 0, "neutral": 0}
    for v in verdicts:
        counts[v["verdict"]] += 1

    def count_flag(flag):
        return sum(1 for v in verdicts if flag in v["flags"])

    metrics = {
        "total_reviewed": n,
        "improvement_rate": round(counts["improvement"] / n, 3),
        "regression_rate": round(counts["regression"] / n, 3),
        "mixed_rate": round(counts["mixed"] / n, 3),
        "neutral_rate": round(counts["neutral"] / n, 3),
        "verdict_counts": counts,
        "domain_alignment_improved": count_flag("domain_alignment_improved"),
        "cross_domain_leakage_prevented": count_flag("cross_domain_leakage_prevented"),
        "cross_domain_leakage_preservation": count_flag("cross_domain_leakage_prevented"),
        "confidence_inflation_reduced": count_flag("confidence_inflation_reduced"),
        "confidence_inflation_introduced": count_flag("confidence_inflation_introduced"),
        "false_positive_amplified": count_flag("false_positive_amplified"),
        "recommendation_made_concrete": count_flag("recommendation_made_concrete"),
        "recommendation_generic_to_honest_gap": count_flag("recommendation_generic_to_honest_gap"),
        "recommendation_quality_preservation": count_flag("recommendation_made_concrete")
        + count_flag("recommendation_generic_to_honest_gap"),
        "acw_newly_enabled": count_flag("acw_newly_enabled"),
        "acw_newly_blocked": count_flag("acw_newly_blocked"),
        "acw_ready_off": sum(1 for v in verdicts if v["off_acw"]),
        "acw_ready_on": sum(1 for v in verdicts if v["on_acw"]),
    }

    # Confidence calibration impact: mean |conf-50| as a crude over/under-confidence proxy,
    # plus mean confidence on analyst-weak (acc<=4) vs analyst-strong (acc>=7) cases.
    weak = [v for v in verdicts if v["rc_accuracy"] <= 4]
    strong = [v for v in verdicts if v["rc_accuracy"] >= 7]
    cal = {
        "weak_cases_off_mean_conf": round(sum(v["off_conf"] for v in weak) / len(weak), 1),
        "weak_cases_on_mean_conf": round(sum(v["on_conf"] for v in weak) / len(weak), 1),
        "strong_cases_off_mean_conf": round(sum(v["off_conf"] for v in strong) / len(strong), 1),
        "strong_cases_on_mean_conf": round(sum(v["on_conf"] for v in strong) / len(strong), 1),
    }

    out = {"metrics": metrics, "calibration_impact": cal, "per_investigation": verdicts}
    json.dump(out, open(os.path.join(HERE, "replay_metrics.json"), "w"), indent=2)

    print("=== VERDICTS ===")
    print(f"{'id':8} {'category':12} {'obj_domain':22} {'acc':>3} {'OFF':>5} {'ON':>6} {'Δ':>6} acw  verdict   flags")
    for v in verdicts:
        print(
            f"{v['id']:8} {v['category'][:12]:12} {v['obj_domain'][:22]:22} {v['rc_accuracy']:>3} "
            f"{v['off_conf']:>5.1f} {v['on_conf']:>6.1f} {v['dconf']:>6.1f} "
            f"{int(v['off_acw'])}/{int(v['on_acw'])}  {v['verdict']:10} {','.join(v['flags'])}"
        )
    print("\n=== METRICS ===")
    print(json.dumps(metrics, indent=2))
    print("\n=== CALIBRATION IMPACT ===")
    print(json.dumps(cal, indent=2))


if __name__ == "__main__":
    main()
