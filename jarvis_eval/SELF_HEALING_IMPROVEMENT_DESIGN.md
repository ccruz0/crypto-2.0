# Jarvis Self-Healing — Next Improvement Design

**Status:** Design only. No code implemented, no PR, no ACW tasks, no production changes.
**Driver:** Production-quality evaluation of 18 real investigations (overall 4.81/10).
**Date:** 2026-06-20

This design targets the four diagnostic-quality findings from the evaluation **without touching the ACW gating**, which the evaluation found to be working correctly (1/18 ACW-ready, secrets blocked, never executes). The ACW layer (`backend/app/jarvis/self_healing/service.py`) is treated as a fixed downstream consumer that simply receives better inputs.

---

## 0. Current pipeline (read-only investigation findings)

Flow for a completed investigation:

1. **Objective intake** — `classify_investigation(objective)` (`backend/app/jarvis/investigations/investigation_types.py:319`) matches `INVESTIGATION_TEMPLATES` (first match wins) → `(category, template_id, template)`. Separately, `classify_investigation_objective(objective)` (`backend/app/jarvis/investigations/objective_classification.py:183`) → `InvestigationObjectiveType`, used **only** to pick a plan template. *Two unreconciled classifiers.*
2. **Evidence collection** — collectors run read-only tools; evidence normalized by `backend/app/jarvis/investigations/evidence_model.py`.
3. **Root-cause ranking** — `rank_root_causes(evidence, category, tool_outputs, recent_failures)` (`investigation_report.py:642`). Scores 10 hardcoded `_KNOWN_CAUSE_PATTERNS` via regex over an evidence *corpus*. Score = `category_bonus` (0 / +5 / +15) + 40 per corpus pattern hit + 15·weight per evidence-item hit + cross-source bonus (8–20) + recent_failures (≤15) + evidence_count (≤20), capped at 100.
4. **Report build** — `build_investigation_report(...)` (`investigation_report.py:789`) special-cases `authentication` and open-orders mismatch (hardcoded scores 96/92/90), then `root_cause = top.cause`, `confidence = top.score`, `recommended_fix = _lookup_fix_for_cause(...)` (`investigation_report.py:774`).
5. **Self-healing advisory** — `build_recommendation(...)` consumes the report; ACW gating already correct.

### Root cause of each evaluation finding (mapped to code)

| Finding | Mechanism in current code |
|--------|----------------------------|
| #1 Objective ignored | `rank_root_causes` uses only `category`; objective text/domain never enters ranking. |
| #2 Auth → order root causes | Auth collectors include `reconcile_crypto_com_open_orders`, so the evidence corpus contains order/trigger text; an order pattern hit (+40) beats a weak in-category bonus (+15). No domain gate; cross-domain causes compete freely. |
| #3 Overstated confidence | `confidence == additive match score` (capped 100) + hardcoded 96/92/90. Evidence count alone adds ≤20, cross-source ≤20, so circumstantial evidence reaches 90+. No notion of evidence strength, objective alignment, or specificity. |
| #4 Generic recommendations | `_lookup_fix_for_cause` fallback returns "Review collected evidence and implement targeted fix behind approval gate"; the "no mismatch" path returns "No repair needed". Concrete files/tests exist in `backend/app/jarvis/proposals/template_catalog.py` but are only used by the self-healing layer, not surfaced in the report. |
| #5 ACW gating correct | `self_healing/service.py` gating is strict and correct — **do not modify**. |

---

## Deliverable 1 — Objective-Aware Root Cause Selection (architecture)

### 1.1 New domain layer
New module `backend/app/jarvis/investigations/domains.py`:

```
class InvestigationDomain(str, Enum):
    EXCHANGE_AUTH = "exchange_auth"
    PORTFOLIO_RECONCILIATION = "portfolio_reconciliation"
    ORDER_RECONCILIATION = "order_reconciliation"
    OPEN_ORDERS = "open_orders"
    DATABASE = "database"
    DEPLOYMENT = "deployment"
    INFRASTRUCTURE = "infrastructure"
    PERFORMANCE = "performance"
    GENERIC = "generic"
```

`classify_domain(objective, category, template_id) -> DomainClassification` where
`DomainClassification = {domain, domain_confidence (0..1), matched_signals: list[str]}`.

- Deterministic, keyword/pattern based (reuse the existing regexes from `objective_classification.py` and the template→category map from `investigation_types.py`, **unified** into one domain output).
- `domain_confidence` reflects match strength: exact template match → 1.0; strong keyword hit → 0.7–0.9; weak/ambiguous → 0.3–0.5; no signal → `GENERIC` at 0.2.
- This replaces the "two classifiers" problem with a single source of truth that both ranking and confidence consume.

### 1.2 Tag causes and templates with a domain
- Add a `domain: InvestigationDomain` (or `domains: set`) field to each `_KNOWN_CAUSE_PATTERNS` entry and to each `FixTemplate` in `template_catalog.py`.
- Add `domain` to `RootCauseCandidate`.

### 1.3 Domain-relevance gating in `rank_root_causes`
Add a `DOMAIN_RELEVANCE[objective_domain][cause_domain] -> weight` matrix:

- **in-domain** (same) → weight **1.0** + alignment bonus.
- **adjacent** (curated allowed pairs, e.g. `open_orders ↔ order_reconciliation`, `database ↔ deployment`, `deployment ↔ infrastructure`) → weight **0.6**.
- **cross-domain** (e.g. `exchange_auth` objective vs `order_reconciliation` cause) → weight **0.2**, and **hard-blocked from becoming the selected root cause** unless (a) there is no in-domain candidate above the floor AND (b) direct high-confidence evidence of the cause's domain exists ("explicit evidence override").

`adjusted_score = base_score × DOMAIN_RELEVANCE[obj_domain][cause_domain]`. Rank by `adjusted_score`.

### 1.4 Selection rule (in `build_investigation_report`)
- Select highest `adjusted_score` candidate.
- If the best available candidate is cross-domain → set `objective_mismatch = True`, do **not** promote it; prefer the strongest in-domain candidate, else return `INSUFFICIENT_EVIDENCE` with `missing_evidence = ["No in-domain root cause for <domain>; evidence points to <other domain>"]`.
- Result: an `exchange_auth` investigation can no longer surface an order/trigger root cause (fixes #1, #2).

---

## Deliverable 2 — Confidence Calibration (architecture)

New module `backend/app/jarvis/investigations/confidence.py`. Replace "match score == confidence" with a **bounded multiplicative model** over four factors, each in `[0,1]`:

| Factor | Source | Definition |
|--------|--------|-----------|
| **E — Evidence strength** | `evidence_model` | f(independent_sources, direct high-confidence observations, substantive count, and whether *this cause's* supporting evidence is direct vs circumstantial). |
| **O — Objective alignment** | `domains.classify_domain` | `domain_confidence` × (selected-cause-domain == objective-domain ? 1 : partial). |
| **D — Domain match** | relevance matrix (Del. 1) | 1.0 in-domain, 0.6 adjacent, 0.2 cross. |
| **S — Recommendation specificity** | recommendation builder (Del. 3) | 1.0 if concrete files+commands+validation; ~0.5 partial; 0.1 generic-only. |

`raw = 100 × (wE·E + wO·O + wD·D + wS·S)` (weights summing to 1, e.g. 0.4/0.2/0.25/0.15), **then apply hard caps**:

- `D < 1.0` (any domain mismatch) → cap **50**.
- Evidence below "≥2 independent sources OR ≥1 direct high-confidence" → cap **40** (mirrors the existing insufficiency gate in `validate_investigation_report_fields`).
- Recommendation is generic-only (S low) → cap **60**.
- Non-meaningful root cause → **0** (already enforced; keep).

**Remove the hardcoded 96 / 92 / 90 literals** in `classify_open_orders_mismatch` and the auth branch; let a genuine, verified, in-domain 3-way count match earn a high score *through* high E/O/D rather than by fiat.

Emit a `ConfidenceBreakdown {E,O,D,S, raw, caps_applied, final}` stored in `synthesis` for transparency and future re-evaluation. **Guarantee:** weak evidence or domain mismatch can no longer yield 90–100 (fixes #3).

---

## Deliverable 3 — Recommendation Generation (architecture)

New module `backend/app/jarvis/investigations/recommendation_builder.py` producing a structured `RecommendationPlan`:

```
RecommendationPlan {
  proposed_fix: str
  affected_files: list[str]            # real paths
  commands: list[{description, command}]   # exact, read-only-first
  validation_steps: list[str]          # concrete, runnable
  risks: list[{description, severity, mitigation}]
  rollback: str
  specificity: float                   # feeds factor S
}
```

Concreteness sources, in priority order:
1. **Template-backed** — when a `_KNOWN_CAUSE_PATTERNS` entry / `FixTemplate` matches, emit its `target_files`, `test_paths`, and `validation_rules` as files + commands + validation. Promote `template_catalog.py` into the report layer (today only the self-healing layer reads it). Example for portfolio: files `backend/app/services/portfolio_cache.py`; command `grep -n "equity\|net_equity" backend/app/services/portfolio_cache.py`; validation `pytest backend/tests/test_portfolio_equity_field_discovery.py`.
2. **Evidence-derived files** — when no template matches, surface real `file_path` values already present in collected `repository` evidence items (mark as `candidate`), so recommendations point only at files actually seen.
3. **Generic-phrase ban** — a blocklist (`"review configuration"`, `"check settings"`, `"investigate further"`, `"review collected evidence"`, `"implement targeted fix"`, `"no repair needed"`). If the generated text reduces to banned-only content → set `specificity` low (caps confidence per Del. 2) and **replace the vague fix with an explicit gap statement**: "Insufficient evidence to produce a concrete fix; missing: <X>." Never present banned-only text as actionable (fixes #4).

Every actionable recommendation must carry **≥1 concrete file AND ≥1 validation step**, or it is downgraded to "insufficient" rather than shown as a fix.

---

## Deliverable 4 — Required code changes (enumeration; not implemented)

**New modules**
- `backend/app/jarvis/investigations/domains.py` — `InvestigationDomain`, `classify_domain`, `DOMAIN_RELEVANCE`.
- `backend/app/jarvis/investigations/confidence.py` — calibrated model + `ConfidenceBreakdown`.
- `backend/app/jarvis/investigations/recommendation_builder.py` — `RecommendationPlan` + generic-phrase guard.

**Modified (additive, behind a flag)**
- `investigation_report.py`: tag `_KNOWN_CAUSE_PATTERNS` with `domain`; add `domain` to `RootCauseCandidate`; apply domain gating in `rank_root_causes`; in `build_investigation_report` use calibrated confidence, structured recommendation, and `objective_mismatch` handling; remove hardcoded 96/92/90.
- `objective_classification.py` / `investigation_types.py`: expose unified mapping consumed by `domains.py` (or have `domains.py` import both). No behavior change when flag off.
- `proposals/template_catalog.py`: add `domain` to `FixTemplate` (read by both report and self-healing layers).
- `InvestigationReport` / `to_dict`: carry `domain`, `confidence_breakdown`, `recommendation_plan`. **Persistence:** store these inside existing `synthesis` / `ranked_causes_json` JSON columns first (zero migration); optional dedicated columns later.

**Explicitly NOT changed**
- `backend/app/jarvis/self_healing/service.py`, `assessment.py`, `safety_rules.py`, `config.py` — ACW gating untouched. It benefits automatically: better/meaningful `root_cause`, calibrated `confidence` vs the 70 threshold, and concrete `affected_files`.

---

## Deliverable 5 — Required tests (not the basis of evaluation; behavior locks)

- **Domain classifier**: each domain incl. the real eval objectives (e.g. "Investigate Crypto.com authentication failures" → `EXCHANGE_AUTH`; "Investigate portfolio reconciliation mismatch" → `PORTFOLIO_RECONCILIATION`).
- **Cross-domain gating**: auth investigation + order-cause evidence → order cause penalized/blocked; selected cause is in-domain or status `INSUFFICIENT_EVIDENCE`. Replays the failing eval cases `ec30b60b`, `d3fa6e63`.
- **Confidence calibration**: weak evidence → ≤40; domain mismatch → ≤50; generic recommendation → ≤60; verified in-domain 3-way match → high but justified; assert **no** 90–100 when E or D is low.
- **Recommendation**: every actionable plan has ≥1 file and ≥1 validation step; banned-phrase guard converts generic-only output to an explicit gap statement.
- **Replay harness** (real data): re-run the 18 evaluation investigations (`jarvis_eval/raw_investigations.json`) through the new pipeline; snapshot domains, selected root causes, confidence distribution, and the recomputed 5-category scores; assert no cross-domain root cause and a confidence distribution shift away from 90–100.
- **ACW invariance**: assert `acw_ready` for the 18 is unchanged or **stricter** (never newly enabled for a previously-weak case); confirm `service.py` is not imported-modified.

---

## Deliverable 6 — Rollout plan

1. **Phase 0 — flagged, off by default.** Land pure functions behind `JARVIS_OBJECTIVE_AWARE_RC=false`. Old path unchanged.
2. **Phase 1 — shadow compute.** With flag on in staging, compute new `domain`/`confidence_breakdown`/`recommendation_plan` and store in `synthesis`, but keep serving the old `root_cause`/`confidence`. Run the replay harness on live investigations for ~1–2 weeks; review diffs.
3. **Phase 2 — advisory switch (read-only).** Serve the new root cause + calibrated confidence + structured recommendation in the dashboard/advisory only. ACW still consumes the same fields but gating unchanged.
4. **Phase 3 — feed ACW.** Allow calibrated confidence to drive the existing (unchanged) 70 ACW threshold. Enable **per domain progressively**, starting with the most reliable (`portfolio_reconciliation`, `open_orders`) and ending with the least (`exchange_auth`).
5. **Kill switch:** the flag. Each phase gated on replay-harness sign-off.

---

## Deliverable 7 — Risks

| Risk | Mitigation |
|------|-----------|
| Over-penalizing a *legitimate* cross-domain cause (e.g., auth failure truly empties orders) | Adjacency matrix + "explicit evidence override": cross-domain allowed only with direct high-confidence evidence of that domain. |
| Domain misclassification cascades into wrong gating | `domain_confidence`; when low, widen allowed domains and fall back to `GENERIC` (no gating). |
| Confidence deflation pushes previously-"completed" investigations to `insufficient_evidence`, lowering ACW-ready count further | Intended trade-off (precision over recall); tune caps with the replay harness; ACW must stay strict. |
| Recommendation builder points at wrong files from repo evidence | Only surface files present in collected evidence or the template catalog; label inferred files `candidate`. |
| Maintenance burden of domain tags / relevance matrix | Centralize in `domains.py` with exhaustive tests; one place to edit. |
| Persistence/migration risk | Start with JSON piggyback (no migration); defer dedicated columns. |
| Behavior change risk to ACW | ACW code untouched + ACW-invariance test; phased rollout. |

---

## Deliverable 8 — Estimated impact on evaluation scores

Baseline (18 real investigations): **Overall 4.81** — RootCause 5.22, RecQuality 4.33, Scope 5.17, Risk 5.89, Actionability 3.44.

| Category | Baseline | Projected | Primary lever |
|----------|:--:|:--:|---------------|
| Root Cause Accuracy | 5.22 | **~7.0** | Domain gating fixes the 4 auth (2–3) and 2 generic (3) cases. |
| Recommendation Quality | 4.33 | **~6.5** | Concrete files/commands/validation; generic-phrase ban. |
| Scope Accuracy | 5.17 | **~6.8** | Template + evidence-derived real files on more cases. |
| Risk Assessment Accuracy | 5.89 | **~6.8** | Structured per-recommendation risks. |
| Actionability | 3.44 | **~6.5** | Exact commands + validation steps (biggest lever). |
| **Overall** | **4.81** | **~6.7** | |

Caveats: confidence calibration will likely move a few borderline investigations into `insufficient_evidence` (improving precision, possibly reducing the raw "completed" count). ACW-ready count is expected to stay ≈1–3 and only for genuinely strong, in-domain, template-backed cases (e.g., portfolio reconciliation) — consistent with the evaluation's "keep ACW gating strict" conclusion.

---

## Summary

- **A. Objective-aware selection:** a single `domains.py` classifier + per-cause domain tags + a domain-relevance matrix that penalizes (0.6) or blocks (0.2 / hard-block) cross-domain causes.
- **B. Confidence calibration:** a bounded 4-factor model (Evidence, Objective alignment, Domain match, Specificity) with hard caps that make 90–100 impossible under weak evidence or domain mismatch.
- **C. Recommendation quality:** a structured `RecommendationPlan` (files, commands, validation, risks) sourced from the template catalog + collected evidence, with a generic-phrase ban.
- ACW gating stays exactly as-is and only receives better inputs. Projected overall lift **4.81 → ~6.7**.
