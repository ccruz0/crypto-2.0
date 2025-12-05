"""
Workflows registry for monitoring workflows.

This module defines all available monitoring workflows with their metadata,
including schedule, endpoints, and descriptions.
"""
from typing import Dict, List, Optional, Any

# Registry of all monitoring workflows
WORKFLOWS: List[Dict[str, Any]] = [
    {
        "id": "watchlist_consistency",
        "name": "Watchlist Consistency Check",
        "description": "Compares backend vs watchlist for all symbols, including throttle and alert flags.",
        "run_endpoint": "/monitoring/workflows/watchlist_consistency/run",
        "schedule": "Nightly at 03:00 (Bali time)",
        "automated": True,
    },
    {
        "id": "daily_summary",
        "name": "Daily Summary",
        "description": "Envía resumen diario del portfolio y actividad de trading",
        "run_endpoint": None,  # No manual trigger endpoint yet
        "schedule": "Diario a las 8:00 AM",
        "automated": True,
    },
    {
        "id": "sell_orders_report",
        "name": "Sell Orders Report",
        "description": "Reporte de órdenes de venta pendientes",
        "run_endpoint": None,  # No manual trigger endpoint yet
        "schedule": "Diario a las 7:00 AM (Bali time)",
        "automated": True,
    },
    {
        "id": "sl_tp_check",
        "name": "SL/TP Check",
        "description": "Verifica posiciones sin órdenes de Stop Loss o Take Profit",
        "run_endpoint": None,  # No manual trigger endpoint yet
        "schedule": "Diario a las 8:00 AM",
        "automated": True,
    },
    {
        "id": "telegram_commands",
        "name": "Telegram Commands",
        "description": "Procesa comandos recibidos por Telegram",
        "run_endpoint": None,  # Continuous process, no manual trigger
        "schedule": "Continuo (cada segundo)",
        "automated": True,
    },
    {
        "id": "dashboard_snapshot",
        "name": "Dashboard Snapshot",
        "description": "Actualiza el snapshot del dashboard para mejorar rendimiento",
        "run_endpoint": None,  # Continuous process, no manual trigger
        "schedule": "Cada 60 segundos",
        "automated": True,
    },
]


def get_workflow_by_id(workflow_id: str) -> Optional[Dict[str, Any]]:
    """Get workflow by ID."""
    for workflow in WORKFLOWS:
        if workflow["id"] == workflow_id:
            return workflow
    return None


def get_all_workflows() -> List[Dict[str, Any]]:
    """Get all workflows."""
    return WORKFLOWS.copy()






