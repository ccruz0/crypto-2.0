# Portfolio Reconcile Evidence Collection Instructions

## Current Status

The backend at `http://localhost:8002` is returning 500 errors for `/api/dashboard/state`.

## Steps to Enable Reconcile Debug

1. **Enable PORTFOLIO_RECONCILE_DEBUG on AWS Backend**:
   - If using SSM port-forward to AWS, the backend container needs `PORTFOLIO_RECONCILE_DEBUG=1`
   - Add to `.env.aws` or docker-compose.yml backend-aws service environment section:
     ```
     - PORTFOLIO_RECONCILE_DEBUG=1
     ```
   - Restart backend: `docker-compose restart backend-aws` (on AWS instance)

2. **Verify Debug is Enabled**:
   - Check backend logs: `docker-compose logs backend-aws | grep RECONCILE`
   - Should see: `[RECONCILE] Found X equity/balance fields in API response`

3. **Fetch Dashboard State**:
   ```bash
   curl -sS "http://localhost:8002/api/dashboard/state" | python3 -m json.tool > dashboard_state.json
   ```

4. **Extract Portfolio Evidence**:
   ```bash
   python3 evidence/portfolio_reconcile/extract_portfolio.py dashboard_state.json .
   ```

## Expected Output Files

- `dashboard_state.json` - Full API response
- `portfolio_only.json` - Portfolio section only
- `portfolio_extract.txt` - Human-readable summary

## What to Look For

- `portfolio.total_value_usd` - Should match Crypto.com UI "Wallet Balance (after haircut)"
- `portfolio.portfolio_value_source` - Should be `exchange:wallet_balance_after_haircut` or similar
- `portfolio.reconcile.chosen.field_path` - The exact field path used
- `portfolio.reconcile.raw_fields` - All equity/balance fields found in API response
