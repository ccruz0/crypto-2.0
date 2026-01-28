import inspect
import sys
from pathlib import Path

# Ensure `backend/` is on sys.path so `import app...` works when pytest is run from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_check_signal_for_coin_sync_initializes_now_utc_once() -> None:
    """
    Regression guard:
    - now_utc must be initialized before first use
    - now_utc must not be re-assigned later in the function (avoids future unbound-local risks)
    """
    from app.services.signal_monitor import SignalMonitorService

    src = inspect.getsource(SignalMonitorService._check_signal_for_coin_sync)

    needle = "now_utc = datetime.now(timezone.utc)"
    assert src.count(needle) == 1, "now_utc must be initialized exactly once"

    lines = src.splitlines()
    assign_idx = next(i for i, line in enumerate(lines) if needle in line)

    # Find the first non-comment usage of now_utc after assignment
    use_idxs = [
        i
        for i, line in enumerate(lines)
        if "now_utc" in line and needle not in line and not line.lstrip().startswith("#")
    ]
    assert use_idxs, "expected now_utc to be used in the function"
    assert assign_idx < min(use_idxs), "now_utc must be initialized before first use"

