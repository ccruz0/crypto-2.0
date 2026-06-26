#### f79b9ffc | dashboard | dashboard_exchange_mismatch | conf=90.0
OBJ: Why was dashboard showing zero orders while exchange had one?
ROOT: Open orders cache empty but dashboard API serves database fallback
FIX: Review collected evidence and implement targeted fix behind approval gate.
SUMMARY: Why was dashboard showing zero orders while exchange had one?
- Exchange=1, DB=1, dashboard=0
- Reconciliation found 2 discrepancy(ies)
- Open-status count (NEW/ACTIVE/PARTIALLY_FILLED): 1; query=SELECT COUNT(*) AS count FROM exchange_orders WHERE status IN 
- Orders by status: {'FILLED': 149, 'ACTI
EVIDENCE (15):
  - [None] Exchange=1, DB=1, dashboard=0
  - [None] Reconciliation found 2 discrepancy(ies)
  - [None] Open-status count (NEW/ACTIVE/PARTIALLY_FILLED): 1; query=SELECT COUNT(*) AS count FROM exchange_orders WHERE 
  - [None] Orders by status: {'FILLED': 149, 'ACTIVE': 1}
  - [None] Latest orders sample: [{'id': 150, 'exchange_order_id': '5755600489253467765', 'symbol': 'BTC_USD', 'side': 'S
  - [None] Open position symbols: [{'symbol': 'DGB_USD', 'open_commitments': 6}, {'symbol': 'SOL_USD', 'open_commitments'
  - [None] Raw in-memory cache contains 0 open orders; last_updated=None
  - [None] Dashboard API effective count=1 via source=database_fallback, sync_status=stale_cache_db_fallback, data_verifi
  - [None] Live exchange: regular=1, trigger=0, total=1, data_verified=True; trigger API issue: 400 Client Error: Bad Req
  - [None] Open orders API route at line 28: ### `/api/orders/open` (routes_orders.py)
  - [None] Frontend open orders hook at line 203:         if "frontend" in m.get("path", "") or "getOpenOrders" in m.get(
  - [None] exchange_total=1, regular=1, trigger=0, cache_raw=0, dashboard_effective=1 (source=database_fallback)
  - [None] Trigger-order API error_code=None: 400 Client Error: Bad Request for url: https://api.crypto.com/exchange/v1/p
  - [None] Open orders cache stale; dashboard serving DB fallback while exchange has live orders
  - [None] Health check status=pass
RANKED:
  - 90.0 Open orders cache empty but dashboard API serves database fallback
  - 100.0 Stale dashboard cache not refreshed by exchange sync
  - 88.0 Trigger order API failure blocks cache updates
  - 75.0 Reconciliation found 2 discrepancy(ies)

#### e080e0d0 | dashboard | dashboard_exchange_mismatch | conf=96.0
OBJ: Why are my open orders different from Crypto.com?
ROOT: No active dashboard/exchange mismatch detected
FIX: No dashboard/exchange sync repair needed based on current live counts.
SUMMARY: Why are my open orders different from Crypto.com?
- Exchange=5, DB=2, dashboard=5
- Trigger-order API error_code=50001: ERR_INTERNAL
- Reconciliation found 6 discrepancy(ies)
- Open-status count (NEW/ACTIVE/PARTIALLY_FILLED): 2; query=SELECT COUNT(*) AS count FROM exchange_orders WHERE status IN 
Co
EVIDENCE (15):
  - [None] Exchange=5, DB=2, dashboard=5
  - [None] Trigger-order API error_code=50001: ERR_INTERNAL
  - [None] Reconciliation found 6 discrepancy(ies)
  - [None] Open-status count (NEW/ACTIVE/PARTIALLY_FILLED): 2; query=SELECT COUNT(*) AS count FROM exchange_orders WHERE 
  - [None] Orders by status: {'FILLED': 149, 'UNKNOWN': 3, 'ACTIVE': 2}
  - [None] Latest orders sample: [{'id': 154, 'exchange_order_id': '73817490101936697', 'symbol': 'BTC_USD', 'side': 'SEL
  - [None] Open position symbols: [{'symbol': 'DGB_USD', 'open_commitments': 6}, {'symbol': 'SOL_USD', 'open_commitments'
  - [None] Raw in-memory cache contains 5 open orders; last_updated=2026-06-14 08:55:38.525610+00:00
  - [None] Dashboard API effective count=5 via source=crypto_com_api, sync_status=ok, data_verified=True; trigger_orders_
  - [None] Live exchange: regular=2, trigger=3, total=5, data_verified=True; trigger API issue: ERR_INTERNAL (code=50001,
  - [None] Open orders API route at line 28: ### `/api/orders/open` (routes_orders.py)
  - [None] Frontend open orders hook at line 101:             {"path": "frontend/src/app/api.ts", "line": "678", "text": 
  - [None] exchange_total=5, regular=2, trigger=3, cache_raw=5, dashboard_effective=5 (source=crypto_com_api)
  - [None] Open order counts differ across exchange, database, and dashboard
  - [None] Health check status=pass
RANKED:
  - 96.0 No active dashboard/exchange mismatch detected
  - 96.0 No active dashboard/exchange mismatch detected
  - 88.0 Stale dashboard cache not refreshed by exchange sync
  - 33.0 Duplicated API secret in runtime.env causes Crypto.com auth failure (4

#### ec30b60b | authentication | exchange_auth_failing | conf=90.0
OBJ: Investigate Crypto.com authentication failures
ROOT: Open orders cache empty but dashboard API serves database fallback
FIX: Review collected evidence and implement targeted fix behind approval gate.
SUMMARY: Investigate Crypto.com authentication failures
- Exchange=5, DB=2, dashboard=5; checked_at=2026-06-16T14:25:25.464981+00:00
- Trigger-order API error_code=50001: ERR_INTERNAL
- Reconciliation found 6 discrepancy(ies)
- [2026-06-16T14:25:25.924559+00:00] container=github_app_monitor.log:     Exchange
EVIDENCE (14):
  - [exchange] Exchange=5, DB=2, dashboard=5; checked_at=2026-06-16T14:25:25.464981+00:00
  - [exchange] Trigger-order API error_code=50001: ERR_INTERNAL
  - [diagnostic] Reconciliation found 6 discrepancy(ies)
  - [log] [2026-06-16T14:25:25.924559+00:00] container=github_app_monitor.log:     Exchange credential/auth warnings: no
  - [log] [2026-06-16T14:25:25.924559+00:00] container=github_app_monitor.log: EXCHANGE_CREDENTIAL_WARNINGS=NO
  - [log] [2026-06-16T14:25:25.924559+00:00] container=github_app_monitor.log:   == 2. Local secrets/runtime.env key pre
  - [log] [2026-06-16T14:25:25.924559+00:00] container=github_app_monitor.log:   == 3. Container env (scripts/verify_dep
  - [repository] app/api/routes_portfolio.py:190 —     from app.utils.credential_resolver import resolve_crypto_credentials, ge
  - [repository] app/services/portfolio_snapshot.py:90 —         from app.utils.credential_resolver import resolve_crypto_crede
  - [repository] app/services/portfolio_cache.py:190 —         from app.utils.credential_resolver import resolve_crypto_credent
  - [repository] app/services/portfolio_cache.py:818 —             from app.utils.credential_resolver import resolve_crypto_cre
  - [repository] app/services/portfolio_cache.py:1065 —             from app.utils.credential_resolver import resolve_crypto_cr
  - [None] Credential presence flags: ['EXCHANGE_CUSTOM_API_KEY_PRESENT', 'EXCHANGE_CUSTOM_API_SECRET_PRESENT']; used_pai
  - [None] runtime.env contains 2 secret lines; duplicate entries may override canonical credentials
RANKED:
  - 90.0 Open orders cache empty but dashboard API serves database fallback
  - 83.0 Trigger order API failure blocks cache updates
  - 75.0 Reconciliation found 6 discrepancy(ies)
  - 48.0 Crypto.com API credentials missing or misconfigured in runtime.env

#### d3fa6e63 | authentication | exchange_auth_failing | conf=100.0
OBJ: Investigate Crypto.com authentication failures
ROOT: Trigger order API failure blocks cache updates
FIX: Allow regular open orders to update cache independently when trigger-order sync fails.
SUMMARY: Investigate Crypto.com authentication failures
- Exchange=5, DB=2, dashboard=0; checked_at=2026-06-16T14:24:10.753455+00:00
- Trigger-order API error_code=50001: ERR_INTERNAL
- Reconciliation found 10 discrepancy(ies)
- [2026-06-16T14:24:11.883950+00:00] container=github_app_monitor.log:     Exchang
EVIDENCE (14):
  - [exchange] Exchange=5, DB=2, dashboard=0; checked_at=2026-06-16T14:24:10.753455+00:00
  - [exchange] Trigger-order API error_code=50001: ERR_INTERNAL
  - [diagnostic] Reconciliation found 10 discrepancy(ies)
  - [log] [2026-06-16T14:24:11.883950+00:00] container=github_app_monitor.log:     Exchange credential/auth warnings: no
  - [log] [2026-06-16T14:24:11.883950+00:00] container=github_app_monitor.log: EXCHANGE_CREDENTIAL_WARNINGS=NO
  - [log] [2026-06-16T14:24:11.883950+00:00] container=github_app_monitor.log:   == 2. Local secrets/runtime.env key pre
  - [log] [2026-06-16T14:24:11.883950+00:00] container=github_app_monitor.log:   == 3. Container env (scripts/verify_dep
  - [repository] app/api/routes_portfolio.py:190 —     from app.utils.credential_resolver import resolve_crypto_credentials, ge
  - [repository] app/services/portfolio_snapshot.py:90 —         from app.utils.credential_resolver import resolve_crypto_crede
  - [repository] app/services/portfolio_cache.py:190 —         from app.utils.credential_resolver import resolve_crypto_credent
  - [repository] app/services/portfolio_cache.py:818 —             from app.utils.credential_resolver import resolve_crypto_cre
  - [repository] app/services/portfolio_cache.py:1065 —             from app.utils.credential_resolver import resolve_crypto_cr
  - [None] Credential presence flags: ['EXCHANGE_CUSTOM_API_KEY_PRESENT', 'EXCHANGE_CUSTOM_API_SECRET_PRESENT']; used_pai
  - [None] runtime.env contains 2 secret lines; duplicate entries may override canonical credentials
RANKED:
  - 100.0 Trigger order API failure blocks cache updates
  - 75.0 Reconciliation found 10 discrepancy(ies)
  - 68.0 Database has open orders but dashboard cache is empty
  - 48.0 Crypto.com API credentials missing or misconfigured in runtime.env

#### a6cf648c | authentication | exchange_auth_failing | conf=48.0
OBJ: Investigate Crypto.com authentication failures
ROOT: Crypto.com API credentials missing or misconfigured in runtime.env
FIX: Set canonical EXCHANGE_CUSTOM_API_KEY/SECRET in runtime.env; remove duplicate secret lines.
SUMMARY: Investigate Crypto.com authentication failures
- Exchange=5, DB=2, dashboard=5; checked_at=2026-06-16T15:03:24.894009+00:00
- Trigger-order API error_code=50001: ERR_INTERNAL
- Reconciliation found 6 discrepancy(ies)
- [2026-06-16T15:03:25.368711+00:00] container=github_app_monitor.log: EXCHANGE_CRE
EVIDENCE (15):
  - [exchange] Exchange=5, DB=2, dashboard=5; checked_at=2026-06-16T15:03:24.894009+00:00
  - [exchange] Trigger-order API error_code=50001: ERR_INTERNAL
  - [diagnostic] Reconciliation found 6 discrepancy(ies)
  - [log] [2026-06-16T15:03:25.368711+00:00] container=github_app_monitor.log: EXCHANGE_CREDENTIAL_WARNINGS=NO
  - [log] [2026-06-16T15:03:25.368711+00:00] container=github_app_monitor.log:   == 2. Local secrets/runtime.env key pre
  - [log] [2026-06-16T15:03:25.368711+00:00] container=github_app_monitor.log:   == 3. Container env (scripts/verify_dep
  - [log] [2026-06-16T15:03:25.368711+00:00] container=github_app_monitor.log:     == Deploy secrets (container env, pre
  - [log] [2026-06-16T15:03:25.368711+00:00] container=github_app_monitor.log:       GitHub App credentials:
  - [repository] tests/test_crypto_credential_resolver.py:7 — from app.utils.credential_resolver import (
  - [repository] tests/test_crypto_credential_resolver.py:23 —     with patch("app.utils.credential_resolver.runtime_env_file_p
  - [repository] tests/test_portfolio_snapshot_env.py:11 — from app.utils.credential_resolver import (
  - [repository] docs/architecture/PORTFOLIO_RECONSTRUCTION.md:78 — - Credentials are resolved by `app.utils.credential_resolve
  - [repository] docs/architecture/PORTFOLIO_RECONSTRUCTION.md:378 — | Credential resolver | `backend/app/utils/credential_reso
  - [None] Credential presence flags: ['EXCHANGE_CUSTOM_API_KEY_PRESENT', 'EXCHANGE_CUSTOM_API_SECRET_PRESENT']; used_pai
  - [None] runtime.env contains 2 secret lines; duplicate entries may override canonical credentials
RANKED:
  - 90.0 Open orders cache empty but dashboard API serves database fallback
  - 83.0 Trigger order API failure blocks cache updates
  - 75.0 Reconciliation found 6 discrepancy(ies)
  - 48.0 Crypto.com API credentials missing or misconfigured in runtime.env

#### 7652e662 | authentication | exchange_auth_failing | conf=48.0
OBJ: Investigate Crypto.com authentication failures
ROOT: Crypto.com API credentials missing or misconfigured in runtime.env
FIX: Set canonical EXCHANGE_CUSTOM_API_KEY/SECRET in runtime.env; remove duplicate secret lines.
SUMMARY: Investigate Crypto.com authentication failures
- Exchange=5, DB=2, dashboard=5; checked_at=2026-06-16T14:28:14.330032+00:00
- Trigger-order API error_code=50001: ERR_INTERNAL
- Reconciliation found 6 discrepancy(ies)
- [2026-06-16T14:28:14.751685+00:00] container=github_app_monitor.log:     Exchange
EVIDENCE (14):
  - [exchange] Exchange=5, DB=2, dashboard=5; checked_at=2026-06-16T14:28:14.330032+00:00
  - [exchange] Trigger-order API error_code=50001: ERR_INTERNAL
  - [diagnostic] Reconciliation found 6 discrepancy(ies)
  - [log] [2026-06-16T14:28:14.751685+00:00] container=github_app_monitor.log:     Exchange credential/auth warnings: no
  - [log] [2026-06-16T14:28:14.751685+00:00] container=github_app_monitor.log: EXCHANGE_CREDENTIAL_WARNINGS=NO
  - [log] [2026-06-16T14:28:14.751685+00:00] container=github_app_monitor.log:   == 2. Local secrets/runtime.env key pre
  - [log] [2026-06-16T14:28:14.751685+00:00] container=github_app_monitor.log:   == 3. Container env (scripts/verify_dep
  - [repository] app/api/routes_portfolio.py:190 —     from app.utils.credential_resolver import resolve_crypto_credentials, ge
  - [repository] app/services/portfolio_snapshot.py:90 —         from app.utils.credential_resolver import resolve_crypto_crede
  - [repository] app/services/portfolio_cache.py:190 —         from app.utils.credential_resolver import resolve_crypto_credent
  - [repository] app/services/portfolio_cache.py:818 —             from app.utils.credential_resolver import resolve_crypto_cre
  - [repository] app/services/portfolio_cache.py:1065 —             from app.utils.credential_resolver import resolve_crypto_cr
  - [None] Credential presence flags: ['EXCHANGE_CUSTOM_API_KEY_PRESENT', 'EXCHANGE_CUSTOM_API_SECRET_PRESENT']; used_pai
  - [None] runtime.env contains 2 secret lines; duplicate entries may override canonical credentials
RANKED:
  - 90.0 Open orders cache empty but dashboard API serves database fallback
  - 83.0 Trigger order API failure blocks cache updates
  - 75.0 Reconciliation found 6 discrepancy(ies)
  - 48.0 Crypto.com API credentials missing or misconfigured in runtime.env

#### 4fcd9e28 | dashboard | open_orders_zero_dashboard | conf=96.0
OBJ: Investigate why open orders show 0 in the dashboard
ROOT: No active dashboard/exchange mismatch detected
FIX: No dashboard/exchange sync repair needed based on current live counts.
SUMMARY: Investigate why open orders show 0 in the dashboard
- Open-status count (NEW/ACTIVE/PARTIALLY_FILLED): 2; query=SELECT COUNT(*) AS count FROM exchange_orders WHERE status IN 
- Orders by status: {'FILLED': 149, 'UNKNOWN': 3, 'ACTIVE': 2}
- Latest orders sample: [{'id': 154, 'exchange_order_id': '738
EVIDENCE (21):
  - [None] Open-status count (NEW/ACTIVE/PARTIALLY_FILLED): 2; query=SELECT COUNT(*) AS count FROM exchange_orders WHERE 
  - [None] Orders by status: {'FILLED': 149, 'UNKNOWN': 3, 'ACTIVE': 2}
  - [None] Latest orders sample: [{'id': 154, 'exchange_order_id': '73817490101936697', 'symbol': 'BTC_USD', 'side': 'SEL
  - [None] Open position symbols: [{'symbol': 'DGB_USD', 'open_commitments': 6}, {'symbol': 'SOL_USD', 'open_commitments'
  - [None] Raw in-memory cache contains 5 open orders; last_updated=2026-06-16 15:02:59.829466+00:00
  - [None] Dashboard API effective count=5 via source=crypto_com_api, sync_status=ok, data_verified=True; trigger_orders_
  - [None] Live exchange: regular=2, trigger=3, total=5, data_verified=True; trigger API issue: ERR_INTERNAL (code=50001,
  - [None] Open orders API route at line 28: ### `/api/orders/open` (routes_orders.py)
  - [None] Frontend open orders hook at line 114:             {"path": "frontend/src/app/api.ts", "line": "678", "text": 
  - [diagnostic] exchange_total=5, regular=2, trigger=3, cache_raw=5, dashboard_effective=5 (source=crypto_com_api); checked_at
  - [exchange] Trigger-order API error_code=50001: ERR_INTERNAL
  - [diagnostic] Open order counts differ across exchange, database, and dashboard
  - [exchange] Exchange=5, DB=2, dashboard=5; checked_at=2026-06-16T15:03:18.696953+00:00
  - [diagnostic] Reconciliation found 6 discrepancy(ies)
  - [database] table=exchange_orders; row_count=1; timestamps=['2026-06-16T15:03:18.698486+00:00']; query=SELECT COUNT(*) AS 
  - [log] No log matches for keywords=('open orders', 'sync', 'cache', '50001') in services=['backend-aws', 'frontend-aw
  - [repository] tests/test_jarvis_diagnostic_tools.py:114 —             {"path": "frontend/src/app/api.ts", "line": "678", "te
  - [repository] app/jarvis/execution_tools/diagnose_open_orders.py:203 —         if "frontend" in m.get("path", "") or "getOpe
  - [repository] app/jarvis/execution_tools/diagnose_open_orders.py:216 —         detail="Frontend calls getOpenOrders() -> GET
  - [repository] app/jarvis/execution_tools/diagnose_open_orders.py:459 —         "frontend_hook": "getOpenOrders() in frontend
  - [repository] app/jarvis/execution_tools/search_repository.py:12 —         "getOpenOrders",
RANKED:
  - 96.0 No active dashboard/exchange mismatch detected
  - 100.0 Stale dashboard cache not refreshed by exchange sync
  - 33.0 FILLED orders exist in database but dashboard trade history does not d
  - 33.0 Crypto.com API credentials missing or misconfigured in runtime.env

#### 2616ea25 | dashboard | dashboard_exchange_mismatch | conf=96.0
OBJ: Why are BTC orders missing from the dashboard but visible in Crypto.com?
ROOT: No active dashboard/exchange mismatch detected
FIX: No dashboard/exchange sync repair needed based on current live counts.
SUMMARY: Why are BTC orders missing from the dashboard but visible in Crypto.com?
- Exchange=5, DB=2, dashboard=5; checked_at=2026-06-16T15:03:28.700337+00:00
- Trigger-order API error_code=50001: ERR_INTERNAL
- Reconciliation found 6 discrepancy(ies)
- Open-status count (NEW/ACTIVE/PARTIALLY_FILLED): 2; que
EVIDENCE (24):
  - [exchange] Exchange=5, DB=2, dashboard=5; checked_at=2026-06-16T15:03:28.700337+00:00
  - [exchange] Trigger-order API error_code=50001: ERR_INTERNAL
  - [diagnostic] Reconciliation found 6 discrepancy(ies)
  - [None] Open-status count (NEW/ACTIVE/PARTIALLY_FILLED): 2; query=SELECT COUNT(*) AS count FROM exchange_orders WHERE 
  - [None] Orders by status: {'FILLED': 149, 'UNKNOWN': 3, 'ACTIVE': 2}
  - [None] Latest orders sample: [{'id': 154, 'exchange_order_id': '73817490101936697', 'symbol': 'BTC_USD', 'side': 'SEL
  - [None] Open position symbols: [{'symbol': 'DGB_USD', 'open_commitments': 6}, {'symbol': 'SOL_USD', 'open_commitments'
  - [None] Raw in-memory cache contains 5 open orders; last_updated=2026-06-16 15:03:28.004628+00:00
  - [None] Dashboard API effective count=5 via source=crypto_com_api, sync_status=ok, data_verified=True; trigger_orders_
  - [None] Live exchange: regular=2, trigger=3, total=5, data_verified=True; trigger API issue: ERR_INTERNAL (code=50001,
  - [None] Open orders API route at line 28: ### `/api/orders/open` (routes_orders.py)
  - [None] Frontend open orders hook at line 114:             {"path": "frontend/src/app/api.ts", "line": "678", "text": 
  - [diagnostic] exchange_total=5, regular=2, trigger=3, cache_raw=5, dashboard_effective=5 (source=crypto_com_api); checked_at
  - [diagnostic] Open order counts differ across exchange, database, and dashboard
  - [database] table=exchange_orders; row_count=1; timestamps=['2026-06-16T15:03:33.460908+00:00']; query=SELECT COUNT(*) AS 
  - [log] [2026-06-16T15:03:33.954365+00:00] container=github_app_monitor.log:       YES - GitHub App or legacy PAT conf
  - [log] [2026-06-16T15:03:33.954365+00:00] container=github_app_monitor_latest.log:       YES - GitHub App or legacy P
  - [log] [2026-06-16 14:53:40] container=dpkg.log: 2026-06-16 14:53:40 status triggers-pending libc-bin:amd64 2.36-9+de
  - [repository] tests/test_jarvis_diagnostic_tools.py:114 —             {"path": "frontend/src/app/api.ts", "line": "678", "te
  - [repository] app/jarvis/execution_tools/diagnose_open_orders.py:203 —         if "frontend" in m.get("path", "") or "getOpe
  - [repository] app/jarvis/execution_tools/diagnose_open_orders.py:216 —         detail="Frontend calls getOpenOrders() -> GET
  - [repository] app/jarvis/execution_tools/diagnose_open_orders.py:459 —         "frontend_hook": "getOpenOrders() in frontend
  - [repository] app/jarvis/execution_tools/search_repository.py:12 —         "getOpenOrders",
  - [runtime] Health check status=pass
RANKED:
  - 96.0 No active dashboard/exchange mismatch detected
  - 100.0 Stale dashboard cache not refreshed by exchange sync
  - 33.0 FILLED orders exist in database but dashboard trade history does not d
  - 33.0 Crypto.com API credentials missing or misconfigured in runtime.env

#### a5439a76 | orders | executed_orders_missing | conf=100.0
OBJ: Why are executed orders missing? investigate btc orders
ROOT: FILLED orders exist in database but dashboard trade history does not display them
FIX: Verify trade-history API route returns FILLED exchange_orders rows and frontend renders them.
SUMMARY: Why are executed orders missing? investigate btc orders
- table=exchange_orders; row_count=3; timestamps=['2026-06-16T15:03:38.317030+00:00']; query=SELECT status, COUNT(*) AS co
- table=exchange_orders; status_counts: FILLED=149, UNKNOWN=3, ACTIVE=2
- table=exchange_orders; row_count=50; order_ids=
EVIDENCE (10):
  - [database] table=exchange_orders; row_count=3; timestamps=['2026-06-16T15:03:38.317030+00:00']; query=SELECT status, COUN
  - [database] table=exchange_orders; status_counts: FILLED=149, UNKNOWN=3, ACTIVE=2
  - [database] table=exchange_orders; row_count=50; order_ids=['5755600488945374736', '5755600483209949691', '575560048672723
  - [log] No log matches for keywords=('FILLED', 'executed', 'BTC', 'order', 'trade') in services=['backend-aws', 'front
  - [repository] import_orders.py:3 — Import executed orders from CSV file into the order_history database
  - [repository] import_orders.py:20 —     conn = sqlite3.connect('order_history.db')
  - [repository] import_orders.py:25 —         CREATE TABLE IF NOT EXISTS order_history (
  - [repository] import_orders.py:124 —                         INSERT OR REPLACE INTO order_history
  - [repository] perf_investigation_log.md:139 — 2. **Reduced Page Size**: Reduced `page_size` in `sync_order_history()` from 2
  - [runtime] Health check status=pass
RANKED:
  - 100.0 FILLED orders exist in database but dashboard trade history does not d
  - 48.0 Trigger order API failure blocks cache updates
  - 48.0 Database has open orders but dashboard cache is empty
  - 48.0 All sources agree: zero open orders on exchange

#### c7eae0f4 | orders | open_orders_empty | conf=96.0
OBJ: Why are open orders empty?
ROOT: No active dashboard/exchange mismatch detected
FIX: No dashboard/exchange sync repair needed based on current live counts.
SUMMARY: Why are open orders empty?
- UI screenshot
- Open-status count (NEW/ACTIVE/PARTIALLY_FILLED): 2; query=SELECT COUNT(*) AS count FROM exchange_orders WHERE status IN 
- Orders by status: {'FILLED': 149, 'UNKNOWN': 3, 'ACTIVE': 2}
- Latest orders sample: [{'id': 154, 'exchange_order_id': '738174901019
EVIDENCE (22):
  - [image] UI screenshot
  - [None] Open-status count (NEW/ACTIVE/PARTIALLY_FILLED): 2; query=SELECT COUNT(*) AS count FROM exchange_orders WHERE 
  - [None] Orders by status: {'FILLED': 149, 'UNKNOWN': 3, 'ACTIVE': 2}
  - [None] Latest orders sample: [{'id': 154, 'exchange_order_id': '73817490101936697', 'symbol': 'BTC_USD', 'side': 'SEL
  - [None] Open position symbols: [{'symbol': 'DGB_USD', 'open_commitments': 6}, {'symbol': 'SOL_USD', 'open_commitments'
  - [None] Raw in-memory cache contains 5 open orders; last_updated=2026-06-16 15:41:47.057521+00:00
  - [None] Dashboard API effective count=5 via source=crypto_com_api, sync_status=ok, data_verified=True; trigger_orders_
  - [None] Live exchange: regular=2, trigger=3, total=5, data_verified=True; trigger API issue: ERR_INTERNAL (code=50001,
  - [None] Open orders API route at line 28: ### `/api/orders/open` (routes_orders.py)
  - [None] Frontend open orders hook at line 203:         if "frontend" in m.get("path", "") or "getOpenOrders" in m.get(
  - [diagnostic] exchange_total=5, regular=2, trigger=3, cache_raw=5, dashboard_effective=5 (source=crypto_com_api); checked_at
  - [exchange] Trigger-order API error_code=50001: ERR_INTERNAL
  - [diagnostic] Open order counts differ across exchange, database, and dashboard
  - [exchange] Exchange=5, DB=2, dashboard=5; checked_at=2026-06-16T15:42:05.467619+00:00
  - [diagnostic] Reconciliation found 6 discrepancy(ies)
  - [database] table=exchange_orders; row_count=1; timestamps=['2026-06-16T15:42:05.469213+00:00']; query=SELECT COUNT(*) AS 
  - [log] No log matches for keywords=('open orders', 'sync', 'cache') in services=['backend-aws', 'frontend-aws', 'mark
  - [repository] app/jarvis/execution_tools/diagnose_open_orders.py:203 —         if "frontend" in m.get("path", "") or "getOpe
  - [repository] app/jarvis/execution_tools/diagnose_open_orders.py:216 —         detail="Frontend calls getOpenOrders() -> GET
  - [repository] app/jarvis/execution_tools/diagnose_open_orders.py:459 —         "frontend_hook": "getOpenOrders() in frontend
  - [repository] app/jarvis/execution_tools/search_repository.py:12 —         "getOpenOrders",
  - [repository] app/jarvis/agents/repository_agent.py:83 —         queries.extend(["getOpenOrders", "/orders/open", "open_orde
RANKED:
  - 96.0 No active dashboard/exchange mismatch detected
  - 83.0 Stale dashboard cache not refreshed by exchange sync
  - 48.0 FILLED orders exist in database but dashboard trade history does not d
  - 48.0 All sources agree: zero open orders on exchange

#### 5cb222df | orders | open_orders_empty | conf=96.0
OBJ: Why are open orders empty?
ROOT: No active dashboard/exchange mismatch detected
FIX: No dashboard/exchange sync repair needed based on current live counts.
SUMMARY: Why are open orders empty?
- UI screenshot
- Open-status count (NEW/ACTIVE/PARTIALLY_FILLED): 2; query=SELECT COUNT(*) AS count FROM exchange_orders WHERE status IN 
- Orders by status: {'FILLED': 149, 'UNKNOWN': 3, 'ACTIVE': 2}
- Latest orders sample: [{'id': 154, 'exchange_order_id': '738174901019
EVIDENCE (22):
  - [image] UI screenshot
  - [None] Open-status count (NEW/ACTIVE/PARTIALLY_FILLED): 2; query=SELECT COUNT(*) AS count FROM exchange_orders WHERE 
  - [None] Orders by status: {'FILLED': 149, 'UNKNOWN': 3, 'ACTIVE': 2}
  - [None] Latest orders sample: [{'id': 154, 'exchange_order_id': '73817490101936697', 'symbol': 'BTC_USD', 'side': 'SEL
  - [None] Open position symbols: [{'symbol': 'DGB_USD', 'open_commitments': 6}, {'symbol': 'SOL_USD', 'open_commitments'
  - [None] Raw in-memory cache contains 5 open orders; last_updated=2026-06-16 15:42:26.642066+00:00
  - [None] Dashboard API effective count=5 via source=crypto_com_api, sync_status=ok, data_verified=True; trigger_orders_
  - [None] Live exchange: regular=2, trigger=3, total=5, data_verified=True; trigger API issue: ERR_INTERNAL (code=50001,
  - [None] Open orders API route at line 28: ### `/api/orders/open` (routes_orders.py)
  - [None] Frontend open orders hook at line 203:         if "frontend" in m.get("path", "") or "getOpenOrders" in m.get(
  - [diagnostic] exchange_total=5, regular=2, trigger=3, cache_raw=5, dashboard_effective=5 (source=crypto_com_api); checked_at
  - [exchange] Trigger-order API error_code=50001: ERR_INTERNAL
  - [diagnostic] Open order counts differ across exchange, database, and dashboard
  - [exchange] Exchange=5, DB=2, dashboard=5; checked_at=2026-06-16T15:42:34.072277+00:00
  - [diagnostic] Reconciliation found 6 discrepancy(ies)
  - [database] table=exchange_orders; row_count=1; timestamps=['2026-06-16T15:42:34.076797+00:00']; query=SELECT COUNT(*) AS 
  - [log] No log matches for keywords=('open orders', 'sync', 'cache') in services=['backend-aws', 'frontend-aws', 'mark
  - [repository] app/jarvis/execution_tools/diagnose_open_orders.py:203 —         if "frontend" in m.get("path", "") or "getOpe
  - [repository] app/jarvis/execution_tools/diagnose_open_orders.py:216 —         detail="Frontend calls getOpenOrders() -> GET
  - [repository] app/jarvis/execution_tools/diagnose_open_orders.py:459 —         "frontend_hook": "getOpenOrders() in frontend
  - [repository] app/jarvis/execution_tools/search_repository.py:12 —         "getOpenOrders",
  - [repository] app/jarvis/agents/repository_agent.py:83 —         queries.extend(["getOpenOrders", "/orders/open", "open_orde
RANKED:
  - 96.0 No active dashboard/exchange mismatch detected
  - 83.0 Stale dashboard cache not refreshed by exchange sync
  - 48.0 FILLED orders exist in database but dashboard trade history does not d
  - 48.0 All sources agree: zero open orders on exchange

#### cd4b339b | api | generic | conf=27.0
OBJ: Analyze recent error logs for production incidents
ROOT: FILLED orders exist in database but dashboard trade history does not display them
FIX: Verify trade-history API route returns FILLED exchange_orders rows and frontend renders them.
SUMMARY: Analyze recent error logs for production incidents
- Health check status=fail
- No log matches for keywords=['error'] in services=['backend-aws', 'frontend-aws', 'market-updater-aws']; match_count=0
- tests/test_jarvis_diagnostic_tools.py:114 —             {"path": "frontend/src/app/api.ts", "line":
EVIDENCE (7):
  - [runtime] Health check status=fail
  - [log] No log matches for keywords=['error'] in services=['backend-aws', 'frontend-aws', 'market-updater-aws']; match
  - [repository] tests/test_jarvis_diagnostic_tools.py:114 —             {"path": "frontend/src/app/api.ts", "line": "678", "te
  - [repository] app/jarvis/execution_tools/diagnose_open_orders.py:203 —         if "frontend" in m.get("path", "") or "getOpe
  - [repository] app/jarvis/execution_tools/diagnose_open_orders.py:216 —         detail="Frontend calls getOpenOrders() -> GET
  - [repository] app/jarvis/execution_tools/diagnose_open_orders.py:459 —         "frontend_hook": "getOpenOrders() in frontend
  - [repository] app/jarvis/execution_tools/search_repository.py:12 —         "getOpenOrders",
RANKED:
  - 27.0 FILLED orders exist in database but dashboard trade history does not d
  - 27.0 Trigger order API failure blocks cache updates
  - 27.0 Crypto.com API credentials missing or misconfigured in runtime.env
  - 27.0 Duplicated API secret in runtime.env causes Crypto.com auth failure (4

#### 3f35a4d6 | orders | open_orders_empty | conf=96.0
OBJ: Why are open orders empty?
ROOT: No active dashboard/exchange mismatch detected
FIX: No dashboard/exchange sync repair needed based on current live counts.
SUMMARY: Why are open orders empty?
- Open-status count (NEW/ACTIVE/PARTIALLY_FILLED): 5; query=SELECT COUNT(*) AS count FROM exchange_orders WHERE status IN 
- Orders by status: {'FILLED': 149, 'ACTIVE': 5}
- Latest orders sample: [{'id': 153, 'exchange_order_id': '73817490101944530', 'symbol': 'BTC_USD', '
EVIDENCE (21):
  - [None] Open-status count (NEW/ACTIVE/PARTIALLY_FILLED): 5; query=SELECT COUNT(*) AS count FROM exchange_orders WHERE 
  - [None] Orders by status: {'FILLED': 149, 'ACTIVE': 5}
  - [None] Latest orders sample: [{'id': 153, 'exchange_order_id': '73817490101944530', 'symbol': 'BTC_USD', 'side': 'SEL
  - [None] Open position symbols: [{'symbol': 'DGB_USD', 'open_commitments': 6}, {'symbol': 'SOL_USD', 'open_commitments'
  - [None] Raw in-memory cache contains 5 open orders; last_updated=2026-06-19 19:31:36.222731+00:00
  - [None] Dashboard API effective count=5 via source=crypto_com_api, sync_status=ok, data_verified=True; trigger_orders_
  - [None] Live exchange: regular=2, trigger=3, total=5, data_verified=True; trigger API issue: ERR_INTERNAL (code=50001,
  - [None] Open orders API route at line 28: ### `/api/orders/open` (routes_orders.py)
  - [None] Frontend open orders hook at line 114:             {"path": "frontend/src/app/api.ts", "line": "678", "text": 
  - [diagnostic] exchange_total=5, regular=2, trigger=3, cache_raw=5, dashboard_effective=5 (source=crypto_com_api); checked_at
  - [exchange] Trigger-order API error_code=50001: ERR_INTERNAL
  - [diagnostic] Open orders exist in database and cache
  - [exchange] Exchange=5, DB=5, dashboard=5; checked_at=2026-06-19T19:32:05.802602+00:00
  - [diagnostic] Reconciliation found 6 discrepancy(ies)
  - [database] table=exchange_orders; row_count=1; timestamps=['2026-06-19T19:32:05.804414+00:00']; query=SELECT COUNT(*) AS 
  - [log] No log matches for keywords=('open orders', 'sync', 'cache') in services=['backend-aws', 'frontend-aws', 'mark
  - [repository] tests/test_jarvis_diagnostic_tools.py:114 —             {"path": "frontend/src/app/api.ts", "line": "678", "te
  - [repository] scripts/diag/run_acw_v2_bugfix_validation.py:169 —         "expected_tests": "useOrders.test.ts with mocked ge
  - [repository] app/jarvis/execution_tools/diagnose_open_orders.py:203 —         if "frontend" in m.get("path", "") or "getOpe
  - [repository] app/jarvis/execution_tools/diagnose_open_orders.py:216 —         detail="Frontend calls getOpenOrders() -> GET
  - [repository] app/jarvis/execution_tools/diagnose_open_orders.py:459 —         "frontend_hook": "getOpenOrders() in frontend
RANKED:
  - 96.0 No active dashboard/exchange mismatch detected
  - 83.0 Stale dashboard cache not refreshed by exchange sync
  - 75.0 Open orders exist in database and cache
  - 48.0 FILLED orders exist in database but dashboard trade history does not d

#### 5b76cf57 | portfolio | portfolio_reconciliation_mismatch | conf=90.5
OBJ: Investigate portfolio reconciliation mismatch
ROOT: Portfolio equity derived from balances because exchange API omits equity field
FIX: Map exchange-reported equity/net_equity from get_account_summary response into portfolio_cache.
SUMMARY: Investigate portfolio reconciliation mismatch
- table=exchange_orders; row_count=7; timestamps=['2026-06-19T20:18:09.799687+00:00']; query=SELECT symbol, COUNT(*) AS op
- Health check status=fail
- PORTFOLIO_CONCLUSION.md:93 — Crypto.com API → portfolio_cache.py → Database → API → Frontend
- tests/t
EVIDENCE (9):
  - [database] table=exchange_orders; row_count=7; timestamps=['2026-06-19T20:18:09.799687+00:00']; query=SELECT symbol, COUN
  - [runtime] Health check status=fail
  - [repository] PORTFOLIO_CONCLUSION.md:93 — Crypto.com API → portfolio_cache.py → Database → API → Frontend
  - [repository] tests/test_portfolio_value_reconciliation.py:10 — from app.services.portfolio_cache import get_portfolio_summa
  - [repository] tests/test_portfolio_value_reconciliation.py:118 —         with patch('app.services.portfolio_cache.trade_clie
  - [repository] tests/test_portfolio_value_reconciliation.py:122 —             with patch('app.services.portfolio_cache.resolv
  - [repository] tests/test_portfolio_value_reconciliation.py:126 —                 with patch('app.services.portfolio_cache._t
  - [log] No log matches for keywords=('portfolio', 'equity', 'reconciliation', 'balance', 'derived') in services=['back
  - [None] Exchange equity fields found: [('accounts[0].market_value', 4.88408262), ('accounts[1].market_value', 0.064742
RANKED:
  - 90.5 Portfolio equity derived from balances because exchange API omits equi
  - 26.0 FILLED orders exist in database but dashboard trade history does not d
  - 26.0 Trigger order API failure blocks cache updates
  - 26.0 Crypto.com API credentials missing or misconfigured in runtime.env

#### 99e5946a | api | jarvis_task_failing | conf=27.0
OBJ: Why is Jarvis task failing?
ROOT: FILLED orders exist in database but dashboard trade history does not display them
FIX: Verify trade-history API route returns FILLED exchange_orders rows and frontend renders them.
SUMMARY: Why is Jarvis task failing?
- No log matches for keywords=('jarvis', 'task', 'failed', 'error') in services=['backend-aws', 'frontend-aws', 'market-up
- tests/test_repository_graph.py:21 —             {"path": "backend/app/jarvis/execution/service.py", "line_count": 100, "
- tests/test_patch_agent.p
EVIDENCE (7):
  - [log] No log matches for keywords=('jarvis', 'task', 'failed', 'error') in services=['backend-aws', 'frontend-aws', 
  - [repository] tests/test_repository_graph.py:21 —             {"path": "backend/app/jarvis/execution/service.py", "line_coun
  - [repository] tests/test_patch_agent.py:14 —         "modules": [{"path": "backend/app/jarvis/execution/service.py", "line_c
  - [repository] app/jarvis/execution_tools/search_repository.py:70 —         "jarvis/execution",
  - [repository] app/jarvis/agents/patch_agent.py:41 —     return candidates[:5] or ["backend/app/jarvis/execution/service.py"]
  - [repository] tests/test_open_order_investigation.py:12 — from app.jarvis.investigations.investigation_runner import collect
  - [runtime] Health check status=fail
RANKED:
  - 27.0 FILLED orders exist in database but dashboard trade history does not d
  - 27.0 Trigger order API failure blocks cache updates
  - 27.0 Crypto.com API credentials missing or misconfigured in runtime.env
  - 27.0 Duplicated API secret in runtime.env causes Crypto.com auth failure (4

#### ada36c20 | dashboard | dashboard_exchange_mismatch | conf=96.0
OBJ: Why does dashboard differ from exchange?
ROOT: No active dashboard/exchange mismatch detected
FIX: No dashboard/exchange sync repair needed based on current live counts.
SUMMARY: Why does dashboard differ from exchange?
- Exchange=5, DB=5, dashboard=5; checked_at=2026-06-19T21:49:35.861252+00:00
- Trigger-order API error_code=50001: ERR_INTERNAL
- Reconciliation found 6 discrepancy(ies)
- Open-status count (NEW/ACTIVE/PARTIALLY_FILLED): 5; query=SELECT COUNT(*) AS count FROM
EVIDENCE (23):
  - [exchange] Exchange=5, DB=5, dashboard=5; checked_at=2026-06-19T21:49:35.861252+00:00
  - [exchange] Trigger-order API error_code=50001: ERR_INTERNAL
  - [diagnostic] Reconciliation found 6 discrepancy(ies)
  - [None] Open-status count (NEW/ACTIVE/PARTIALLY_FILLED): 5; query=SELECT COUNT(*) AS count FROM exchange_orders WHERE 
  - [None] Orders by status: {'FILLED': 149, 'ACTIVE': 5}
  - [None] Latest orders sample: [{'id': 153, 'exchange_order_id': '73817490101944530', 'symbol': 'BTC_USD', 'side': 'SEL
  - [None] Open position symbols: [{'symbol': 'DGB_USD', 'open_commitments': 6}, {'symbol': 'SOL_USD', 'open_commitments'
  - [None] Raw in-memory cache contains 5 open orders; last_updated=2026-06-19 21:49:33.495060+00:00
  - [None] Dashboard API effective count=5 via source=crypto_com_api, sync_status=ok, data_verified=True; trigger_orders_
  - [None] Live exchange: regular=2, trigger=3, total=5, data_verified=True; trigger API issue: ERR_INTERNAL (code=50001,
  - [None] Open orders API route at line 28: ### `/api/orders/open` (routes_orders.py)
  - [None] Frontend open orders hook at line 203:         if "frontend" in m.get("path", "") or "getOpenOrders" in m.get(
  - [diagnostic] exchange_total=5, regular=2, trigger=3, cache_raw=5, dashboard_effective=5 (source=crypto_com_api); checked_at
  - [diagnostic] Open orders exist in database and cache
  - [database] table=exchange_orders; row_count=1; timestamps=['2026-06-19T21:49:51.746010+00:00']; query=SELECT COUNT(*) AS 
  - [log] [2026-06-19T21:49:52.764313+00:00] container=github_app_monitor.log:       YES - GitHub App or legacy PAT conf
  - [log] [2026-06-19T21:49:52.764313+00:00] container=github_app_monitor_latest.log:       YES - GitHub App or legacy P
  - [repository] app/jarvis/execution_tools/diagnose_open_orders.py:203 —         if "frontend" in m.get("path", "") or "getOpe
  - [repository] app/jarvis/execution_tools/diagnose_open_orders.py:216 —         detail="Frontend calls getOpenOrders() -> GET
  - [repository] app/jarvis/execution_tools/diagnose_open_orders.py:459 —         "frontend_hook": "getOpenOrders() in frontend
  - [repository] app/jarvis/execution_tools/search_repository.py:12 —         "getOpenOrders",
  - [repository] app/jarvis/agents/repository_agent.py:83 —         queries.extend(["getOpenOrders", "/orders/open", "open_orde
  - [runtime] Health check status=fail
RANKED:
  - 96.0 No active dashboard/exchange mismatch detected
  - 100.0 Stale dashboard cache not refreshed by exchange sync
  - 75.0 Open orders exist in database and cache
  - 33.0 FILLED orders exist in database but dashboard trade history does not d

#### 9c6c5879 | deployment | generic | conf=50.0
OBJ: Check database health and recent query errors
ROOT: Deployment health check failing
FIX: Inspect container logs and restore failing service before traffic resumes.
SUMMARY: Check database health and recent query errors
- Health check status=pass
- [2026-06-19T22:01:23.172099+00:00] container=github_app_monitor.log:     ERROR: No backend container running (backend-aw
- [2026-06-19T22:01:23.172099+00:00] container=github_app_monitor_latest.log:     ERROR: No backend cont
EVIDENCE (8):
  - [runtime] Health check status=pass
  - [log] [2026-06-19T22:01:23.172099+00:00] container=github_app_monitor.log:     ERROR: No backend container running (
  - [log] [2026-06-19T22:01:23.172099+00:00] container=github_app_monitor_latest.log:     ERROR: No backend container ru
  - [repository] app/jarvis/execution_tools/search_repository.py:36 —         "JarvisControlTab",
  - [repository] app/jarvis/execution_tools/search_repository.py:72 —         "JarvisControlTab",
  - [repository] tests/test_trading_guardrails.py:129 — class TestMaxOpenOrdersTotal:
  - [repository] tests/test_jarvis_diagnostic_tools.py:62 — class TestDiagnoseOpenOrders:
  - [repository] tests/test_jarvis_diagnostic_tools.py:114 —             {"path": "frontend/src/app/api.ts", "line": "678", "te
RANKED:
  - 50.0 Deployment health check failing
  - 30.0 FILLED orders exist in database but dashboard trade history does not d
  - 30.0 Trigger order API failure blocks cache updates
  - 30.0 Crypto.com API credentials missing or misconfigured in runtime.env

#### fe5f566e | websocket | websocket_prices_stale | conf=63.0
OBJ: Why are websocket prices stale?
ROOT: Websocket price feed disconnected or not receiving updates
FIX: Restart market-updater service and verify websocket subscription health.
SUMMARY: Why are websocket prices stale?
- app/factory.py:843 —         # Start real-time price stream for dashboard WebSocket (/api/ws/prices); controlled by ENAB
- app/factory.py:858 —             from app.services.websocket_manager import stop_websocket
- app/factory.py:859 —             await stop_websoc
EVIDENCE (11):
  - [repository] app/factory.py:843 —         # Start real-time price stream for dashboard WebSocket (/api/ws/prices); controll
  - [repository] app/factory.py:858 —             from app.services.websocket_manager import stop_websocket
  - [repository] app/factory.py:859 —             await stop_websocket()
  - [repository] app/factory.py:860 —             logger.info("WebSocket stopped on shutdown")
  - [repository] app/factory.py:862 —             logger.error(f"Error stopping WebSocket: {e}")
  - [log] [2026-06-19T22:48:24.729898+00:00] container=github_app_monitor.log:   -- backend-aws (last 200 lines) --
  - [log] [2026-06-19T22:48:24.729898+00:00] container=github_app_monitor.log:   -- backend-aws-canary (last 200 lines) 
  - [log] [2026-06-19T22:48:24.729898+00:00] container=github_app_monitor.log:   backend-aws (automated-trading-platform
  - [log] [2026-06-19T22:48:24.729898+00:00] container=github_app_monitor.log:   backend-aws-canary (automated-trading-p
  - [log] [2026-06-19T22:48:24.729898+00:00] container=github_app_monitor.log:   backend-aws /ping_fast: ok
  - [runtime] Health check status=fail
RANKED:
  - 63.0 Websocket price feed disconnected or not receiving updates
  - 43.0 FILLED orders exist in database but dashboard trade history does not d
  - 43.0 Trigger order API failure blocks cache updates
  - 43.0 Crypto.com API credentials missing or misconfigured in runtime.env