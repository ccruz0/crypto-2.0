#!/usr/bin/env python3
"""
Quick validation of agent routing and callback selection (no Notion, no OpenClaw).

Usage:
  cd backend && PYTHONPATH=. python scripts/validate_agent_routing.py

Exit 0 if all checks pass; 1 otherwise.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    from app.services.agent_routing import route_task_with_reason
    from app.services.agent_callbacks import select_default_callbacks_for_task

    errors = []

    # Telegram
    t_tg = {
        "task": {"id": "val-tg", "task": "Alerts not being sent", "type": "telegram", "details": "Test"},
        "repo_area": {},
    }
    aid, reason = route_task_with_reason(t_tg)
    if aid != "telegram_alerts":
        errors.append(f"Telegram routing: expected telegram_alerts, got {aid} (reason={reason})")
    else:
        pack = select_default_callbacks_for_task(t_tg)
        if "Telegram" not in (pack.get("selection_reason") or ""):
            errors.append(f"Telegram callback: expected Telegram in reason, got {pack.get('selection_reason')}")
        elif not pack.get("apply_change_fn"):
            errors.append("Telegram callback: apply_change_fn is None")
        else:
            print("OK Telegram routing:", reason)

    # Execution
    t_ex = {
        "task": {"id": "val-ex", "task": "Order not in open orders", "type": "order", "details": "Test"},
        "repo_area": {},
    }
    aid2, reason2 = route_task_with_reason(t_ex)
    if aid2 != "execution_state":
        errors.append(f"Execution routing: expected execution_state, got {aid2} (reason={reason2})")
    else:
        pack2 = select_default_callbacks_for_task(t_ex)
        if "Execution" not in (pack2.get("selection_reason") or ""):
            errors.append(f"Execution callback: expected Execution in reason, got {pack2.get('selection_reason')}")
        elif not pack2.get("apply_change_fn"):
            errors.append("Execution callback: apply_change_fn is None")
        else:
            print("OK Execution routing:", reason2)

    if errors:
        for e in errors:
            print("FAIL:", e)
        return 1
    print("All routing checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
