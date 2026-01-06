# Portfolio Cache Fix - Deployment Status

## Phase 1: Commit & Push ✅
- **Status**: COMPLETE
- **Commit**: `50cf7b1 Fix: make portfolio_cache defensive to prevent /api/dashboard/state 500`
- **Pushed**: Yes

## Phase 2: AWS Deploy
- **Status**: PENDING (requires SSM access)
- **Script**: `deploy_and_verify_portfolio_fix.sh`
- **Action needed**: Run deployment script or manually:
  ```bash
  # On AWS instance:
  cd ~/automated-trading-platform
  git pull origin main
  docker compose --profile aws build backend-aws
  docker compose --profile aws restart backend-aws
  ```

## Phase 3: Enable PORTFOLIO_RECONCILE_DEBUG
- **Status**: PENDING
- **Method**: Added to docker-compose.yml (defaults to 1)
- **Action needed**: Restart backend after deployment

## Phase 4: Verify Fix
- **Status**: PENDING (requires SSM port-forward)
- **SSM Port-forward**: Must be active
- **Test command**: 
  ```bash
  curl -sS http://localhost:8002/api/dashboard/state | python3 -m json.tool
  ```

## Phase 5: Collect Evidence
- **Status**: READY (scripts created)
- **Script**: `./evidence/portfolio_reconcile/collect_evidence.sh`
- **Action needed**: Run after Phase 4 passes

## Next Steps
1. Start SSM port-forward (if not active)
2. Run `./deploy_and_verify_portfolio_fix.sh`
3. Test `/api/dashboard/state` endpoint
4. Run evidence collection script
5. Verify portfolio_value_source starts with "exchange:"
