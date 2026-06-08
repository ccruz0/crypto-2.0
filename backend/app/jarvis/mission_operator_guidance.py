"""Operator-facing guidance strings (Notion + Telegram guided choices).

Kept free of orchestrator imports to avoid cycles.
"""

from __future__ import annotations

from typing import Any

def notion_options_from_guided_profile(profile: str, *, ctx: dict[str, Any] | None = None) -> tuple[str, ...]:
    """Human labels aligned with Telegram guided rows."""
    return tuple(label for _code, label in guided_button_rows_for_profile(profile, ctx=ctx))


def guided_button_rows_for_profile(
    profile: str,
    *,
    ctx: dict[str, Any] | None = None,
) -> list[tuple[str, str]]:
    """
    (callback_code, button_label) for ``jm:g:<mission_id>:<code>``.

    Codes are <= 4 ASCII chars to keep callback_data under Telegram limits.
    """
    raw = (profile or "").strip().lower()
    if raw == "perico_runtime":
        raw = "perico_repo_path"
    if raw not in ("generic_wait", "perico_repo_path", "perico_pytest", "perico_test_path"):
        raw = "generic_wait"
    c = raw
    ctx = ctx or {}
    fb = str(ctx.get("fallback_root") or "/app").strip() or "/app"
    rh = str(ctx.get("repo_root_hint") or "").strip()

    if c == "perico_test_path":
        return [
            ("full", "🧪 Ejecutar toda la suite (sin un solo archivo)"),
            ("app", "📁 Probar ruta de código en el contenedor"),
            ("clr", "🧹 Volver a detección automática de ruta"),
            ("stop", "⛔ Parar misión"),
        ]

    if c == "perico_pytest":
        return [
            ("app", "📁 Probar ruta de código en el contenedor"),
            ("clr", "🧹 Volver a detección automática de ruta"),
            ("retr", "🔁 Reintentar ejecución de tests"),
            ("stop", "⛔ Parar misión"),
        ]

    if c == "perico_repo_path":
        short = rh[:22] + ("…" if len(rh) > 22 else "") if rh else "detectada"
        return [
            ("app", "📁 Probar ruta de código en el contenedor"),
            ("clr", "🧹 Volver a detección automática de ruta"),
            ("retr", f"🔁 Reintentar con ruta {short}"),
            ("stop", "⛔ Parar misión"),
        ]

    # generic_wait: planner / goal shortfall / execution waiting for input
    return [
        ("logs", "📎 Aportar logs o salida de tests"),
        ("wide", "🔍 Seguir revisando código y tests"),
        ("retr", "🔁 Reintentar desde el último punto"),
        ("stop", "⛔ Parar misión"),
    ]


def resolve_guided_mission_input_text(code: str, *, ctx: dict[str, Any] | None) -> str | None:
    """
    Map a short callback code to the ``/mission input`` tail (Spanish, stable prefixes).

    Lines starting with ``[PERICO_ENV …]`` are stripped for the planner in ``continue_after_input``.

    Returns None when the code is unknown (caller should ignore or treat as noop).
    """
    c = (code or "").strip().lower()
    ctx = ctx or {}
    profile = str(ctx.get("profile") or "").strip().lower()
    rh = str(ctx.get("repo_root_hint") or "").strip()
    fb = str(ctx.get("fallback_root") or "/app").strip() or "/app"

    if c == "app":
        return (
            f"[PERICO_ENV PERICO_REPO_ROOT={fb}]\n"
            f"[OPERADOR_GUIADO] Forzar PERICO_REPO_ROOT={fb!r} y reintentar la misión."
        )
    if c == "clr":
        return (
            "[PERICO_ENV CLEAR PERICO_REPO_ROOT]\n"
            "[OPERADOR_GUIADO] Quitar PERICO_REPO_ROOT explícito; usar detección automática del runtime."
        )
    if c == "full":
        return (
            "[OPERADOR_GUIADO] PYTEST: ejecutar descubrimiento de tests sin ruta de archivo concreta "
            "(asumiendo cwd de backend correcto)."
        )
    if c == "logs":
        return (
            "[OPERADOR_GUIADO] Aporto o describo logs, salida de pytest o trazas relevantes "
            "en el contexto actual."
        )
    if c == "wide":
        return (
            "[OPERADOR_GUIADO] Continuar con inspección más amplia del repositorio y tests "
            "visibles; no forzar aún un parche único."
        )
    if c == "retr":
        if profile in ("perico_repo_path", "perico_pytest", "perico_test_path", "perico_runtime"):
            return (
                f"[PERICO_ENV PERICO_REPO_ROOT={fb}]\n"
                f"[OPERADOR_GUIADO] Reintento: aplicar raíz {fb!r} y continuar."
            )
        return "[OPERADOR_GUIADO] REINTENTO: volver a ejecutar la misión con la misma petición y configuración actual."
    if c == "stop":
        return "[OPERADOR_GUIADO] CANCELAR: no continuar con esta misión; archivar o cerrar."
    return None
