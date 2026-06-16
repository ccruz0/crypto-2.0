"""Async background loop for the investigation scheduler."""

from __future__ import annotations

import asyncio
import logging

from app.jarvis.investigations.scheduler import config as sched_config
from app.jarvis.investigations.scheduler.service import run_investigation_scheduler_cycle

logger = logging.getLogger(__name__)

_loop_running = False


def get_scheduler_runtime_state() -> dict:
    from app.jarvis.investigations.scheduler.leader import get_leader_state
    from app.jarvis.investigations.scheduler.service import get_last_cycle_snapshot

    leader = get_leader_state()
    snapshot = get_last_cycle_snapshot()
    return {
        "scheduler_running": _loop_running,
        "last_cycle_at": snapshot.get("last_cycle_at") or "",
        "last_cycle_result": snapshot.get("last_cycle_result") or {},
        "instance_id": snapshot.get("instance_id") or "",
        "leader": leader,
    }


async def start_investigation_scheduler_loop() -> None:
    """Run scheduler cycles periodically; never raises to the caller."""
    global _loop_running

    interval = sched_config.investigation_scheduler_interval_seconds()
    _loop_running = True
    logger.info("investigation_scheduler_loop_started interval=%ds", interval)

    loop = asyncio.get_running_loop()
    while True:
        if not sched_config.investigation_scheduler_enabled():
            await asyncio.sleep(interval)
            continue
        try:
            result = await loop.run_in_executor(None, run_investigation_scheduler_cycle)
            logger.info(
                "investigation_scheduler_cycle action=%s queued=%s",
                result.get("action"),
                result.get("queued_count"),
            )
        except Exception as exc:
            logger.exception("investigation_scheduler_cycle_error: %s", exc)
        await asyncio.sleep(interval)
