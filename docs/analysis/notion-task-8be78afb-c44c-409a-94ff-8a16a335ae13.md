## Title
Full Audit of Trading Alert Pipeline and Anti-Spam Logic

## Task ID
`8be78afb-c44c-409a-94ff-8a16a335ae13`

## Current Version
`v0.1.0`

## Proposed Version
`v0.2.0`

## Problem Observed
El sistema de trading está generando múltiples alertas repetidas en Telegram relacionadas con BTC_USD cuando falla la creación de órdenes automáticas.

Error observado

AUTOMATIC ORDER CREATION FAILED
Symbol: BTC_USD
Side: BUY
Signal: BUY signal detected
Trade enabled: True
Error: CONFIGURACIÓN REQUERIDA
El campo "Amount USD" no está configurado para BTC_USD.

Problema
- La alerta se repite continuamente, lo que indica que no se están aplicando correctamente las reglas de control de alertas.
- P

## Current Implementation Summary
- Docs: `docs/architecture/system-map.md` - # System Map (AI-readable)  **First document for agents.** How the system is connected: components, external APIs, data flow, and dependencies.  ---  ## System Components  ### Dashboard - **Frontend UI** — Next.js app; served at `https://da
- Docs: `docs/agents/context.md` - # Agent Context (AI-readable)  How an autonomous agent (Cursor, OpenClaw, or other tools) should work inside this repository: purpose, critical areas, and where to find things.  ---  ## Purpose of the project  - **Automated Trading Platform
- Docs: `docs/agents/task-system.md` - # Task System for Agents (AI-readable)  How agents should interpret and execute tasks: lifecycle, planning, validation, and where to find logs and monitoring.  ---  ## Task lifecycle  Tasks move through clear states. Use these when planning
- Docs: `docs/integrations/crypto-api.md` - # Crypto.com Exchange API  How the platform connects to Crypto.com Exchange: configuration, modes, and production (AWS) setup.  ---  ## Overview  - The backend talks to **Crypto.com Exchange API v1** (`https://api.crypto.com/exchange/v1`). 
- Docs: `docs/decision-log/README.md` - # Decision Log  Record of **significant technical and product decisions** that affect the platform. Keeping a log here helps humans and AI agents understand *why* things are done a certain way.  ---  ## Purpose  - Capture **what** was decid
- Code: `backend/app/services/telegram_commands.py` - file exists (6340 lines)
- Code: `backend/app/services/telegram_notifier.py` - file exists (1667 lines); contains: alert
- Code: `backend/app/api/routes_monitoring.py` - file exists (3629 lines); contains: signal, alert
- Code: `backend/app/services/signal_monitor.py` - file exists (9709 lines); contains: signal, alert
- Code: `backend/app/services/trading_signals.py` - file exists (1053 lines); contains: signal, volume, indicator
- Code: `backend/app/models/trade_signal.py` - file exists (84 lines); contains: signal

## Business Logic Intent
Improve alert/signal decision quality while preserving existing safety constraints and avoiding direct production behavior changes in this step.

## Historical Data Observations
- `order_history.db` - SQLite order history database; file present (753664 bytes)
- `runtime-history` - runtime historical folder; directory present with sample entries: 2026-02-23
- `logs/agent_activity.jsonl` - agent workflow event log; file present (24147 bytes, 114 lines)
- `backend/app/services/order_history_db.py` - order-history DB access service; file present (8685 bytes, 219 lines)
- `backend/app/models/exchange_order.py` - exchange order model; file present (3702 bytes, 77 lines)
- `backend/app/models/trade_signal.py` - trade signal model; file present (3355 bytes, 84 lines)

## Proposed Improvement
- Propose incremental indicator/threshold tuning with staged validation criteria before any production logic change.
- Limit first implementation scope to the affected files listed below and keep non-targeted business logic unchanged.

## Expected Benefit
Higher signal relevance and lower noise by validating improvement hypotheses against documented intent and available historical evidence.

## Affected Files
- `backend/app/services/telegram_commands.py`
- `backend/app/services/telegram_notifier.py`
- `backend/app/api/routes_monitoring.py`
- `backend/app/services/signal_monitor.py`
- `backend/app/services/trading_signals.py`
- `backend/app/models/trade_signal.py`

## Validation Plan
- Confirm proposal alignment with business intent in docs and existing strategy definitions.
- Review historical-signal/order trends from available local data sources before changing thresholds.
- Run callback validation to ensure proposal completeness and traceability metadata.

## Risk Level
low

## Confidence Score
0.700 (rule-based: coverage of affected files + historical observations + explicit problem statement)

_Generated at 2026-03-14T05:27:59Z_
