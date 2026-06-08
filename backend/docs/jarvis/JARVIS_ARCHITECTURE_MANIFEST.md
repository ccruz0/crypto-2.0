# Jarvis Architecture Manifest

> Reconciliation snapshot: 2026-06-08  
> Branch: `perico-autonomy-pr1` @ `68cd2bd`  
> PROD: `automated-trading-platform-backend-aws-1` (healthy)  
> Goal: git must reproduce the full Jarvis platform currently running in production.

---

## Layer Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         REPORTING & ALERTS LAYER                         │
│  executive_report_service · telegram_*_alerts · weekly report scheduler │
└─────────────────────────────────────────────────────────────────────────┘
                                    ▲
┌─────────────────────────────────────────────────────────────────────────┐
│                         STRATEGY LAYER                                   │
│  objectives · key_results · kr_refresh · objective_analytics           │
└─────────────────────────────────────────────────────────────────────────┘
                                    ▲
┌─────────────────────────────────────────────────────────────────────────┐
│                         DECISION LAYER                                   │
│  decision_service · decision_analytics · decision_persistence            │
└─────────────────────────────────────────────────────────────────────────┘
                                    ▲
┌─────────────────────────────────────────────────────────────────────────┐
│                         MANAGEMENT LAYER                                 │
│  chief_of_staff · followups · initiatives · action_planner               │
└─────────────────────────────────────────────────────────────────────────┘
                                    ▲
┌─────────────────────────────────────────────────────────────────────────┐
│                         AUDITOR LAYER                                    │
│  aws_auditor · crypto_auditor · wallet_reconciliation · metrics          │
└─────────────────────────────────────────────────────────────────────────┘
                                    ▲
┌─────────────────────────────────────────────────────────────────────────┐
│                         MVP EXECUTION LAYER (LangGraph)                  │
│  service · graph · agents · tools · risk · persistence (task_runs)      │
└─────────────────────────────────────────────────────────────────────────┘
                                    ▲
┌─────────────────────────────────────────────────────────────────────────┐
│                         LEGACY ORCHESTRATION                             │
│  orchestrator · planner · telegram_control · perico_mission · marketing  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Auditors

### AWS Auditor

| Component | Path | Role |
|-----------|------|------|
| Agent | `mvp/aws_auditor.py` | Task detection, audit orchestration |
| Tools | `mvp/aws_auditor_tools.py` | Read-only AWS inventory (EC2, EBS, EIP, SG, costs) |
| Persistence | `mvp/audit_persistence.py` | `jarvis_audit_runs` CRUD |
| Alerts | — | Via action planner / executive dashboard |

**Triggers:** LangGraph task (`is_aws_audit_task`), KR metric resolver, executive dashboard collector.

### Crypto Auditor

| Component | Path | Role |
|-----------|------|------|
| Agent | `mvp/crypto_auditor.py` | Crypto audit task routing |
| Tools | `mvp/crypto_auditor_tools.py` | Exchange wallet, dashboard portfolio |
| Reconciliation | `mvp/wallet_reconciliation.py` | Wallet vs dashboard diff tool |
| Persistence | `mvp/crypto_audit_persistence.py` | `jarvis_crypto_audit_runs` CRUD |
| Alerts | `mvp/telegram_crypto_alerts.py` | Telegram on audit completion |

**Triggers:** LangGraph task, service.py post-run persistence.

---

## Management Layer

### Chief of Staff

| Component | Path | Role |
|-----------|------|------|
| Core | `mvp/chief_of_staff.py` | Prioritization, health score, executive report body |
| Dependencies | action_plans, audits, crypto_audits, decisions, followups, initiatives, objectives, metrics |

**Callers:** `executive_report_service.create_executive_report`, tests.

### Action Planner

| Component | Path | Role |
|-----------|------|------|
| Planner | `mvp/action_planner.py` | Generate plans from audit/dashboard sources |
| Service | `mvp/action_plan_service.py` | Orchestration + Telegram |
| Persistence | `mvp/action_plan_persistence.py` | `jarvis_action_plans` |
| Alerts | `mvp/telegram_action_plan_alerts.py` | Telegram notifications |

### Follow-ups

| Component | Path | Role |
|-----------|------|------|
| Agent | `mvp/followup_agent.py` | Detect stale items across sources |
| Service | `mvp/followup_service.py` | Generate + update workflow |
| Persistence | `mvp/followup_persistence.py` | `jarvis_followups` |
| Scheduler | `mvp/jarvis_daily_followup_scheduler.py` | Daily 9:00 AM |
| Alerts | `mvp/telegram_followup_alerts.py` | Daily Telegram summary |

### Initiatives

| Component | Path | Role |
|-----------|------|------|
| Service | `mvp/initiative_service.py` | CRUD + health computation |
| Persistence | `mvp/initiative_persistence.py` | `jarvis_initiatives` |

---

## Decision Layer

| Component | Path | Role |
|-----------|------|------|
| Service | `mvp/decision_service.py` | Record approval/rejection/deferral |
| Analytics | `mvp/decision_analytics.py` | Success rates, lessons learned |
| Persistence | `mvp/decision_persistence.py` | `jarvis_decisions` |

**Circular note:** `decision_analytics` ↔ `objective_analytics` (lazy imports; no boot failure).

---

## Strategy Layer

| Component | Path | Role |
|-----------|------|------|
| Service | `mvp/objective_service.py` | Objectives, KRs, links, seed |
| Persistence | `mvp/objective_persistence.py` | `jarvis_objectives`, `jarvis_key_results`, `jarvis_objective_links` |
| Analytics | `mvp/objective_analytics.py` | Strategic outcome index |
| KR Refresh | `mvp/kr_refresh_service.py` | Auto-refresh KR values |
| KR Resolver | `mvp/kr_metric_resolver.py` | Metric alias → live data |
| KR Persistence | `mvp/kr_refresh_persistence.py` | `jarvis_kr_refresh_runs` |
| Scheduler | `mvp/jarvis_kr_refresh_scheduler.py` | Daily 7:30 AM |
| Alerts | `mvp/telegram_kr_alerts.py` | KR refresh Telegram |

---

## Reporting Layer

| Component | Path | Role |
|-----------|------|------|
| Metrics | `mvp/metrics_persistence.py` | Executive dashboard + `jarvis_daily_metrics` |
| Reports | `mvp/executive_report_service.py` | Weekly report generation |
| Persistence | `mvp/executive_report_persistence.py` | `jarvis_executive_reports` |
| Scheduler | `mvp/jarvis_weekly_report_scheduler.py` | Monday 8:30 AM |
| Alerts | `mvp/telegram_executive_report_alerts.py` | Weekly Telegram |

---

## MVP Execution Layer (LangGraph)

| Component | Path | Role |
|-----------|------|------|
| Entry | `mvp/service.py` | `run_jarvis_task()` |
| Graph | `mvp/graph.py` | supervisor → planner → executor → reviewer → cost_guard |
| Agents | `mvp/agents.py` | Bedrock agent nodes + audit shortcuts |
| Tools | `mvp/tools.py` | Readonly tool registry |
| Risk | `mvp/risk.py` | Task risk classification |
| Schemas | `mvp/schemas.py` | Pydantic API models |
| Config | `mvp/config.py` | `JARVIS_ENABLED`, `JARVIS_DRY_RUN_ONLY` |
| Task DB | `mvp/persistence.py` | `jarvis_task_runs` |

---

## Schedulers

Registered in `app/services/scheduler.py`:

| Job ID | Trigger | Wrapper | Downstream |
|--------|---------|---------|------------|
| `jarvis_kr_refresh` | Daily 07:30 | `jarvis_kr_refresh_scheduler.run_kr_refresh_sync` | `kr_refresh_service.refresh_key_results` |
| `jarvis_daily_followup` | Daily 09:00 | `jarvis_daily_followup_scheduler.run_daily_followup_sync` | `followup_service.generate_followups` |
| `jarvis_weekly_executive_report` | Monday 08:30 | `jarvis_weekly_report_scheduler.run_weekly_executive_report_sync` | `executive_report_service.create_executive_report` |

All schedulers are read-only; no trades, AWS writes, or infra mutations.

---

## Persistence Layer

Tables created via boot hooks in `app/database.py` (`ensure_jarvis_*`). No Alembic migrations for Jarvis tables.

| Table | Boot Hook | Primary Module |
|-------|-----------|----------------|
| `jarvis_task_runs` | `ensure_jarvis_task_runs_table` | `mvp/persistence.py` |
| `jarvis_audit_runs` | `ensure_jarvis_audit_runs_table` | `mvp/audit_persistence.py` |
| `jarvis_crypto_audit_runs` | `ensure_jarvis_crypto_audit_runs_table` | `mvp/crypto_audit_persistence.py` |
| `jarvis_daily_metrics` | `ensure_jarvis_daily_metrics_table` | `mvp/metrics_persistence.py` |
| `jarvis_action_plans` | `ensure_jarvis_action_plans_table` | `mvp/action_plan_persistence.py` |
| `jarvis_decisions` | `ensure_jarvis_decisions_table` | `mvp/decision_persistence.py` |
| `jarvis_initiatives` | `ensure_jarvis_initiatives_table` | `mvp/initiative_persistence.py` |
| `jarvis_executive_reports` | `ensure_jarvis_executive_reports_table` | `mvp/executive_report_persistence.py` |
| `jarvis_followups` | `ensure_jarvis_followups_table` | `mvp/followup_persistence.py` |
| `jarvis_objectives` | `ensure_jarvis_objectives_table` | `mvp/objective_persistence.py` |
| `jarvis_key_results` | `ensure_jarvis_key_results_table` | `mvp/objective_persistence.py` |
| `jarvis_objective_links` | `ensure_jarvis_objective_links_table` | `mvp/objective_persistence.py` |
| `jarvis_objective_metrics` | `ensure_jarvis_objective_metrics_table` | `mvp/objective_persistence.py` |
| `jarvis_kr_refresh_runs` | `ensure_jarvis_kr_refresh_runs_table` | `mvp/kr_refresh_persistence.py` |
| `jarvis_marketing_intake_state` | `ensure_jarvis_marketing_intake_table` | `marketing_intake_persist.py` (legacy) |

Column migration: `ensure_jarvis_key_results_metric_columns` adds `metric_source`, `last_refreshed_at`.

---

## API Routes

Router: `app/api/routes_jarvis.py` (prefix varies by mount; frontend uses `/jarvis/*` proxy).

| Method | Path | Subsystem |
|--------|------|-----------|
| POST | `/jarvis` | Legacy orchestrator |
| POST | `/api/jarvis/task` | LangGraph MVP |
| GET | `/api/jarvis/tasks` | Task list |
| GET | `/api/jarvis/tasks/{task_id}` | Task detail |
| GET | `/api/jarvis/audits` | AWS audits |
| GET | `/api/jarvis/audits/{audit_id}` | AWS audit detail |
| GET | `/api/jarvis/crypto-audits` | Crypto audits |
| GET | `/api/jarvis/crypto-audits/{audit_id}` | Crypto audit detail |
| GET | `/api/jarvis/executive` | Executive dashboard |
| GET | `/api/jarvis/action-plans` | Action plans |
| GET | `/api/jarvis/action-plans/{plan_id}` | Plan detail |
| POST | `/api/jarvis/action-plans/generate` | Generate plan |
| GET | `/api/jarvis/executive-reports` | Weekly reports |
| GET | `/api/jarvis/executive-reports/{report_id}` | Report detail |
| POST | `/api/jarvis/executive-reports/generate` | Generate report |
| POST | `/api/jarvis/decisions` | Create decision |
| GET | `/api/jarvis/decisions` | List decisions |
| GET | `/api/jarvis/decisions/{decision_id}` | Decision detail |
| GET | `/api/jarvis/decision-analytics` | Decision intelligence |
| POST | `/api/jarvis/initiatives` | Create initiative |
| GET | `/api/jarvis/initiatives` | List initiatives |
| GET | `/api/jarvis/initiatives/{initiative_id}` | Initiative detail |
| PUT | `/api/jarvis/initiatives/{initiative_id}` | Update initiative |
| POST | `/api/jarvis/followups/generate` | Generate followups |
| GET | `/api/jarvis/followups` | List followups |
| GET | `/api/jarvis/followups/{followup_id}` | Followup detail |
| PUT | `/api/jarvis/followups/{followup_id}` | Update followup |
| POST | `/api/jarvis/objectives` | Create objective |
| GET | `/api/jarvis/objectives` | List objectives |
| GET | `/api/jarvis/objectives/{objective_id}` | Objective detail |
| PUT | `/api/jarvis/objectives/{objective_id}` | Update objective |
| POST | `/api/jarvis/objectives/{objective_id}/key-results` | Add KR |
| PUT | `/api/jarvis/objectives/key-results/{kr_id}` | Update KR |
| POST | `/api/jarvis/objectives/{objective_id}/links` | Link entity |
| POST | `/api/jarvis/objectives/seed` | Seed samples |
| POST | `/api/jarvis/objectives/metrics/refresh` | Refresh objective metrics |
| POST | `/api/jarvis/objectives/key-results/refresh` | KR auto-refresh |
| GET | `/api/jarvis/objectives/key-results/refresh-runs` | KR refresh history |
| GET | `/api/jarvis/objective-analytics` | Objective analytics |

**HEAD (git) exposes 16 routes.** Working tree / PROD expose **39 routes**.

---

## Dashboard Routes (Frontend)

Base: `frontend/src/app/jarvis/`

| Route | Page | Git Status |
|-------|------|------------|
| `/jarvis` | Task console | Modified |
| `/jarvis/executive` | Executive dashboard | Untracked |
| `/jarvis/audits` | AWS audit list | Untracked |
| `/jarvis/audits/[auditId]` | AWS audit detail | Untracked |
| `/jarvis/crypto-audits` | Crypto audit list | Untracked |
| `/jarvis/crypto-audits/[auditId]` | Crypto audit detail | Untracked |
| `/jarvis/action-plans` | Action plan list | Untracked |
| `/jarvis/action-plans/[planId]` | Action plan detail | Untracked |
| `/jarvis/executive-reports` | Report list | Untracked |
| `/jarvis/executive-reports/[reportId]` | Report detail | Untracked |
| `/jarvis/decisions` | Decision list | Untracked |
| `/jarvis/decisions/[decisionId]` | Decision detail | Untracked |
| `/jarvis/initiatives` | Initiative list | Untracked |
| `/jarvis/initiatives/[initiativeId]` | Initiative detail | Untracked |
| `/jarvis/followups` | Followup list | Untracked |
| `/jarvis/followups/[followupId]` | Followup detail | Untracked |
| `/jarvis/objectives` | Objective list | Committed |
| `/jarvis/objectives/[objectiveId]` | Objective detail | Committed |

API client: `frontend/src/lib/api.ts` (+522 lines uncommitted Jarvis types/functions).

---

## Dependency Graph (Management Stack)

```
Chief of Staff
 ├─ metrics_persistence (executive dashboard)
 ├─ audit_persistence / crypto_audit_persistence
 ├─ action_plan_persistence
 ├─ decision_analytics
 ├─ followup_persistence
 ├─ initiative_persistence
 └─ objective_persistence

Executive Report Service
 └─ chief_of_staff.generate_executive_report
     └─ telegram_executive_report_alerts

Followup Service
 └─ followup_agent
     ├─ action_plans, audits, crypto_audits, decisions, initiatives
     └─ followup_persistence

Action Plan Service
 └─ action_planner
     ├─ audit_persistence / crypto_audit_persistence
     └─ metrics_persistence (executive_dashboard source)

KR Refresh Service
 └─ kr_metric_resolver
     ├─ aws_auditor_tools, audit_persistence
     ├─ crypto_audit_persistence, metrics_persistence
     ├─ followup_persistence, action_plan_persistence
     └─ initiative_persistence

LangGraph MVP (service.py)
 └─ graph → agents → tools
     ├─ aws_auditor / crypto_auditor (short-circuit paths)
     └─ persistence (task_runs, audit_runs, crypto_audit_runs)
```

---

## Environment Variables

| Variable | Used By |
|----------|---------|
| `JARVIS_ENABLED` | MVP gate |
| `JARVIS_DRY_RUN_ONLY` | Execution policy |
| `AWS_*` / IAM role | AWS auditor tools |
| `TELEGRAM_*` | All telegram_*_alerts modules |
| Bedrock region/model env | `mvp/config.py`, `bedrock_client.py` |

---

## Git Reconciliation Status (2026-06-08)

| Classification | Count | Meaning |
|----------------|-------|---------|
| A — committed, deployed, clean | 55 | In git HEAD, in PROD, no local drift |
| A* — committed, deployed, drift | 13 | In git but modified locally vs HEAD |
| B — deployed, not committed | 29 | Untracked; restored from container / local dev |
| D — orphaned | 4 stale `.pyc` | `dialog_router`, `marketing_execution`, `marketing_staging`, `telegram_bridge` (no `.py` source) |

**Critical gap:** A fresh `git clone` of HEAD cannot import 8 modules referenced by committed code (`metrics_persistence`, `kr_metric_resolver`, `autonomous_orchestrator`).

---

## Test Coverage Map

| Test File | Subsystem | Git Status |
|-----------|-----------|------------|
| `test_jarvis_task_mvp.py` | LangGraph MVP | Committed |
| `test_jarvis_kr_refresh.py` | KR refresh | Committed |
| `test_jarvis_objectives.py` | Objectives + chief_of_staff | Committed |
| `test_jarvis_aws_auditor.py` | AWS auditor | Untracked |
| `test_jarvis_crypto_auditor.py` | Crypto auditor | Untracked |
| `test_jarvis_wallet_reconciliation.py` | Wallet reconcile | Untracked |
| `test_jarvis_action_planner.py` | Action planner | Untracked |
| `test_jarvis_executive_metrics.py` | Executive dashboard | Untracked |
| `test_jarvis_chief_of_staff.py` | Chief of Staff | Untracked |
| `test_jarvis_decision_intelligence.py` | Decisions | Untracked |
| `test_jarvis_initiatives.py` | Initiatives | Untracked |
| `test_jarvis_followups.py` | Follow-ups | Untracked |

---

## Reproducibility Scorecard (git clone → docker compose up)

| Subsystem | Score | Blocker |
|-----------|-------|---------|
| LangGraph MVP core | 70 | Auditors wired in WT only |
| AWS Auditor | 25 | All modules untracked; boot hooks uncommitted |
| Crypto Auditor | 25 | All modules untracked |
| Executive Dashboard | 40 | Depends on untracked auditor modules |
| Action Planner | 20 | Fully untracked |
| Decision Intelligence | 20 | Fully untracked |
| Follow-ups | 20 | Fully untracked |
| Initiatives | 55 | Persistence committed; service untracked |
| Objectives + KR Refresh | 80 | Mostly committed; scheduler in HEAD |
| Chief of Staff | 20 | Untracked |
| Weekly Reports | 20 | Untracked + scheduler hooks uncommitted |
| Frontend Dashboard | 30 | 8/9 page groups untracked; api.ts drift |
| Database schema | 50 | 6 boot hooks missing from HEAD |
| **Overall platform** | **35** | See reconciliation report |

---

## Recommended Commit Order

1. **Foundation:** `database.py` boot hooks, `scheduler.py` Jarvis jobs  
2. **Group A:** AWS auditor (`aws_auditor*`, `audit_persistence`)  
3. **Group B:** Crypto auditor (`crypto_auditor*`, `wallet_reconciliation`, `crypto_audit_persistence`, `telegram_crypto_alerts`)  
4. **Shared metrics:** reconcile `metrics_persistence.py` imports  
5. **Group C:** Action planner stack  
6. **Group D:** Decision intelligence stack  
7. **Group E:** Follow-ups stack + daily scheduler  
8. **Group F:** Chief of Staff + executive reports + weekly scheduler  
9. **Group G:** Objectives (verify) + KR refresh (mostly done)  
10. **Integration:** `routes_jarvis.py`, `service.py`, `agents.py`, `tools.py`, `graph.py`, `schemas.py`  
11. **Frontend:** `api.ts` + all `/jarvis/*` pages  
12. **Tests:** one commit per group above  
13. **Support:** `autonomy_ledger.py`, `perico_guided_env.py`, `repo_worker_mvp.py`, `requirements.txt`
