# Prompt para Cursor — mensaje de guardrail legible en Telegram (#3)

Copia en el agente de Cursor, raíz del repo `crypto-2.0`.

---

Trabaja en `ccruz0/crypto-2.0`. Objetivo: cuando una orden se bloquea por un guardrail, el mensaje
de Telegram debe explicarlo en lenguaje humano, no mostrar el código crudo
`system_core_one_active_trade_per_coin` / `GUARDRAIL_BLOCKED`.

**Contexto**
Los reason codes se emiten en `backend/app/services/signal_monitor.py`
(`reason_code=ReasonCode.GUARDRAIL_BLOCKED.value`) y el string de razón crudo (p.ej.
`system_core_one_active_trade_per_coin`, `system_core_max_open_trades count=5 max=5`,
`system_core_max_trade_usd ...`, `system_core_rsi ...`) viene de
`backend/app/services/system_core_trade_guards.py`. Hoy el mensaje "❌ ORDER FAILED" pasa ese string
tal cual al notificador de Telegram.

**Cambio**
1. Añade un helper de mapeo razón→texto humano (ES), p.ej. en
   `backend/app/utils/decision_reason.py` o un módulo nuevo `guardrail_messages.py`:

```python
def humanize_guardrail_reason(reason: str, symbol: str | None = None) -> str:
    base = (symbol or "la moneda").split("_")[0] if symbol else "la moneda"
    r = (reason or "").lower()
    if "one_active_trade_per_coin" in r:
        return f"🚫 Compra no ejecutada: {base} ya tiene una posición abierta (regla: 1 trade activo por moneda)."
    if "max_open_trades" in r:
        return "🚫 Compra no ejecutada: alcanzado el máximo de posiciones abiertas simultáneas."
    if "max_trade_usd" in r:
        return "🚫 Compra no ejecutada: el importe supera el máximo por operación."
    if "daily_drawdown" in r:
        return "🚫 Compra no ejecutada: alcanzado el límite de pérdida diaria (drawdown)."
    if r.startswith("system_core_rsi"):
        return "🚫 Compra no ejecutada: RSI fuera del rango permitido para comprar."
    if "max_orders_per_symbol_per_day" in r or "orders_today" in r:
        return f"🚫 Compra no ejecutada: {base} alcanzó el máximo de órdenes de hoy."
    return f"🚫 Compra no ejecutada: {reason}"
```

2. En el punto donde se construye la notificación "ORDER FAILED" por guardrail (busca en
   `signal_monitor.py` / el notificador de Telegram donde se envía el `reason_code` + `error`),
   usa `humanize_guardrail_reason(reason, symbol)` para el texto visible. Mantén el código crudo en
   un campo/línea secundaria (p.ej. "Detalle técnico: <reason>") para diagnóstico, o en logs.

**Restricciones**: solo texto de notificación. No cambies la lógica de los guardrails ni cuándo
bloquean. No toques el bucle de trading.

**Tests**: añade `backend/tests/test_guardrail_messages.py` cubriendo cada rama del mapeo
(one_active_trade_per_coin, max_open_trades, max_trade_usd, rsi, per_symbol_per_day, fallback).

**Entrega**: rama `fix/humanize-guardrail-telegram`, PR contra `main` con el link.
Bajo riesgo (solo presentación). Deploy con el flujo estándar.
