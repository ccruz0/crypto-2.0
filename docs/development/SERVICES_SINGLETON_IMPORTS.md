# ATP: `app.services` singletons and import rules

This doc generalizes the **module vs singleton instance** problem (first surfaced with `telegram_notifier`). See also [ATP_NOTIFIER_AND_DB_PATTERNS.md](./ATP_NOTIFIER_AND_DB_PATTERNS.md) for Telegram-specific detail and DB session rules.

## When `from app.services import X` is ambiguous

`backend/app/services/__init__.py` may **re-export** a name that matches a submodule file (e.g. `telegram_notifier`). Then:

- `from app.services import telegram_notifier` → **singleton instance**
- `import app.services.telegram_notifier as m` → often the **same instance** (package attribute shadows the submodule for that import form)
- `importlib.import_module("app.services.telegram_notifier")` → the real **module** (for patching `getRuntimeEnv`, constructing `TelegramNotifier()`, etc.)

If **`__init__.py` does not** define `X`, then `from app.services import X` loads the **submodule** `app.services.X` as usual — no shadowing.

**Rule:** Before assuming `from app.services import foo` is the module, check `app/services/__init__.py` for a re-export of `foo`.

## Singleton-style services (audit)

Module-level or lazy global instances under `backend/app/services/` (non-exhaustive; grep for `# Global instance` / `get_*` factories):

| Module | Export pattern | Same name as file? | Re-exported in `__init__.py`? |
|--------|----------------|--------------------|-------------------------------|
| `telegram_notifier.py` | `telegram_notifier = TelegramNotifier()` | **Yes** | **Yes** → shadowing risk |
| `signal_monitor.py` | `signal_monitor_service = SignalMonitorService()` | No | No |
| `exchange_sync.py` | `exchange_sync_service = ExchangeSyncService()` | No | No |
| `sl_tp_checker.py` | `sl_tp_checker_service = SLTPCheckerService()` | No | No |
| `scheduler.py` | `trading_scheduler = TradingScheduler()` | No | No |
| `daily_summary.py` | `daily_summary_service = DailySummaryService()` | No | No |
| `buy_index_monitor.py` | `buy_index_monitor = BuyIndexMonitorService()` | No | No |
| `data_sources.py` | `data_manager = DataSourceManager()` | No | No |
| `order_history_db.py` | `order_history_db = OrderHistoryDB()` | No | No |
| `brokers/crypto_com_trade.py` | `trade_client = CryptoComTradeClient()` | No (`trade_client` ≠ `crypto_com_trade`) | No |
| `margin_leverage_cache.py` | `get_leverage_cache()` lazy singleton | No | No |
| `margin_info_service.py` | `get_margin_info_service()` lazy singleton | No | No |
| `fill_tracker.py` | `get_fill_tracker()` lazy singleton | No | No |
| `event_bus.py` | `get_event_bus()` lazy singleton | No | No |

**Highest shadowing risk today:** only **`telegram_notifier`** (name matches submodule + re-export).

## Import conventions

### Runtime code needs the shared instance

```python
from app.services.telegram_notifier import telegram_notifier
# or, if re-exported and you accept package coupling:
from app.services import telegram_notifier
```

### Tests / patches need the module object

```python
import importlib

m = importlib.import_module("app.services.telegram_notifier")
monkeypatch.setattr(m, "getRuntimeEnv", lambda: "aws")
```

### Runtime code needs another service’s module (e.g. patch `trade_client` on module)

Prefer **importlib** if the submodule might ever be re-exported under the same name, or for consistency:

```python
import importlib
sm = importlib.import_module("app.services.signal_monitor")
monkeypatch.setattr(sm.trade_client, "place_market_order", fake)
```

## `app.services.__init__.py` policy

- **Keep** the `telegram_notifier` re-export (call sites and docs already rely on it).
- **Do not** add new `from app.services.<submodule> import <name>` re-exports where `<name>` equals the submodule’s basename (e.g. `foo` for `foo.py`) **unless** you document shadowing and update tests to use `importlib` for the module.
- Prefer **no new re-exports** for singletons; use explicit `from app.services.<module> import <singleton>` instead.

## Checklist: adding a new singleton service

1. Prefer a singleton name **different from** the module basename (e.g. `foo_service` in `foo.py`) to avoid confusion.
2. If the singleton name **must** match the module name, **do not** re-export it from `__init__.py` unless you accept the shadowing contract and document it here.
3. In tests that patch module-level symbols, use **`importlib.import_module("app.services.<module>")`**.
4. Add a one-line module docstring: “Exports class X and singleton `y`.”

## Risky patterns (watchlist)

| Pattern | Risk |
|---------|------|
| `import app.services.<name> as m` when `<name>` is re-exported from package | `m` may be the **instance**, not the module |
| `from app.services import <name>` in tests that need to patch module attributes | Can be wrong if `__init__.py` re-exports an instance under `<name>` |
| Monkeypatching `app.services` attribute without checking `__init__.py` | May patch the wrong object |

## Related tests

- `test_telegram_refresh_config.py` — `importlib` for notifier **module**; regression test for package **instance** import.
- `test_services_singleton_imports.py` — lightweight guards for module vs instance expectations.

## `live_trading_gate` (policy module, not a singleton)

`app.services.live_trading_gate` is imported from `signal_monitor`, `exchange_sync`, and `crypto_com_trade`. The file must exist in the repo (it was previously missing, causing `ModuleNotFoundError`). Tests must not register a `MagicMock` for this package name unless they intend to override behavior for that test only.

**Contract:** `assert_exchange_mutation_allowed` returns immediately when live trading is off (DB/env). `require_mutation_allowed_for_broker` runs in `crypto_com_trade` only after dry-run / `live_trading` short-circuits (including `create_stop_loss_take_profit_with_variations`, which uses `dry_run` / `self.live_trading` like other order helpers). Enforcement is still off (no raises after the live check); see module docstring in `live_trading_gate.py`.

**Tests:** `backend/tests/test_live_trading_gate.py` covers blocked branches and broker ordering.
