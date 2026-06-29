import ast
import inspect
import sys
from pathlib import Path

# Ensure `backend/` is on sys.path so `import app...` works when pytest is run from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _decision_assignment_indents(src: str, name: str) -> list[int]:
    """Return the indentation (col offset) of every `<name> = ...` assignment."""
    tree = ast.parse(src)
    indents: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    indents.append(node.col_offset)
    return indents


def test_decision_sell_bound_before_sell_only_path() -> None:
    """
    Regression guard (blocks ALL SELL alerts when broken):

    decision_buy / decision_sell must be assigned UNCONDITIONALLY (at the
    method's top indentation level, not only inside the `if buy_signal:`
    branch) before the SELL pipeline references them.

    Previously both were assigned only inside `if buy_signal:`, so on a
    SELL-only decision (buy_signal=False, sell_signal=True) the
    [ALERT_PIPELINE_TRACE] reference to `decision_sell` raised
    UnboundLocalError, aborting the monitor cycle before the SELL Telegram
    alert was dispatched.
    """
    from app.services.signal_monitor import SignalMonitorService

    src = inspect.getsource(SignalMonitorService._check_signal_for_coin_sync)
    # Dedent so the method body parses as a standalone module.
    src = inspect.cleandoc("\n".join(src.splitlines()[1:]))

    # After dedent, the method body lives at column 0; statements nested inside
    # `if buy_signal:` (or any block) have col_offset > 0.
    for name in ("decision_buy", "decision_sell"):
        indents = _decision_assignment_indents(src, name)
        assert indents, f"expected {name} to be assigned in the method"
        assert min(indents) == 0, (
            f"{name} must be assigned unconditionally at the top level of the "
            f"method (col 0), not only inside a conditional branch; "
            f"found assignment indents {sorted(set(indents))}"
        )


def test_decision_sell_has_no_unbound_guard() -> None:
    """
    The SELL-path [ALERT_PIPELINE_TRACE] must reference decision_sell directly.
    A `'decision_sell' in locals()` guard would mask the real bug (the binding),
    so once decision_sell is bound unconditionally the guard is unnecessary.
    """
    from app.services.signal_monitor import SignalMonitorService

    src = inspect.getsource(SignalMonitorService._check_signal_for_coin_sync)
    assert "'decision_sell' in locals()" not in src, (
        "decision_sell should be bound unconditionally; no locals() guard needed"
    )
