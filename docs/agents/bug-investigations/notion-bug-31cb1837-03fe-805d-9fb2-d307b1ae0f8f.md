# Bug investigation: Investigate test signal throttle inconsistency

- **Notion page id**: `31cb1837-03fe-805d-9fb2-d307b1ae0f8f`
- **Priority**: `High`
- **Project**: `Crypto Trading`
- **Type**: `Bug`
- **GitHub link**: ``

## Inferred area

- **Area**: Trading Engine / Strategy
- **Matched rules**: strategy-signals

## Affected modules

- `backend/app/services/signal_monitor.py`
- `backend/app/services/trading_signals.py`
- `backend/app/services/strategy_profiles.py`
- `backend/app/services/signal_throttle.py`

## Relevant docs

- [docs/architecture/system-map.md](../../architecture/system-map.md)
- [docs/agents/context.md](../context.md)
- [docs/agents/task-system.md](../task-system.md)
- [docs/decision-log/README.md](../../decision-log/README.md)
- [docs/integrations/crypto-api.md](../../integrations/crypto-api.md)

## Relevant runbooks

- [docs/runbooks/OPEN_VS_TRIGGER_ORDERS_DIAGNOSTIC.md](../../runbooks/OPEN_VS_TRIGGER_ORDERS_DIAGNOSTIC.md)

## Bug details

- **Reported symptom**: Investigate test signal throttle inconsistency
- **Reproducible**: (to be confirmed)
- **Severity**: (inferred from priority: High)

## Investigation checklist

- [ ] Confirm current behavior (logs, health endpoint, dashboard)
- [ ] Identify root cause in affected module(s)
- [ ] Determine smallest safe fix
- [ ] Verify fix does not affect unrelated areas
- [ ] Update relevant docs/runbooks if behavior changes
- [ ] Validate (tests/lint/manual) before marking deployed
