# Prompt para Cursor — máx. órdenes abiertas configurable + label + persistencia (#4/#5/#6)

Copia en el agente de Cursor, raíz del repo `crypto-2.0`.

---

Trabaja en `ccruz0/crypto-2.0`. Tres objetivos relacionados con la configuración de estrategia.

## A) Exponer el máximo de ÓRDENES ABIERTAS en la config (hoy es env, no UI)
Hoy el tope real de órdenes abiertas está hardcodeado por entorno en
`backend/app/services/system_core_trade_guards.py`:
```python
_MAX_OPEN_TRADES = int(os.getenv("SYSTEM_CORE_MAX_OPEN_TRADES", "5"))
# + regla one_active_trade_per_coin (efectivamente 1 posición por moneda)
```
No se puede cambiar desde el dashboard.

Cambios:
1. Añade a la config de trading (global, no por-preset — el guardrail es global) dos campos:
   - `maxOpenOrdersTotal` (int, default 5) → máximo de posiciones/símbolos abiertos a la vez.
   - `maxOpenOrdersPerCoin` (int, default 1) → cuántas posiciones por moneda (1 = regla actual).
   Persístelos en el mismo store que `getTradingConfig`/`saveTradingConfig` (`/config`).
2. Cablea `system_core_trade_guards.py` para leer de la config (vía `config_loader`) con **fallback**
   a las env vars actuales si la config no trae el valor (no cambies el comportamiento por defecto):
   - `one_active_trade_per_coin` → usa `maxOpenOrdersPerCoin` en vez de la constante 1.
   - `_MAX_OPEN_TRADES` → usa `maxOpenOrdersTotal` si está en config.
3. Frontend: añade estos dos campos en el modal de configuración
   (`frontend/src/app/components/StrategyConfigModal.tsx`) en una sección nueva "Límites de órdenes
   abiertas", con su tipo en `frontend/src/types/dashboard.ts`. Deben guardarse y recargarse.

## B) Corregir el label engañoso (#5)
El campo actual `maxOrdersPerSymbolPerDay` ("Max Orders Per Symbol / Day") es un throttle
**por símbolo y por día** (se aplica en `backend/app/utils/trading_guardrails.py` contando
`orders_today`). NO lo renombres a "general" — su semántica es correcta. Solo aclara el label a algo
como **"Máx. órdenes por moneda al día (throttle)"** con su help text, para que no se confunda con el
tope de órdenes abiertas del punto A.

## C) Verificar/arreglar persistencia por preset (#6)
`handleSaveStrategyConfig` (en `frontend/src/app/page.tsx`) mergea en
`strategy_rules[preset][riskMode]` y preserva el resto, así que en teoría persiste por preset. Verifica
end-to-end: cambia el selector de preset a uno != Swing/Conservative, edita un valor, guarda, recarga
la página y confirma que persiste. Si NO persiste, arréglalo (probable causa: el modal abre siempre en
Swing/Conservative o el reload no relee `strategy_rules[preset]`). Añade un test si tocas lógica.

**Restricciones**: los defaults NO deben cambiar el comportamiento actual (5 total, 1 por moneda).
No toques el bucle de trading ni el gate live (eso es otro fix aparte). Cambios auditables.

**Tests**: unitarios del guardrail leyendo de config con fallback a env; y del frontend si cambias
lógica de guardado.

**Entrega**: rama `feat/config-max-open-orders`, PR contra `main` con el link y nota de qué defaults
se mantienen. Deploy con el flujo estándar.
