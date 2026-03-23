"""
ATP service package.

Re-exports the Telegram notifier **singleton** as ``telegram_notifier``. That shadows the
submodule name on the package: ``import app.services.telegram_notifier as m`` binds to the
**instance**, not the module. For the real module object (patching, ``TelegramNotifier``), use::

    import importlib
    m = importlib.import_module("app.services.telegram_notifier")

**Instance (alerts):**

    from app.services import telegram_notifier
    from app.services.telegram_notifier import telegram_notifier

See docs/development/ATP_NOTIFIER_AND_DB_PATTERNS.md and docs/development/SERVICES_SINGLETON_IMPORTS.md.

**Policy:** Only ``telegram_notifier`` is re-exported here. Do **not** add further
``from app.services.<submodule> import <same_name>`` re-exports without reading
SERVICES_SINGLETON_IMPORTS.md — that pattern shadows the submodule and breaks
``import app.services.<name> as ...`` for callers who need the **module**.
"""

from app.services.telegram_notifier import telegram_notifier

__all__ = ["telegram_notifier"]
