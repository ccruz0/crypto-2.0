"""Build evaluation records from REAL recommendation outputs and REAL evidence.

Scores are assigned by analyst judgement, each grounded in the investigation's
own evidence (see `rationale`). This script merges those scores with the real
engine outputs (recommendations.json) and computes the aggregate metrics
required by the evaluation.
"""

from __future__ import annotations

import json
import os
import statistics

HERE = os.path.dirname(__file__)

# Required-type bucket for each investigation (for "most/least reliable type").
TYPE_BUCKET = {
    "5b76cf57-80e6-45d0-8640-de0263777864": "order reconciliation",
    "f79b9ffc-c553-4e58-a41b-3ee63a5bd30c": "order reconciliation",
    "a5439a76-d6ce-4b2f-900a-f649ed1c45e1": "order reconciliation",
    "e080e0d0-e746-4fcd-8f2d-22f54733f223": "order reconciliation",
    "4fcd9e28-22b1-43f2-886a-cf21466bc2bb": "order reconciliation",
    "2616ea25-b02f-40d1-a8b6-91667e9323c9": "order reconciliation",
    "3f35a4d6-b8c4-4422-94d4-106daa77c904": "order reconciliation",
    "a6cf648c-e91a-463a-91d9-5ed492828cff": "exchange auth",
    "7652e662-957b-4200-98a2-91bcdc52e9dd": "exchange auth",
    "ec30b60b-aeaa-492b-a67b-f23c9fccf235": "exchange auth",
    "d3fa6e63-9b96-4822-8181-3ff1be2bd85a": "exchange auth",
    "9c6c5879-ad3d-4f0b-91e9-0d38b7e5ca80": "deployment health",
    "99e5946a-82f1-42fa-a95a-37e03a68e2f9": "deployment health",
    "fe5f566e-00ea-4065-acc6-409fd2e2a162": "signal monitor",
    "cd4b339b-6cac-4bc2-aed2-8f7403a35961": "alert investigation",
    "ada36c20-8323-4160-9d2e-17dbf8cfdca2": "alert investigation",
    "c7eae0f4-2522-41a3-b52a-7d8e0b356892": "image investigation",
    "5cb222df-8007-4a0f-91df-b91dee0bac16": "image investigation",
}

# scores: [root_cause_accuracy, recommendation_quality, scope_accuracy,
#          risk_assessment_accuracy, actionability]  (each 0-10)
SCORES = {
    "5b76cf57-80e6-45d0-8640-de0263777864": {
        "s": [9, 9, 9, 8, 8],
        "rationale": "Evidence 'Exchange equity fields found: accounts[].market_value' directly supports the root cause (exchange omits a top-level equity field, so equity is derived from balances). Top cause 90.5 vs runner-ups 26.0 = clear separation. Template maps to backend/app/services/portfolio_cache.py (correct, single file), low risk, ACW-ready. Recommendation names the concrete change (map get_account_summary equity/net_equity). Minor: exact field path still needs a quick code lookup.",
    },
    "f79b9ffc-c553-4e58-a41b-3ee63a5bd30c": {
        "s": [8, 4, 4, 6, 3],
        "rationale": "Root cause (cache empty, dashboard serves DB fallback) is well evidenced: cache_raw=0, source=database_fallback, exchange=1/db=1/dashboard=0. But recommended_fix is the placeholder 'Review collected evidence and implement targeted fix behind approval gate' -> no actionable content, no files, despite open_orders_cache/routes_dashboard being known components.",
    },
    "a5439a76-d6ce-4b2f-900a-f649ed1c45e1": {
        "s": [7, 6, 4, 5, 4],
        "rationale": "DB evidence FILLED=149 supports 'FILLED orders exist but trade history does not display them' and it matches the objective. Direction (verify trade-history API + frontend render) is reasonable but no files are named; confidence 100 is overconfident for a display-layer hypothesis with no UI evidence captured.",
    },
    "9c6c5879-ad3d-4f0b-91e9-0d38b7e5ca80": {
        "s": [5, 5, 4, 5, 4],
        "rationale": "Health check evidence says status=pass while a log line shows 'ERROR: No backend container running'. Root cause 'Deployment health check failing' is only partially supported (mixed signals). 'Inspect container logs and restore failing service' is generic but appropriate for a deployment check; no files (acceptable for infra).",
    },
    "fe5f566e-00ea-4065-acc6-409fd2e2a162": {
        "s": [5, 5, 3, 6, 5],
        "rationale": "Thin evidence: factory.py websocket code refs + health=fail; no direct staleness metric. Templated root cause 'feed disconnected'. SCOPE MISMATCH: template files are frontend/src/lib/priceStreamWsUrl.ts (same-origin URL regression) yet the recommendation text says 'restart market-updater service' (backend ops). Files and recommended action disagree.",
    },
    "e080e0d0-e746-4fcd-8f2d-22f54733f223": {
        "s": [6, 4, 6, 6, 3],
        "rationale": "Exchange=5/DB=2/dashboard=5: dashboard matches exchange, so 'no active dashboard/exchange mismatch' is defensible, but it dismisses 6 reconciliation discrepancies, DB lag, and a persistent trigger-order 50001 error. Root cause is non-meaningful (generic) so engine correctly emits no files / not ACW-ready, but confidence 96 is far too high for a 'nothing to fix' verdict.",
    },
    "4fcd9e28-22b1-43f2-886a-cf21466bc2bb": {
        "s": [6, 4, 6, 6, 3],
        "rationale": "Objective 'open orders show 0' but evidence shows dashboard_effective=5 via crypto_com_api (ok). 'No active mismatch' is defensible vs live counts, but the objective's symptom isn't reproduced/explained. Generic root cause -> no files, not ACW-ready (correct), yet confidence 96 unjustified.",
    },
    "2616ea25-b02f-40d1-a8b6-91667e9323c9": {
        "s": [6, 4, 6, 6, 3],
        "rationale": "Objective 'BTC orders missing from dashboard' but Exchange=5/dashboard=5 match; 'no active mismatch' defensible against live counts but does not address the reported BTC symptom. Generic root cause -> no files/not ACW-ready (correct); confidence 96 overstated.",
    },
    "ada36c20-8323-4160-9d2e-17dbf8cfdca2": {
        "s": [7, 4, 6, 7, 3],
        "rationale": "Exchange=5/DB=5/dashboard=5 all genuinely match, so 'no active mismatch detected' is accurate and impact 'Low' is correct. But it offers no action (only 'monitor 50001 separately') and ignores the recurring trigger 50001. Confidence 96 acceptable for the match verdict but still attached to a non-meaningful root-cause label.",
    },
    "3f35a4d6-b8c4-4422-94d4-106daa77c904": {
        "s": [7, 4, 6, 7, 3],
        "rationale": "Exchange=5/DB=5/dashboard=5 match and 'Open orders exist in database and cache' is in evidence; 'no active mismatch' accurate, impact correct. No actionable output; trigger 50001 left unaddressed.",
    },
    "c7eae0f4-2522-41a3-b52a-7d8e0b356892": {
        "s": [6, 4, 6, 6, 3],
        "rationale": "Image investigation: evidence includes '[image] UI screenshot' but no OCR text or extracted entities feed the analysis; conclusion is identical to the text-only open-orders-empty cases (dashboard=exchange=5). The image adds an evidence row but contributes no incremental diagnostic signal. Generic root cause -> no files/not ACW-ready (correct); confidence 96 overstated.",
    },
    "5cb222df-8007-4a0f-91df-b91dee0bac16": {
        "s": [6, 4, 6, 6, 3],
        "rationale": "Image investigation run seconds after c7eae0f4 with identical output. Image evidence ('UI screenshot') again carries no OCR/entities and does not change the diagnosis. No dedup of near-identical investigations.",
    },
    "a6cf648c-e91a-463a-91d9-5ed492828cff": {
        "s": [3, 4, 5, 6, 3],
        "rationale": "Root cause 'credentials missing or misconfigured' CONTRADICTS the evidence: EXCHANGE_CREDENTIAL_WARNINGS=NO, KEY_PRESENT/SECRET_PRESENT flags set, and dashboard=5 (private API working). Only weak signal is 'runtime.env contains 2 secret lines'. Confidence 48 is appropriately low. Safety correctly blocks (secrets domain) so not ACW-ready -> good safety, weak diagnosis.",
    },
    "7652e662-957b-4200-98a2-91bcdc52e9dd": {
        "s": [3, 4, 5, 6, 3],
        "rationale": "Duplicate of a6cf648c (same objective, same evidence shape, same output). Same evidence contradiction (creds present, no warnings). Confidence 48 honest; safety-blocked. Demonstrates lack of dedup and the credential false-positive pattern.",
    },
    "ec30b60b-aeaa-492b-a67b-f23c9fccf235": {
        "s": [2, 3, 4, 5, 2],
        "rationale": "Objective is authentication, but the selected root cause is 'Open orders cache empty but dashboard API serves DB fallback' (orders domain). The auth-relevant cause is ranked LAST (48) while an unrelated order cause wins (90). Confidence 90 on a wrong-domain answer = strongly overconfident. Recommendation is the generic placeholder. Objective-awareness failure.",
    },
    "d3fa6e63-9b96-4822-8181-3ff1be2bd85a": {
        "s": [2, 4, 5, 5, 3],
        "rationale": "Objective is authentication, but root cause is 'Trigger order API failure blocks cache updates' (orders) at confidence 100. The trigger fix itself is real (template -> 3 correct files for a trigger issue), but it is mis-scoped onto an auth investigation. Confidence 100 wildly overconfident for wrong-domain. Safety correctly blocks -> not ACW-ready.",
    },
    "cd4b339b-6cac-4bc2-aed2-8f7403a35961": {
        "s": [3, 3, 4, 5, 3],
        "rationale": "Objective 'analyze recent error logs' but evidence shows match_count=0 (NO error logs found). Root cause 'FILLED orders not displayed in trade history' is unrelated to the (empty) log search. All ranked causes tied at 27 = no real signal; confidence 27 is honest. Recommendation generic.",
    },
    "99e5946a-82f1-42fa-a95a-37e03a68e2f9": {
        "s": [3, 3, 4, 5, 3],
        "rationale": "Objective 'Why is Jarvis task failing?' but evidence shows 'No log matches for jarvis/task/failed/error'. Root cause is the canned 'FILLED orders not displayed' (unrelated). No evidence of any task failure was found, yet a root cause is asserted. Confidence 27 honest. Objective-awareness failure on a deployment/ops question.",
    },
}


def main() -> None:
    with open(os.path.join(HERE, "recommendations.json")) as fh:
        recs = {r["investigation_id"]: r for r in json.load(fh)}

    cats = [
        "root_cause_accuracy",
        "recommendation_quality",
        "scope_accuracy",
        "risk_assessment_accuracy",
        "actionability",
    ]

    records = []
    for inv_id, sc in SCORES.items():
        r = recs[inv_id]
        scores = dict(zip(cats, sc["s"]))
        overall = round(sum(sc["s"]) / 5, 2)
        records.append(
            {
                "investigation_id": inv_id,
                "type_bucket": TYPE_BUCKET[inv_id],
                "objective": r["objective"],
                "investigation_type": f"{r['category']} / template={r['template_id']}",
                "evidence_collected": f"{r['evidence_count']} evidence items",
                "root_cause": r["root_cause"],
                "recommendation": r["proposed_fix"] or r["recommended_fix"],
                "confidence": r["confidence_stored"],
                "severity": r["assessment"]["severity"],
                "affected_files": r["affected_files"],
                "estimated_risk": r["estimated_risk"],
                "has_template": r["recommendation"]["has_template"],
                "acw_ready": r["acw_ready"],
                "acw_block_reasons": r["acw"]["reasons"],
                "safety_allowed": r["safety"]["allowed"],
                "scores": scores,
                "overall_score": overall,
                "rationale": sc["rationale"],
            }
        )

    # Aggregates
    cat_avg = {c: round(statistics.mean(rec["scores"][c] for rec in records), 2) for c in cats}
    overall_avg = round(statistics.mean(rec["overall_score"] for rec in records), 2)

    ranked = sorted(records, key=lambda x: x["overall_score"], reverse=True)
    top5 = [
        {"investigation_id": r["investigation_id"], "type": r["type_bucket"],
         "objective": r["objective"], "overall_score": r["overall_score"]}
        for r in ranked[:5]
    ]
    bottom5 = [
        {"investigation_id": r["investigation_id"], "type": r["type_bucket"],
         "objective": r["objective"], "overall_score": r["overall_score"]}
        for r in ranked[-5:]
    ]

    # Per-type averages
    type_avg = {}
    buckets = sorted({r["type_bucket"] for r in records})
    for b in buckets:
        rs = [r for r in records if r["type_bucket"] == b]
        type_avg[b] = {
            "n": len(rs),
            "overall": round(statistics.mean(r["overall_score"] for r in rs), 2),
            "root_cause_accuracy": round(statistics.mean(r["scores"]["root_cause_accuracy"] for r in rs), 2),
            "actionability": round(statistics.mean(r["scores"]["actionability"] for r in rs), 2),
        }

    summary = {
        "n_investigations": len(records),
        "n_acw_ready": sum(1 for r in records if r["acw_ready"]),
        "category_averages": cat_avg,
        "overall_average": overall_avg,
        "top5_strongest": top5,
        "top5_weakest": list(reversed(bottom5)),
        "per_type_averages": type_avg,
    }

    out = {"summary": summary, "records": records}
    with open(os.path.join(HERE, "evaluation_records.json"), "w") as fh:
        json.dump(out, fh, indent=2)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
