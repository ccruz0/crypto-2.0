## Que hace

Filtro de regimen para cortos, decision de Carlos (22-ago): un corto solo se abre si price < MA200 — espejo del gate de compra, que bloquea BUY con price <= ma200. Implementado en check_system_core_short_entry_allowed (system_core_trade_guards.py), cuyo docstring admitia que los gates RSI/MA200 eran solo de BUY.

## Motivo medido (rev-20260822-cortos-en-alcista)

- 37 de 38 entradas del 19-21 ago fueron cortos con price>ma200 en pleno rally.
- El mercado barrio el libro: 11 stops en 24h, -177,84 USD.
- La senal SELL nacio como salida de swing largo; el PR #479 la convirtio en apertura de cortos sin filtro de regimen.

## Semantica

- FAIL-CLOSED: sin MA200 valida (o precio invalido) el corto NO se abre. Un filtro de regimen fail-open no filtra nada, como demostro el contador de posiciones (#523).
- Kill-switch sin tocar codigo: SHORT_REQUIRE_PRICE_BELOW_MA200=false (requiere reinicio del contenedor para tomar la var).
- Fallback de simbolo: exacto → BASE_USD → BASE_USDT en market_data.

## Verificacion previa (protocolo multiangulo, rev-20260822-filtro-regimen)

- Un unico llamador del gate en el repo (signal_monitor.py:9410) y respeta el bloqueo; el precio no llega 0/None por ese camino (guardia en :2690).
- SQL probada contra la BD real: BONK y BTC bloqueados; GRAM tambien (su ma200 existe).
- Efecto inmediato: bloquea 45-46 de 47 cortos posibles hoy. El unico shorteable seria MATIC_USDT, con datos sospechosos (posible artefacto post-migracion) — vigilar.
- Tests: 9 passed contra la imagen de produccion (6 nuevos + los 3 de test_signal_monitor_short_entry_cap, sin regresion). El test nuevo se anade a backend-ci.
- Env en produccion: los flags caen a true por defecto; el filtro queda vivo al desplegar.

## Riesgo conocido, pre-existente

El bloque llamador esta en un try/except que ante una excepcion procede sin guards. Este PR no lo agranda: el helper captura sus propios errores y bloquea. Queda documentado para arreglo aparte.
