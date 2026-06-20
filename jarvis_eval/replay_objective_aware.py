"""Read-only A/B replay of PR #67 (JARVIS_OBJECTIVE_AWARE_RC) over REAL production
investigations exported from the production DB (raw_investigations.json).

For every investigation we run the SAME current pipeline twice on the SAME real
inputs (evidence + real candidate set from ranked_causes_json), toggling only the
feature flag, faithfully mirroring investigation_runner.run_investigation:

    rank stage  -> (flag ON) apply_domain_gating to the real candidate list
    report stage-> build_investigation_report(flag)   -> root cause + confidence
    advisor     -> build_recommendation(report)        -> ACW readiness

Guarantees:
* No DB access, no production access, no execution, no writes to production.
* The flag is set ONLY inside this process via os.environ; production config is
  untouched. JARVIS_SELF_HEALING_ENABLED is set in-process so acw_ready reflects
  what the advisor WOULD emit if self-healing were enabled (the existing baseline
  harness, run_recommendations.py, does the same).
"""

from __future__ import annotations

import copy
import importlib
import json
import os
import sys
import types

os.environ.setdefault("JARVIS_SELF_HEALING_ENABLED", "true")
os.environ.setdefault("JARVIS_SELF_HEALING_ACW_THRESHOLD", "70")

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, BACKEND)


def _shim_package(dotted: str) -> None:
    rel = dotted.split(".")
    path = os.path.join(BACKEND, *rel)
    mod = types.ModuleType(dotted)
    mod.__path__ = [path]
    mod.__package__ = dotted
    sys.modules[dotted] = mod


for pkg in (
    "app",
    "app.core",
    "app.jarvis",
    "app.jarvis.proposals",
    "app.jarvis.investigations",
    "app.jarvis.execution",
    "app.jarvis.self_healing",
):
    _shim_package(pkg)

report_mod = importlib.import_module("app.jarvis.investigations.investigation_report")
domains_mod = importlib.import_module("app.jarvis.investigations.domains")
service_mod = importlib.import_module("app.jarvis.self_healing.service")

build_investigation_report = report_mod.build_investigation_report
RootCauseCandidate = report_mod.RootCauseCandidate
classify_domain = domains_mod.classify_domain
classify_cause_domain = domains_mod.classify_cause_domain
apply_domain_gating = domains_mod.apply_domain_gating
domain_relevance = domains_mod.domain_relevance
build_recommendation = service_mod.build_recommendation

HERE = os.path.dirname(__file__)


def legacy_confidence_from_off(rep_off, rep_on) -> float:
    """Fallback when breakdown lacks legacy_confidence (flag-off path)."""
    return float(rep_off.confidence)


def _candidates(inv: dict) -> list:
    out = []
    for c in inv.get("ranked_causes_json") or []:
        out.append(
            RootCauseCandidate(
                cause=c.get("cause", ""),
                score=float(c.get("score") or 0.0),
                supporting_evidence=list(c.get("supporting_evidence") or []),
                explanation=c.get("explanation", "") or "",
            )
        )
    return out


def _set_flag(on: bool) -> None:
    if on:
        os.environ["JARVIS_OBJECTIVE_AWARE_RC"] = "true"
    else:
        os.environ.pop("JARVIS_OBJECTIVE_AWARE_RC", None)


def _run_report(inv: dict, *, flag_on: bool):
    """Mirror investigation_runner: rank-stage gating (ON) then report build."""
    _set_flag(flag_on)
    evidence = copy.deepcopy(inv.get("evidence_json") or [])
    candidates = _candidates(inv)

    if flag_on:
        dc = classify_domain(
            inv.get("objective", ""),
            category=inv.get("category", ""),
            template_id=inv.get("template_id", ""),
        )
        candidates = apply_domain_gating(candidates, dc.domain, dc.domain_confidence)

    report = build_investigation_report(
        investigation_id=inv["investigation_id"],
        objective=inv.get("objective", ""),
        category=inv.get("category", ""),
        template_id=inv.get("template_id", "") or "",
        evidence=evidence,
        ranked_causes=candidates,
        tool_outputs=[],
        created_at=inv.get("created_at", ""),
    )
    return report


def _advisor(report_dict: dict, *, flag_on: bool) -> dict:
    _set_flag(flag_on)
    return build_recommendation(report_dict)


def main() -> None:
    with open(os.path.join(HERE, "raw_investigations.json")) as fh:
        investigations = json.load(fh)

    rows = []
    for inv in investigations:
        rep_off = _run_report(inv, flag_on=False)
        rep_on = _run_report(inv, flag_on=True)

        d_off = rep_off.to_dict()
        d_on = rep_on.to_dict()

        rec_off = _advisor(d_off, flag_on=False)
        rec_on = _advisor(d_on, flag_on=True)

        obj_domain = classify_domain(
            inv.get("objective", ""),
            category=inv.get("category", ""),
            template_id=inv.get("template_id", "") or "",
        )
        rc_off = rep_off.root_cause or ""
        rc_on = rep_on.root_cause or ""
        cause_dom_off = classify_cause_domain(rc_off).value if rc_off else ""
        cause_dom_on = classify_cause_domain(rc_on).value if rc_on else ""

        rows.append(
            {
                "investigation_id": inv["investigation_id"],
                "objective": inv.get("objective", ""),
                "category": inv.get("category", ""),
                "template_id": inv.get("template_id", ""),
                "stored": {
                    "root_cause": inv.get("root_cause"),
                    "confidence": float(inv.get("confidence") or 0.0),
                    "status": inv.get("status"),
                },
                "objective_domain": obj_domain.domain.value,
                "objective_domain_confidence": obj_domain.domain_confidence,
                "off": {
                    "root_cause": rc_off,
                    "cause_domain": cause_dom_off,
                    "confidence": round(rep_off.confidence, 1),
                    "legacy_confidence": round(rep_off.confidence, 1),
                    "status": rep_off.status.value
                    if hasattr(rep_off.status, "value")
                    else str(rep_off.status),
                    "recommended_fix": rep_off.recommended_fix,
                    "acw_ready": rec_off["acw_ready"],
                    "acw_reasons": rec_off["acw"]["reasons"],
                    "affected_files": rec_off["affected_files"],
                    "estimated_risk": rec_off["estimated_risk"],
                    "safety_allowed": rec_off["safety"]["allowed"],
                },
                "on": {
                    "root_cause": rc_on,
                    "cause_domain": cause_dom_on,
                    "confidence": round(rep_on.confidence, 1),
                    "legacy_confidence": round(
                        (rep_on.confidence_breakdown or {}).get(
                            "legacy_confidence", legacy_confidence_from_off(rep_off, rep_on)
                        ),
                        1,
                    ),
                    "caps_applied": list(
                        (rep_on.confidence_breakdown or {}).get("caps_applied") or []
                    ),
                    "status": rep_on.status.value
                    if hasattr(rep_on.status, "value")
                    else str(rep_on.status),
                    "recommended_fix": rep_on.recommended_fix,
                    "domain": rep_on.domain,
                    "confidence_breakdown": rep_on.confidence_breakdown,
                    "recommendation_plan": rep_on.recommendation_plan,
                    "acw_ready": rec_on["acw_ready"],
                    "acw_reasons": rec_on["acw"]["reasons"],
                    "affected_files": rec_on["affected_files"],
                    "estimated_risk": rec_on["estimated_risk"],
                    "safety_allowed": rec_on["safety"]["allowed"],
                },
            }
        )

    with open(os.path.join(HERE, "replay_objective_aware.json"), "w") as fh:
        json.dump(rows, fh, indent=2, default=str)

    # Console table
    print(
        f"{'id':8} | {'category':13} | {'objdomain':24} | "
        f"{'OFF rc-domain':22} {'conf':>5} | {'ON rc-domain':22} {'conf':>5} | "
        f"{'OFF→ON status':28} | acw O/N"
    )
    for r in rows:
        print(
            f"{r['investigation_id'][:8]} | {r['category'][:13]:13} | "
            f"{r['objective_domain'][:24]:24} | "
            f"{r['off']['cause_domain'][:22]:22} {r['off']['confidence']:5.1f} | "
            f"{r['on']['cause_domain'][:22]:22} {r['on']['confidence']:5.1f} | "
            f"{(r['off']['status']+'→'+r['on']['status'])[:28]:28} | "
            f"{int(r['off']['acw_ready'])}/{int(r['on']['acw_ready'])}"
        )


if __name__ == "__main__":
    main()
