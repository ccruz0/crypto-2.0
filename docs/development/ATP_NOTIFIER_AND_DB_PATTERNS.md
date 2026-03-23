# ATP: Telegram notifier imports, DB sessions, and ORM typing

This document captures three recurring foot-guns and the supported patterns so new code does not repeat them.

**Other service singletons and package re-exports:** see [SERVICES_SINGLETON_IMPORTS.md](./SERVICES_SINGLETON_IMPORTS.md) (audit, `__init__.py` policy, test/patch patterns).

## 1. Telegram notifier: module vs singleton instance

The file `backend/app/services/telegram_notifier.py` defines:

- `TelegramNotifier` — the class
- `telegram_notifier` — a **module-level singleton instance** (`TelegramNotifier()`)

**Wrong mental model:** treating `telegram_notifier` as the module and calling `send_buy_signal` on it. On an empty `app.services` package, `from app.services import telegram_notifier` used to resolve to the **submodule** (the file), which does **not** expose `send_buy_signal` / `send_sell_signal` as module attributes — those are **methods on the instance**.

**Supported imports for sending alerts (instance methods):**

```python
from app.services.telegram_notifier import telegram_notifier
# or (same singleton, re-exported from app.services.__init__):
from app.services import telegram_notifier

telegram_notifier.send_buy_signal(...)
telegram_notifier.send_sell_signal(...)
```

### Shadowing warning (package re-export)

`app.services.__init__` assigns `telegram_notifier` to the **singleton instance**. That name sits on the `app.services` package and **shadows** the submodule for plain `import` statements:

```python
# WRONG for “give me the module” — this is the TelegramNotifier instance, not the module:
import app.services.telegram_notifier as telegram_notifier_module
```

**When you need the actual module** (patch `getRuntimeEnv`, `http_post`, construct `TelegramNotifier()`, etc.):

```python
import importlib

telegram_notifier_module = importlib.import_module("app.services.telegram_notifier")

monkeypatch.setattr(telegram_notifier_module, "getRuntimeEnv", lambda: "aws")
notifier = telegram_notifier_module.TelegramNotifier()
```

You can also use `from app.services.telegram_notifier import TelegramNotifier` — that loads the submodule correctly and imports the class by name.

**Tests:** Prefer `unittest.mock.patch.object(notifier, "send_buy_signal", ...)` on the imported singleton, or patch `alert_emitter.telegram_notifier`, instead of assigning to `notifier.send_buy_signal` by hand.

## 2. `SessionLocal` may be `None`

In `backend/app/database.py`, if engine creation fails or no URL is configured, `SessionLocal` is set to `None`. Calling `SessionLocal()` then raises: `'NoneType' object is not callable`.

**Scripts and one-off jobs** should open sessions with:

```python
from app.database import create_db_session

db = create_db_session()
try:
    ...
finally:
    db.close()
```

This raises a clear `RuntimeError` explaining that the DB is not configured.

For **missing tables** on an otherwise valid engine, scripts may use **`exit_2_if_missing_schema_tables`** (`app.database`) inside `except OperationalError` to print a fixed stderr line and exit with code **2** (see `count_orders.py` / `monitor_alerts.py`).

**Scope:** Prefer `create_db_session()` in `backend/scripts/`, `backend/tools/`, and small top-level `backend/*.py` utilities. Do **not** replace `SessionLocal` usage across `backend/app/` (FastAPI, schedulers, signal monitor) in drive-by changes — those paths often need `if SessionLocal is None` so the service keeps running.

**Audit log:** A repo-wide sweep of script/tool paths and what stayed unchanged is documented in [SESSION_LOCAL_SCRIPT_SWEEP.md](./SESSION_LOCAL_SCRIPT_SWEEP.md).

**Rule of thumb:** If the script imports `app.*` (models, services), use **`create_db_session()`** so URL resolution, Docker host fallback, and local SQLite behavior match the API. Reserve a **local** `create_engine` + `sessionmaker` only for rare tools that deliberately avoid importing `app.database` (not typical in this repo).

Scripts `trigger_manual_alert.py` and `monitor_alerts.py` live under **`backend/scripts/`** (not `backend/` root).

**FastAPI** keeps using `get_db()`, which yields `None` when the database is unavailable so routes can degrade gracefully — that behavior is intentional and different from scripts.

## 3. Pyright and classic SQLAlchemy `Column(...)` models

For declarative models that declare attributes as `Column(...)`, static analysis often types instance attributes as `Column[...]`, so assignments like `row.alert_enabled = True` look invalid even though they are correct at runtime.

**Acceptable in scripts/tests without migrating to `Mapped[]`:**

```python
setattr(row, "alert_enabled", True)
```

A full ORM typing migration (SQLAlchemy 2.0 `Mapped` annotations) is a separate effort.

## 4. Other services (singleton vs module)

Telegram is the only service **re-exported** from `app.services` under the same name as its submodule (shadowing). For a full list of module-level singletons, import rules, and how to add new services safely, see [SERVICES_SINGLETON_IMPORTS.md](./SERVICES_SINGLETON_IMPORTS.md).

## Quick checklist

- [ ] Calling `send_buy_signal` / `send_sell_signal`? Use the **singleton** import paths above.
- [ ] Patching module-level functions or constructing `TelegramNotifier()`? Use `importlib.import_module("app.services.telegram_notifier")` (not `import app.services.telegram_notifier as …`).
- [ ] Patching another `app.services.*` module (e.g. `signal_monitor`)? Prefer `importlib.import_module("app.services.<module>")` — see [SERVICES_SINGLETON_IMPORTS.md](./SERVICES_SINGLETON_IMPORTS.md).
- [ ] Standalone script under `backend/scripts/` or `backend/tools/` needs a DB session? Use `create_db_session()`, not bare `SessionLocal()` (see [SESSION_LOCAL_SCRIPT_SWEEP.md](./SESSION_LOCAL_SCRIPT_SWEEP.md)).
- [ ] Pyright complaints on ORM field assignment in a script? Use `setattr` until models use `Mapped`.
