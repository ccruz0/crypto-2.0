"""Run the REAL Jarvis self-healing recommendation engine over REAL production
investigations exported from the production database.

Read-only: no DB writes, no production access, no execution. We set
JARVIS_SELF_HEALING_ENABLED=true only in THIS process so that acw_ready reflects
what the advisor would emit if the flag were enabled in production. This does not
change any production configuration.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import types

os.environ.setdefault("JARVIS_SELF_HEALING_ENABLED", "true")
os.environ.setdefault("JARVIS_SELF_HEALING_ACW_THRESHOLD", "70")

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, BACKEND)

# The real engine logic lives in pure modules (assessment, recommendation,
# safety_rules, template_matching, template_catalog, execution.safety,
# investigation_types). They are stdlib-only. However, several package __init__
# files eagerly import the database/config layer (which requires production
# secrets). To run the REAL engine logic without touching the DB, we register
# lightweight package shims so that submodule imports resolve to the real source
# files while the heavy __init__ side effects are skipped.
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

# Now import the REAL leaf modules directly from source.
build_recommendation = importlib.import_module(
    "app.jarvis.self_healing.service"
).build_recommendation

HERE = os.path.dirname(__file__)


def main() -> None:
    with open(os.path.join(HERE, "raw_investigations.json")) as fh:
        investigations = json.load(fh)

    out = []
    for inv in investigations:
        rec = build_recommendation(inv)
        out.append(
            {
                "investigation_id": inv["investigation_id"],
                "objective": inv["objective"],
                "category": inv["category"],
                "template_id": inv["template_id"],
                "status": inv["status"],
                "confidence_stored": float(inv.get("confidence") or 0),
                "root_cause": inv.get("root_cause"),
                "recommended_fix": inv.get("recommended_fix"),
                "impact": inv.get("impact"),
                "evidence_count": len(inv.get("evidence_json") or []),
                "ranked_causes": inv.get("ranked_causes_json") or [],
                # REAL engine outputs:
                "assessment": rec["assessment"],
                "recommendation": rec["recommendation"],
                "acw": rec["acw"],
                "safety": rec["safety"],
                "proposed_fix": rec["proposed_fix"],
                "affected_files": rec["affected_files"],
                "estimated_risk": rec["estimated_risk"],
                "acw_ready": rec["acw_ready"],
                "available_actions": rec["available_actions"],
            }
        )

    with open(os.path.join(HERE, "recommendations.json"), "w") as fh:
        json.dump(out, fh, indent=2, default=str)

    # Console summary
    for r in out:
        print(
            f"{r['investigation_id'][:8]} | {r['category']:14s} | {r['template_id']:34s} "
            f"| conf={r['confidence_stored']:5.1f} | risk={r['estimated_risk']:6s} "
            f"| files={len(r['affected_files'])} | acw_ready={r['acw_ready']} "
            f"| tmpl={r['recommendation']['has_template']} "
            f"| reasons={','.join(r['acw']['reasons']) or '-'}"
        )


if __name__ == "__main__":
    main()
