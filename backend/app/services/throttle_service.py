"""Compat shim: `throttle_service` was renamed to `signal_throttle`.

Legacy imports (notably backend/app/services/signal_monitor.py) still do
`from app.services.throttle_service import ...`. Without this module that
import raised ModuleNotFoundError, and signal_monitor.py fell back to an
allow-all stub -> signal throttling was effectively DISABLED in production
(every alert showed "Throttle Disabled"; no 60s / price gating).

Re-exporting the real implementation makes the legacy import succeed and
restores the real throttle. Reversible: delete this file once signal_monitor.py
imports `app.services.signal_throttle` directly.
"""
from app.services.signal_throttle import *  # noqa: F401,F403
from app.services.signal_throttle import (  # noqa: F401
    SignalThrottleConfig,
    LastSignalSnapshot,
    build_strategy_key,
    fetch_signal_states,
    should_emit_signal,
    reset_throttle_state,
    set_force_next_signal,
    record_signal_event,
    compute_config_hash,
)
