"""Core mission lifecycle types and transition guards for autonomous Jarvis."""

from __future__ import annotations

from typing import Final

MISSION_STATUS_RECEIVED: Final[str] = "received"
MISSION_STATUS_PLANNING: Final[str] = "planning"
MISSION_STATUS_RESEARCHING: Final[str] = "researching"
MISSION_STATUS_EXECUTING: Final[str] = "executing"
MISSION_STATUS_WAITING_FOR_INPUT: Final[str] = "waiting_for_input"
MISSION_STATUS_WAITING_FOR_APPROVAL: Final[str] = "waiting_for_approval"
MISSION_STATUS_REVIEWING: Final[str] = "reviewing"
MISSION_STATUS_DONE: Final[str] = "done"
MISSION_STATUS_FAILED: Final[str] = "failed"

MISSION_STATUSES: Final[tuple[str, ...]] = (
    MISSION_STATUS_RECEIVED,
    MISSION_STATUS_PLANNING,
    MISSION_STATUS_RESEARCHING,
    MISSION_STATUS_EXECUTING,
    MISSION_STATUS_WAITING_FOR_INPUT,
    MISSION_STATUS_WAITING_FOR_APPROVAL,
    MISSION_STATUS_REVIEWING,
    MISSION_STATUS_DONE,
    MISSION_STATUS_FAILED,
)

TERMINAL_MISSION_STATUSES: Final[set[str]] = {
    MISSION_STATUS_DONE,
    MISSION_STATUS_FAILED,
}

ALLOWED_MISSION_TRANSITIONS: Final[dict[str, set[str]]] = {
    MISSION_STATUS_RECEIVED: {MISSION_STATUS_PLANNING, MISSION_STATUS_FAILED},
    MISSION_STATUS_PLANNING: {
        MISSION_STATUS_RESEARCHING,
        MISSION_STATUS_EXECUTING,
        MISSION_STATUS_WAITING_FOR_INPUT,
        MISSION_STATUS_FAILED,
    },
    MISSION_STATUS_RESEARCHING: {
        MISSION_STATUS_EXECUTING,
        MISSION_STATUS_WAITING_FOR_INPUT,
        MISSION_STATUS_FAILED,
    },
    MISSION_STATUS_EXECUTING: {
        MISSION_STATUS_WAITING_FOR_APPROVAL,
        MISSION_STATUS_WAITING_FOR_INPUT,
        MISSION_STATUS_REVIEWING,
        MISSION_STATUS_FAILED,
    },
    MISSION_STATUS_WAITING_FOR_INPUT: {
        MISSION_STATUS_PLANNING,
        MISSION_STATUS_RESEARCHING,
        MISSION_STATUS_EXECUTING,
        MISSION_STATUS_FAILED,
    },
    MISSION_STATUS_WAITING_FOR_APPROVAL: {
        MISSION_STATUS_EXECUTING,
        MISSION_STATUS_FAILED,
    },
    MISSION_STATUS_REVIEWING: {
        MISSION_STATUS_DONE,
        MISSION_STATUS_EXECUTING,
        MISSION_STATUS_FAILED,
    },
    MISSION_STATUS_DONE: set(),
    MISSION_STATUS_FAILED: set(),
}


def is_valid_mission_status(value: str) -> bool:
    return (value or "").strip() in MISSION_STATUSES


def can_transition_mission(from_status: str, to_status: str) -> bool:
    src = (from_status or "").strip()
    dst = (to_status or "").strip()
    return dst in ALLOWED_MISSION_TRANSITIONS.get(src, set())

