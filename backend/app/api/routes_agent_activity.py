"""Agent activity — panel de agentes del protocolo de revision multiangulo.

La tabla ``agent_activity`` la escriben las sesiones de revision (Claude)
al lanzar y cerrar cada agente. Este endpoint SOLO LEE; no decide nada y
no toca ninguna ruta de trading.

Estados derivados (no almacenados):
- TRABAJANDO: fila abierta (finished_at IS NULL) de hace < 30 min.
- SIN_CONFIRMAR: fila abierta de hace >= 30 min — la sesion que la abrio
  probablemente murio sin cerrarla. Nunca se muestra como actividad viva.
- LIBRE: la ultima fila del agente esta cerrada.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db

router = APIRouter()

AGENT_NAMES = [
    "atp-reglas-negocio",
    "atp-tecnico",
    "atp-encaje",
    "atp-economico",
    "atp-riesgo-despliegue",
    "atp-coherencia-doc",
]

_PERIOD_DAYS = {"today": 1, "week": 7, "month": 30, "year": 365}
_STALE_SECONDS = 1800  # 30 min


def _iso(dt):
    return dt.isoformat() if dt is not None else None


@router.get("/agents/activity")
def agent_activity(
    period: str = Query("week", pattern="^(today|week|month|year|all)$"),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    days = _PERIOD_DAYS.get(period)
    since = now - timedelta(days=days) if days else None

    # --- tarjetas: ultimo estado conocido de cada agente ---
    cards = []
    for name in AGENT_NAMES:
        row = db.execute(
            text(
                "SELECT task, status, started_at, finished_at, findings_count "
                "FROM agent_activity WHERE agent_name = :n "
                "ORDER BY started_at DESC LIMIT 1"
            ),
            {"n": name},
        ).fetchone()

        status = "LIBRE"
        task = started_at = finished_at = findings = None
        if row is not None:
            task, raw_status, started_at, finished_at, findings = row
            if finished_at is None and raw_status == "TRABAJANDO":
                age = (now - started_at).total_seconds()
                status = "TRABAJANDO" if age < _STALE_SECONDS else "SIN_CONFIRMAR"
            else:
                status = "LIBRE"

        cards.append(
            {
                "agent_name": name,
                "status": status,
                "task": task,
                "started_at": _iso(started_at),
                "finished_at": _iso(finished_at),
                "findings_count": findings,
            }
        )

    # --- historial filtrable ---
    hist_sql = (
        "SELECT agent_name, task, status, started_at, finished_at, "
        "findings_count, revision_id FROM agent_activity"
    )
    params = {}
    if since is not None:
        hist_sql += " WHERE started_at >= :since"
        params["since"] = since
    hist_sql += " ORDER BY started_at DESC LIMIT 200"

    history = [
        {
            "agent_name": r[0],
            "task": r[1],
            "status": r[2],
            "started_at": _iso(r[3]),
            "finished_at": _iso(r[4]),
            "duration_s": (r[4] - r[3]).total_seconds() if r[4] and r[3] else None,
            "findings_count": r[5],
            "revision_id": r[6],
        }
        for r in db.execute(text(hist_sql), params).fetchall()
    ]

    totals = {
        "runs": len(history),
        "revisions": len({h["revision_id"] for h in history if h["revision_id"]}),
        "findings": sum(h["findings_count"] or 0 for h in history),
        "busy_now": sum(1 for c in cards if c["status"] == "TRABAJANDO"),
    }

    return {
        "agents": cards,
        "history": history,
        "totals": totals,
        "period": period,
        "generated_at": now.isoformat(),
        # Los tokens por agente no estan disponibles: el consumo de los
        # subagentes vive en la facturacion de Anthropic, no aqui. Cuando
        # exista ese dato, añadir columna tokens a agent_activity.
        "tokens_available": False,
    }
