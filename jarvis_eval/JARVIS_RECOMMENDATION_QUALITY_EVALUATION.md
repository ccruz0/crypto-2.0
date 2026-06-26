# Jarvis Recommendation Quality Evaluation

**Scope:** Quality and accuracy of Jarvis Self-Healing Advisor recommendations, measured against **real completed production investigations**.
**Mode:** Evaluation only. No production changes, no deploys, no merges, no PRs, no ACW tasks created.
**Date:** 2026-06-20

---

## How this evaluation was produced (real data, real engine)

1. **Real investigations** were read from the production Postgres database (`jarvis_investigations` table, 144 completed investigations). A representative sample of **18 completed investigations** was exported (`raw_investigations.json`), spanning all required types.
2. The deployed backend image predates the Phase 7 self-healing module, so the **real recommendation engine from the workspace** (`app/jarvis/self_healing/*`, `app/jarvis/proposals/*`) was run against each real investigation to produce the **actual recommendation outputs** (`recommendations.json`) — affected files, estimated risk, ACW-readiness, safety verdicts. The engine was run with `JARVIS_SELF_HEALING_ENABLED=true` **in the evaluation process only** (production config untouched) so that `acw_ready` reflects what the advisor would emit if enabled.
3. Each recommendation was scored against **its own collected evidence** (`evidence_view.md`). Scores and per-record rationale are in `evaluation_records.json`.

No scores are based on unit tests; only on real investigation outputs and real recommendations.

**Artifacts:** `raw_investigations.json` · `recommendations.json` · `evidence_view.md` · `evaluation_records.json` · `run_recommendations.py` · `score_and_aggregate.py`

---

## 1. Investigations evaluated (18, across all required types)

| # | ID (short) | Type bucket | Objective | Category/Template | Conf | ACW-ready |
|---|-----------|-------------|-----------|-------------------|------|-----------|
| 1 | 5b76cf57 | order reconciliation | Investigate portfolio reconciliation mismatch | portfolio / portfolio_reconciliation_mismatch | 90.5 | **yes** |
| 2 | f79b9ffc | order reconciliation | Dashboard showing zero while exchange had one | dashboard / dashboard_exchange_mismatch | 90.0 | no |
| 3 | a5439a76 | order reconciliation | Why are executed orders missing? (BTC) | orders / executed_orders_missing | 100.0 | no |
| 4 | e080e0d0 | order reconciliation | Why are my open orders different from Crypto.com? | dashboard / dashboard_exchange_mismatch | 96.0 | no |
| 5 | 4fcd9e28 | order reconciliation | Why open orders show 0 in dashboard | dashboard / open_orders_zero_dashboard | 96.0 | no |
| 6 | 2616ea25 | order reconciliation | BTC orders missing from dashboard | dashboard / dashboard_exchange_mismatch | 96.0 | no |
| 7 | 3f35a4d6 | order reconciliation | Why are open orders empty? | orders / open_orders_empty | 96.0 | no |
| 8 | a6cf648c | exchange auth | Investigate Crypto.com auth failures | authentication / exchange_auth_failing | 48.0 | no |
| 9 | 7652e662 | exchange auth | Investigate Crypto.com auth failures | authentication / exchange_auth_failing | 48.0 | no |
| 10 | ec30b60b | exchange auth | Investigate Crypto.com auth failures | authentication / exchange_auth_failing | 90.0 | no |
| 11 | d3fa6e63 | exchange auth | Investigate Crypto.com auth failures | authentication / exchange_auth_failing | 100.0 | no |
| 12 | 9c6c5879 | deployment health | Check database health and query errors | deployment / generic | 50.0 | no |
| 13 | 99e5946a | deployment health | Why is Jarvis task failing? | api / jarvis_task_failing | 27.0 | no |
| 14 | fe5f566e | signal monitor | Why are websocket prices stale? | websocket / websocket_prices_stale | 63.0 | no |
| 15 | cd4b339b | alert investigation | Analyze recent error logs for incidents | api / generic | 27.0 | no |
| 16 | ada36c20 | alert investigation | Why does dashboard differ from exchange? | dashboard / dashboard_exchange_mismatch | 96.0 | no |
| 17 | c7eae0f4 | image investigation | Why are open orders empty? (UI screenshot) | orders / open_orders_empty | 96.0 | no |
| 18 | 5cb222df | image investigation | Why are open orders empty? (UI screenshot) | orders / open_orders_empty | 96.0 | no |

Each row has a full evaluation record (objective, investigation type, evidence collected, root cause, recommendation, confidence, severity, affected files, ACW-ready) in `evaluation_records.json`.

---

## 2. Scoring rubric

Each recommendation scored 0–10 on five categories:

- **A. Root Cause Accuracy** — did the root cause actually match the evidence?
- **B. Recommendation Quality** — would an engineer find it useful?
- **C. Scope Accuracy** — are the proposed files/components correct?
- **D. Risk Assessment Accuracy** — was the risk estimate realistic?
- **E. Actionability** — could someone implement it without further investigation?

## 3. Per-investigation scores

| ID | Type | A RootCause | B RecQual | C Scope | D Risk | E Action | Overall |
|----|------|:--:|:--:|:--:|:--:|:--:|:--:|
| 5b76cf57 | order recon | 9 | 9 | 9 | 8 | 8 | **8.6** |
| ada36c20 | alert | 7 | 4 | 6 | 7 | 3 | 5.4 |
| 3f35a4d6 | order recon | 7 | 4 | 6 | 7 | 3 | 5.4 |
| a5439a76 | order recon | 7 | 6 | 4 | 5 | 4 | 5.2 |
| f79b9ffc | order recon | 8 | 4 | 4 | 6 | 3 | 5.0 |
| e080e0d0 | order recon | 6 | 4 | 6 | 6 | 3 | 5.0 |
| 4fcd9e28 | order recon | 6 | 4 | 6 | 6 | 3 | 5.0 |
| 2616ea25 | order recon | 6 | 4 | 6 | 6 | 3 | 5.0 |
| c7eae0f4 | image | 6 | 4 | 6 | 6 | 3 | 5.0 |
| 5cb222df | image | 6 | 4 | 6 | 6 | 3 | 5.0 |
| fe5f566e | signal monitor | 5 | 5 | 3 | 6 | 5 | 4.8 |
| 9c6c5879 | deployment | 5 | 5 | 4 | 5 | 4 | 4.6 |
| a6cf648c | exchange auth | 3 | 4 | 5 | 6 | 3 | 4.2 |
| 7652e662 | exchange auth | 3 | 4 | 5 | 6 | 3 | 4.2 |
| d3fa6e63 | exchange auth | 2 | 4 | 5 | 5 | 3 | 3.8 |
| 99e5946a | deployment | 3 | 3 | 4 | 5 | 3 | 3.6 |
| cd4b339b | alert | 3 | 3 | 4 | 5 | 3 | 3.6 |
| ec30b60b | exchange auth | 2 | 3 | 4 | 5 | 2 | 3.2 |

---

## 4. Overall scores

### Average score per category (n=18)

| Category | Average / 10 |
|----------|:--:|
| Root Cause Accuracy | **5.22** |
| Recommendation Quality | **4.33** |
| Scope Accuracy | **5.17** |
| Risk Assessment Accuracy | **5.89** |
| Actionability | **3.44** |
| **Overall average** | **4.81** |

### Top 5 strongest recommendations
1. **5b76cf57** — portfolio reconciliation mismatch — **8.6** (only ACW-ready record; evidence-grounded, correct single file)
2. **ada36c20** — dashboard differs from exchange — **5.4** (counts genuinely matched; accurate "no mismatch")
3. **3f35a4d6** — open orders empty — **5.4** (all counts matched; accurate verdict)
4. **a5439a76** — executed orders missing — **5.2** (DB evidence supports trade-history hypothesis)
5. **f79b9ffc** — dashboard zero vs exchange one — **5.0** (strong root cause; weak recommendation text)

### Top 5 weakest recommendations
1. **ec30b60b** — auth investigation → returned an *orders-cache* root cause at confidence 90 — **3.2**
2. **99e5946a** — "Jarvis task failing" → canned *trade-history* root cause, no failure evidence — **3.6**
3. **cd4b339b** — "analyze error logs" → 0 logs found, yet asserted trade-history root cause — **3.6**
4. **d3fa6e63** — auth investigation → *trigger-order* root cause at confidence 100 — **3.8**
5. **7652e662** — auth → "credentials missing" while evidence shows credentials present — **4.2**

### Most / least reliable investigation types

| Type | n | Overall | RootCause | Actionability |
|------|:-:|:-:|:-:|:-:|
| order reconciliation | 7 | **5.6** | **7.0** | 3.86 |
| image investigation | 2 | 5.0 | 6.0 | 3.0 |
| signal monitor | 1 | 4.8 | 5.0 | 5.0 |
| alert investigation | 2 | 4.5 | 5.0 | 3.0 |
| deployment health | 2 | 4.1 | 4.0 | 3.5 |
| **exchange auth** | 4 | **3.85** | **2.5** | 2.75 |

- **Most reliable:** order reconciliation (esp. `portfolio_reconciliation_mismatch` and genuine count-match verdicts).
- **Least reliable:** exchange authentication, then deployment health and generic "alert" objectives.

---

## 5. Patterns identified (weaknesses)

1. **Objective is ignored when selecting the root cause.** "Objective-aware" routing picks a category/template, but the *diagnosed root cause* is the highest-scoring generic candidate regardless of the question asked. Authentication investigations returned order-cache (ec30b60b, conf 90) and trigger-order (d3fa6e63, conf 100) root causes; "Jarvis task failing" and "analyze error logs" both returned the canned "FILLED orders not displayed in trade history." (Evidence: ranked-cause lists in `evidence_view.md` — auth-relevant cause ranked last at 48 while an unrelated cause wins.)

2. **Confidence is miscalibrated / systematically overconfident.** Confidence 96–100 is attached to (a) non-meaningful root causes ("No active dashboard/exchange mismatch detected," 7 cases at 96) and (b) wrong-domain answers (d3fa6e63 at 100, ec30b60b at 90). Confidence does not track correctness or whether a meaningful root cause exists.

3. **Generic / placeholder recommendations.** "Review collected evidence and implement targeted fix behind approval gate" (f79b9ffc, ec30b60b) and "No repair needed" carry no actionable content. Recommendation Quality (4.33) and Actionability (3.44) are the two lowest categories.

4. **Root cause contradicting evidence (auth false positive).** a6cf648c / 7652e662 conclude "credentials missing or misconfigured" while the evidence shows `EXCHANGE_CREDENTIAL_WARNINGS=NO`, key/secret presence flags set, and a working private API (dashboard=5). The only supporting signal is "runtime.env contains 2 secret lines."

5. **Affected files usually unknown.** Only 3/18 produced affected files (template matched); 15/18 emit no file scope, which caps actionability — most recommendations require a fresh investigation to implement.

6. **Image investigations add no incremental signal.** Both image cases captured `[image] UI screenshot` with no OCR text or extracted entities feeding the diagnosis; the conclusion is identical to the text-only open-orders cases. The image-driven path currently contributes an evidence row but no diagnostic value.

7. **Template ↔ recommendation mismatch.** Websocket (fe5f566e): template files point at `frontend/src/lib/priceStreamWsUrl.ts` (same-origin URL regression) while the recommendation text says "restart market-updater service" (backend ops). Files and proposed action disagree.

8. **No deduplication of near-identical investigations.** a6cf648c/7652e662 and c7eae0f4/5cb222df are duplicate runs seconds apart producing identical output.

9. **(Positive) ACW-readiness is NOT excessive — it is appropriately strict.** Only **1/18** is ACW-ready. Auth/secrets are correctly safety-blocked; generic/non-meaningful root causes are correctly excluded (`missing_root_cause`, `not_fixable`, `affected_files_unknown`); below-threshold confidence is excluded. The advisor never executes, merges, or deploys. This is the system's strongest property.

---

## 6. Improvement proposals

| # | Weakness | Root cause | Proposed improvement | Expected benefit |
|---|----------|-----------|----------------------|------------------|
| 1 | Wrong-domain root causes | Root-cause ranking ignores the objective/category | Constrain or down-weight ranked causes to the objective's domain; if the top cause is outside the objective domain, lower confidence and flag `objective_mismatch` | Auth/deployment investigations stop returning order-cache answers; raises RootCause accuracy for the weakest types |
| 2 | Overconfidence | Confidence not tied to evidence strength or meaningfulness | Cap confidence when `has_meaningful_root_cause` is false; scale confidence by (top cause score − runner-up score) separation | Confidence 96 on "nothing to fix" / wrong-domain disappears; calibration usable as an ACW gate |
| 3 | Generic / placeholder recommendations | Fallback text used when no template matches | Replace placeholders with evidence-derived, component-specific guidance; suppress recommendations that contain only placeholder phrasing | Recommendation Quality and Actionability rise from the lowest categories |
| 4 | Auth credential false positive | "2 secret lines" treated as auth failure despite contrary signals | Require a real auth-failure signal (40101, private-API failure) before asserting a credential root cause; treat "warnings=NO + private API ok" as exonerating | Removes misleading credential recommendations on healthy auth |
| 5 | Files usually unknown | Catalog of 8 templates is too small | Expand fix-template catalog for common categories (deployment, trade-history display, websocket staleness) so more investigations resolve to concrete files | More recommendations become scoped and actionable |
| 6 | Image path adds nothing | OCR/entities not wired into root-cause logic | Feed OCR text + extracted entities into evidence scoring, or stop labelling image runs as image-driven if unused | Image investigations earn their classification or are de-scoped |
| 7 | Template/recommendation mismatch | Recommendation text and template files chosen independently | Validate that recommendation verbs match the template's target layer (frontend vs backend/ops) | Removes contradictory file-vs-action guidance |
| 8 | Duplicate investigations | No dedup of identical objective+evidence | Hash objective + evidence fingerprint and reuse prior result | Less noise; clearer signal for operators |

---

## 7. Final Report

### Executive Summary
Across **18 real completed production investigations**, the Jarvis Self-Healing Advisor produces recommendations of **mixed and generally low-to-moderate quality (overall 4.81/10)**. The advisor's **safety posture is excellent**: only **1 of 18** recommendations was ACW-ready, sensitive domains (credentials/secrets) were correctly blocked, non-meaningful root causes were correctly excluded, and the advisor never executes, merges, or deploys. However, the **diagnostic quality of the recommendations themselves is not yet dependable**: root causes frequently ignore the stated objective, confidence is systematically overstated (96–100 on "nothing to fix" and wrong-domain answers), and the recommendation text is often generic and not directly implementable.

### Recommendation Quality Score: **4.33 / 10**
Dominated by placeholder/"no repair needed" text; only the portfolio template produced a genuinely useful, specific recommendation.

### Root Cause Accuracy Score: **5.22 / 10**
Strong for portfolio reconciliation and genuine count-match verdicts (7–9); poor for authentication (2–3, wrong-domain or evidence-contradicting) and generic objectives.

### Actionability Score: **3.44 / 10**
The lowest category. 15/18 recommendations have no file scope and/or generic text, so an engineer would still need to investigate before acting.

### Most Reliable Investigation Types
- **Order reconciliation** (overall 5.6; root-cause 7.0), especially **`portfolio_reconciliation_mismatch`** (the single ACW-ready, evidence-grounded, correctly-scoped case) and genuine "counts match" verdicts.

### Least Reliable Investigation Types
- **Exchange authentication** (overall 3.85; root-cause **2.5**) — wrong-domain root causes at confidence 90–100, plus credential false positives.
- **Deployment health** and **generic "alert" objectives** — canned trade-history root cause regardless of evidence; honest low confidence is the only saving grace.
- **Image investigations** — accurate by inheritance but add no incremental diagnostic value.

### Recommendations For Improvement
Priority order: (1) make root-cause selection objective-aware and (2) calibrate confidence to evidence strength — these two fixes address the weakest types and the most dangerous failure mode (high confidence on wrong answers). Then (3) eliminate placeholder recommendations, (4) fix the auth credential false positive, and (5) expand the fix-template catalog to improve scope/actionability. See §6 for root cause → improvement → expected benefit.

### Go / No-Go: Enabling Self-Healing Advisor in production

**Verdict: NEEDS MORE VALIDATION.**

- **Safe to keep enabled in advisory / shadow mode** (read-only recommendation generation). The advisor cannot act, the ACW path requires two human approval gates, and ACW-readiness is appropriately strict (1/18). There is no production-safety reason to forbid it from generating advisory output.
- **NOT ready for broad / automatic ACW-task creation.** Recommendation quality (4.33), actionability (3.44), and root-cause accuracy on auth/deployment/generic objectives are too low, and confidence is miscalibrated — so automatically turning recommendations into ACW tasks across categories would mostly create low-value or misdirected work. Only `portfolio_reconciliation_mismatch` currently meets the bar.

**Suggested path:** keep self-healing advisory-only (no auto-ACW); optionally allow ACW creation **only** for the `portfolio_reconciliation_mismatch` template as a controlled pilot; implement improvements §6.1, §6.2, §6.3; then re-run this evaluation on a fresh sample before widening.

**Final recommendation: `NEEDS MORE VALIDATION`.**
