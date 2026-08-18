# Estado a 18-ago-2026, fin de sesion

## Lo primero

**Todo desplegado y verificado. `main` y produccion alineados en `02ed3556`.**
No queda ningun merge sin desplegar, que es justo lo que fallo anoche con #497.

```
x-atp-backend-commit: 02ed3556
System Health: PASS (market_data, market_updater, signal_monitor, telegram)
Expected TP summary: 25 simbolos
```

## Mergeado y desplegado hoy (9 PRs)

| PR | Que arregla |
|---|---|
| #499 | Guarda: no crear proteccion de cierre de corto si el wallet no es negativo |
| #500 | El auto-merge espera los checks del commit actual, no solo path-guard |
| #502 | La guarda de cortos mira **todas** las cuentas, no la primera |
| #503 | El wipe de fantasmas no oculta el simbolo ni su saldo |
| #504 | Una fila por moneda en `portfolio_loans`, no una por refresco |
| #505 | `ghost_mixed_trimmed` llega de verdad al frontend |
| #506 | Desarmar el auto-merge cuando llega un commit con checks en vuelo |
| #507 | El residuo de un corto sin lots no desaparece del summary |
| #508 | El residuo de un activo nunca operado tampoco |

### Resultados medidos en produccion

- **#496 punto 1 cerrado.** Ninguna compra de cobertura fantasma desde el 15-ago.
  Las 22 protecciones BUY vivas cubren cortos reales (todas con balance
  negativo). AAVE se protegio 6h despues del deploy, o sea que la guarda no
  estrangula lo legitimo.
- **`portfolio_loans`: sangria cortada.** Iba a ~7,3 filas/minuto (id 525.180);
  tras el deploy, **delta = 0 en 4,5 minutos**. Filas activas 17 -> 14 (retiradas
  ALGO, DOGE y USD, obsoletas desde miles de ciclos). Suman 22.701,80 USD contra
  los 22.700,85 del dashboard: cuadran, la diferencia es deriva de precio.
- **Expected TP: 19 -> 25 simbolos.** Ya no se cae ningun simbolo con saldo real.
  ALGO, CRO, AKT y BCH volvieron con #503; XRP, BONK, XLM con #507; ADA, AVAX y
  STRK con #508. Todos con `cost_basis_unknown` y direccion correcta.

## Lo que sigue abierto

1. **#498 punto 3 — `AUTO_MERGE_TOKEN` no existe.** Ningun merge del bot dispara
   deploy. Los 5 deploys de hoy fueron a mano con
   `gh workflow run deploy-backend.yml --ref main`. Es lo que hay que arreglar
   para no repetir lo de #497.
2. **CI ejecuta 16 de 341 ficheros de test.** Cuantificado en un comentario a
   #498. Hay 21 tests rojos en `main` que llevan semanas invisibles. Decision de
   Carlos: ampliar en `continue-on-error` primero y hacerlo bloqueante al llegar
   a cero — arreglar 21 antes de tener visibilidad es esfuerzo sin recompensa
   intermedia, y una suite que deja todo en rojo acaba desactivada.
3. **Limpieza de las ~525.000 filas historicas de `portfolio_loans`.** #504 corto
   el crecimiento pero no limpia lo escrito. Es migracion de datos en produccion
   y va aparte. Conviene decidir a la vez si se quiere un indice unico sobre
   `currency`, que lo impediria estructuralmente pero exige deduplicar antes.
4. **Ventana estrecha del auto-merge.** Entre que una PR se abre y el workflow
   arranca, un armado previo podria disparar. Cerrarla exige no armar nunca el
   auto-merge nativo y depender solo del squash directo mas los re-disparos por
   `check_run`.
5. **Sin traza de cambios en watchlist.** `WatchlistItem` no tiene columna
   `updated_at` ni hay tabla de auditoria. Cambiar un flag que decide si el bot
   opera una moneda no deja ningun rastro. Salio al investigar BTC.

## BTC: investigado y cerrado, no era un bug

BTC_USD lleva mas de una semana sin alertar. **Es configuracion, no fallo.**

```
BTC_USD   rsi=47,48   precio +1,11% sobre MA200   alert/buy_alert/trade = True
ATOM_USD  rsi=36,25   precio -3,59% sobre MA200   -> 33 senales
```

`strategy_rules.auto` exige `rsi.buyBelow: 30`. BTC lleva la semana plano —
precio, MA50, MA200 y EMA10 dentro de un 1,1%, ATR 0,31% por vela — y eso fija
el RSI cerca de 50 por construccion. Las monedas que alertan estan en caida.

- **No es el cooldown.** `signal_side=NONE` y `alert_block_reason=None`. Si
  `minPriceChangePct=4` o `alertCooldownMinutes=15` fueran el freno, saldria
  `signal_side=BUY` con `alert_status=BLOCKED`.
- **Los filtros de tendencia pasan** (+1,11% sobre MA200, EMA10 +0,85% sobre
  MA50).
- **BTC entra en el ciclo**: `evaluated_at_utc` se actualiza cada vuelta.
- **BTC_USDT tiene las alertas apagadas** (`alert_enabled=False`), y coincide
  exactamente con los defaults del modelo, asi que probablemente nunca se
  activo desde su creacion el 23-mar. **Sin activar por decision de Carlos.**
  Encenderlo duplicaria alertas del mismo activo: BTC_USD ya esta activo con el
  mismo RSI.

### Bug descartado en `trading_signals.py:269-300`

La sospecha era que `require_ema10_above_ma50` pisaba el `trend_filters_ok` de
`require_price_above_ma200` en vez de hacer AND. **No ocurre**: las cuatro
asignaciones de `False` van seguidas de un `return` inmediato (lineas 272/273,
278/279, 286/287, 296/297), asi que ningun `False` sobrevive. Es un AND por
salida temprana: menos legible, equivalente.

## Lo que encontro Bugbot (4 de 4 reales)

Merece anotarse porque cambia como conviene trabajar aqui:

1. **#504** — la retirada de prestamos vivia dentro de `if loans_found:`, asi que
   con todo repagado no se desactivaba nada. Y es el caso que mas importa:
   `portfolio_snapshot` solo cae a esa tabla cuando no hay balances negativos.
2. **#505** — el detalle pisaba `ghost_mixed_trimmed`. Yo lo habia descartado
   razonando que `resolve_position_side` devuelve MIXED; no habia visto que
   `open_lots` se reasigna a los lots post-alineamiento antes de esa llamada.
3. **#506** — un desarme fallido seguia resolviendo hilos igual, desbloqueando el
   ruleset con el armado viejo vivo. El mismo fallo que la PR venia a cerrar.
4. **#507** — el residuo de un corto salia etiquetado LONG: el lot sintetico no
   tiene `buy_order_id` y la resolucion de lado cae por defecto a BUY.

Dos de los cuatro estaban en codigo que yo habia declarado verificado. La
barrera automatica acerto donde el criterio fallo.

## Notas de entorno

- Los tests NO corren con el Python del sistema (3.14 de Homebrew, sin
  sqlalchemy). Hace falta un venv: `backend/.venv_test/bin/python`.
- `zsh` no hace word-splitting de `$VAR` sin comillas: `pytest $SUITE` no
  expande. Pasar los ficheros literales o usar `${=VAR}`.
- Ojo con `git stash push ... ; git stash pop`: con `;` en vez de `&&`, si el
  push no tiene nada que guardar el pop saca un stash ajeno. Contamino una
  medicion hoy.
- `/api/ohlcv` y `/api/ticker` exigen API key; no sirven para diagnostico
  externo. `/api/watchlist/state` y `/api/market/top-coins-data` si, y traen
  rsi/ma200/ma50/ema10 por simbolo.
