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


def _first_assign_and_use(src: str, name: str) -> tuple[int, int]:
    """Return (first_assignment_lineno, first_use_lineno) for a bare-name var."""
    tree = ast.parse(src)
    assign_lines: list[int] = []
    use_lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == name:
            if isinstance(node.ctx, ast.Store):
                assign_lines.append(node.lineno)
            elif isinstance(node.ctx, ast.Load):
                use_lines.append(node.lineno)
    return (min(assign_lines) if assign_lines else -1,
            min(use_lines) if use_lines else -1)


def test_sell_trace_throttle_metrics_bound_before_use() -> None:
    """
    Regression guard (same class of bug as decision_sell; also blocks SELL alerts):

    The SELL [ALERT_PIPELINE_TRACE] references throttle-metric variables
    (last_alert_at_utc_sell, seconds_since_last_sell, price_change_pct_sell).
    These must be assigned BEFORE their first use. Previously two were never
    assigned (NameError) and one was assigned only after the trace
    (UnboundLocalError), aborting the SELL-only cycle before the alert was sent.
    """
    from app.services.signal_monitor import SignalMonitorService

    src = inspect.getsource(SignalMonitorService._check_signal_for_coin_sync)
    src = inspect.cleandoc("\n".join(src.splitlines()[1:]))

    for name in (
        "last_alert_at_utc_sell",
        "seconds_since_last_sell",
        "price_change_pct_sell",
    ):
        assign_line, use_line = _first_assign_and_use(src, name)
        assert assign_line != -1, f"expected {name} to be assigned in the method"
        assert use_line != -1, f"expected {name} to be used in the method"
        assert assign_line <= use_line, (
            f"{name} must be assigned before first use "
            f"(assign@{assign_line}, use@{use_line})"
        )


def test_sell_send_block_binds_trace_dedup_origin() -> None:
    """
    Regression guard (same class of bug; final SELL-alert blocker):

    The SELL Telegram-send block references trace_id, dedup_key and alert_origin.
    Previously trace_id/dedup_key were never assigned at all, and alert_origin was
    bound only on the BUY path -> NameError on a SELL-only signal AFTER emit_alert
    ran. That NameError was caught and mislogged as a Telegram send failure,
    skipping the SENT state update and re-firing the SELL signal every cycle.

    These must be bound within the SELL send block, before their first use there.
    """
    from app.services.signal_monitor import SignalMonitorService

    src = inspect.getsource(SignalMonitorService._check_signal_for_coin_sync)

    block_start = src.index("if should_emit_telegram_sell:")
    sell_block = src[block_start:]
    first_use = sell_block.index("trace_id={trace_id} channel=")

    for binding in ("trace_id = ", "dedup_key = ", "alert_origin = get_runtime_origin()"):
        assert binding in sell_block, (
            f"SELL send block must bind {binding!r} so the SELL-only path does not "
            f"raise NameError after emit_alert()"
        )
        assert sell_block.index(binding) < first_use, (
            f"{binding!r} must be bound before its first use in the SELL send block"
        )
