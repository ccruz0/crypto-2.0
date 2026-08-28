# Criterio de salida de la sombra (PASO B1 → B2)

Fecha: 2026-08-20 · Estado: **abierto** — primera agregación 28-ago-2026 (NO-GO, ver registro).

Sin un criterio escrito antes de empezar, una fase de sombra acaba de una de
dos maneras: eterna, o cortada por impaciencia. Esto lo fija por adelantado.

## Qué mide la sombra

`position_count_shadow.record_shadow_count` emite una línea por cada llamada al
contador viejo, con claves fijas para poder agregarla con `grep` y `awk`:

```
[POSITION_COUNT_SHADOW] symbol=ALGO base=ALGO legacy=0 shadow=2 diverge=1 \
  long_qty=238.00000000 short_qty=0.00000000 wallet=71.11492880 wallet_ok=1 \
  aligned=1 lots_pre=3 ms=45.2 warning=-
```

No decide nada. `legacy` es lo que el guard usó; `shadow` es lo que el contador
por lots habría dicho.

## Condiciones para pasar a B2

Las cuatro, a la vez.

### 1. Cobertura: la sombra ha visto el sistema moverse

- **≥ 72 h** de sombra continua en producción.
- **≥ 10 entradas** y **≥ 10 cierres** reales observados en la ventana.

El tiempo por sí solo no vale: un contador que solo ha visto estado estático no
ha demostrado que cuente transiciones. Lo que rompe la contabilidad son las
aperturas y los cierres, no el reposo.

Las entradas y cierres se cuentan desde `exchange_orders`, no desde el log de
la sombra, para no medir con la misma regla que se está validando.

### 2. Divergencias: todas explicadas, ninguna pendiente

Cero divergencias `legacy != shadow` **sin causa escrita**. No cero
divergencias: se espera que diverjan —ese es el motivo del arreglo—. Lo que no
se acepta es una divergencia que nadie sepa explicar.

Cada patrón distinto de divergencia se anota en este fichero con: símbolo,
`legacy`, `shadow`, y cuál de los dos tiene razón contra el wallet.

Una divergencia donde **el viejo acierta y el nuevo falla** es bloqueante y
para B2 hasta corregirla.

### 3. La tabla libros-vs-wallet cuadra

Para las 19 monedas con `trade_enabled`, `shadow.long_qty - shadow.short_qty`
debe coincidir con el wallet real del símbolo, con dos tolerancias:

- **Polvo:** desviación por debajo del mínimo negociable del par, o de 1 USD al
  precio actual, lo que sea mayor.
- **Causa escrita:** cualquier desviación mayor necesita una línea en este
  fichero diciendo por qué. Sin línea, no se pasa a B2.

Referencia de partida (20-ago, contador **viejo**, para comparar después):

```
símbolo   libros_n   libros_qty        wallet_real       guard_count
AAVE          3       0.31000000       -0.01232705            0
ALGO          2     238.00000000       71.11492880            0
DOGE          1     133.00000000    -4125.23792652            0
ETH           2       0.01060000       -0.00002514            1
resto         0       0.00000000        (varios)               0
```

El objetivo de B2 es que la columna del contador nuevo cuadre con
`wallet_real`, no con `libros_qty`.

### 4. Coste: medido, no supuesto

- **p95 de `ms` por símbolo < 250 ms**, y
- **p99 < 1000 ms**.

Por encima de eso, B2 entra con caché por ciclo y el criterio se re-mide. Por
debajo, la caché se descarta como complejidad innecesaria. La decisión se toma
con el histograma, no con la intuición.

`ms` incluye el `rebuild_open_lots` completo y, cuando toca refresco, la lectura
de wallet. La lectura está cacheada con TTL
(`POSITION_COUNT_SHADOW_WALLET_TTL`, 60 s por defecto), así que el p95 refleja
el caso normal y el p99 el de refresco.

## Cómo se comprueba

```bash
# divergencias y acuerdo, por símbolo
docker logs backend-aws-1 --since 72h 2>&1 \
  | grep POSITION_COUNT_SHADOW \
  | awk '{for(i=1;i<=NF;i++){split($i,a,"=");k[a[1]]=a[2]}
          print k["symbol"], k["legacy"], k["shadow"], k["diverge"]}' \
  | sort | uniq -c | sort -rn

# histograma de coste
docker logs backend-aws-1 --since 72h 2>&1 \
  | grep -o 'ms=[0-9.]*' | cut -d= -f2 | sort -n \
  | awk '{v[NR]=$1} END {print "n="NR, "p50="v[int(NR*0.5)], "p95="v[int(NR*0.95)], "p99="v[int(NR*0.99)]}'

# fallos de la sombra (no pueden pasar desapercibidos)
docker logs backend-aws-1 --since 72h 2>&1 | grep -c "shadow=ERROR"
```

`shadow=ERROR` con cuenta > 0 es bloqueante: una sombra que muere en silencio
se lee como "sin divergencias".

## Lo que NO forma parte del criterio

- **`maxOpenOrdersTotal` se queda en 7.** Decisión de Carlos (20-ago): si al
  conmutar bloquea con 8 posiciones reales, eso es el límite funcionando. La
  sombra lo enseñará antes de que ocurra, así que no será una sorpresa. Se
  revisa con un día de datos verdaderos, en su propio cambio, **no** en el PR
  que estrena el contador.
- **Migración de libros históricos.** Fuera de B1 y de B2. `rebuild_open_lots`
  reinterpreta las filas existentes, no las reescribe.

## Semántica de wallet: qué aplica en cada fase

| | B1 (sombra) | B2 (decide) |
|---|---|---|
| Wallet no responde | se registra `wallet_ok=0`, **nunca bloquea** | **bloquea entradas + alerta Telegram** |
| Órdenes protectoras | no aplica, no decide | **exentas del guard**, siempre |

El fail-closed de B2 no puede alcanzar a las patas SL/TP: un fallo del exchange
no puede dejar una posición viva sin proteger. Y un fail-closed silencioso sería
una parada inexplicada, así que bloquear implica avisar. Condiciones 2(a) y 2(b)
de Carlos, 20-ago.

## Registro de divergencias

Primera agregación: **28-ago-2026, ventana 00:37–01:45 UTC** (~10.400 muestras).
La ventana es de ~1h y no de 72h por el bloqueo operativo nº1 de abajo.

| fecha | símbolo | legacy | shadow | quién acierta vs wallet | causa |
|---|---|---|---|---|---|
| 28-ago | AAVE | 0 | 1 | **shadow** — wallet −0.02980318 = short_qty exacto a 8 decimales | legacy clavado en 0: sustraendo doblado por gemelas + poblaciones asimétricas (defectos 1-3 de #523) |
| 28-ago | DOT | 0 | 1 | **shadow** — wallet −1.84335603 exacto | ídem |
| 28-ago | ALGO | 0 | 1 | **shadow** — wallet +0.47371971 (long) exacto | ídem |
| 28-ago | ATOM | 0 | 1 | **shadow** — wallet +0.00505000 exacto | ídem; long residual cercano a polvo |
| 28-ago | SUI | 0 | 1 | **shadow** — wallet −0.30335976 exacto | ídem; corto de ~$0,23: revisar si cae bajo tolerancia de polvo |
| 28-ago | ETH | 1 | 1 | acuerdo (short residual de polvo) | — |
| 28-ago | DOGE | 0 | 0 | acuerdo; wallet −12.85 DOGE (~$1) en el borde de la tolerancia | warning=ghost_long_vs_short; vigilar |
| 28-ago | **APT** | 0 | 3 | **NINGUNO cuadra**: wallet dice corto 173.48953042, libros dicen 208.29 — hueco de 34.8 APT ≈ $20 | **BLOQUEANTE (criterio 3)**: legacy=0 es claramente falso (hay cortos reales), pero la cantidad de la sombra tampoco casa. warning=lots_exceed_wallet con aligned=1: la alineación a wallet no está recortando los cortos como recorta los largos. Causa raíz pendiente |
| 28-ago | BONK/SOL/HBAR/AKT | 0 | 1 | pendiente de muestra cruda | mismo patrón aparente que AAVE/DOT; sin línea capturada con wallet en esta agregación |

### Medición de coste (criterio 4) — 28-ago

```
n=10425  p50=68.0ms  p95=308.2ms  p99=681.8ms
shadow=ERROR: 0    wallet_ok=0: 0
```

**p95 = 308 ms > 250 ms → el criterio 4 FALLA.** Según lo ya escrito arriba:
B2 entra con caché por ciclo y el criterio se re-mide. No es opinión nueva,
es la regla que este documento fijó el 20-ago aplicada al histograma real.

### Bloqueos operativos detectados al agregar (28-ago)

1. **La evidencia se evapora.** La rotación de logs del contenedor retiene
   ~1h (16 ficheros json.log) y cada deploy recrea el contenedor. El criterio
   de "72h de sombra continua" es inverificable con `docker logs`: la sombra
   corre desde el 20-ago pero su evidencia no sobrevive. Hace falta persistir
   la agregación (una línea diaria en un fichero del host o una tabla) antes
   de poder declarar cumplido el criterio 1.
2. **Actividad insuficiente.** Con el sizing manual reducido, las últimas 72h
   tienen ~5 entradas y ~7 cierres reales en `exchange_orders` — por debajo
   del mínimo de 10/10 del criterio 1. No es un defecto: es que el sistema
   está operando poco. El criterio se cumplirá con calendario, no con código.

### Estado B1→B2 a 28-ago-2026: **NO-GO**, con camino claro

- Criterio 1 (cobertura): **no cumplido** (evidencia no retenida + actividad < 10/10).
- Criterio 2 (divergencias explicadas): **parcial** — el patrón dominante
  (legacy=0 / shadow=N con wallet dando la razón a la sombra a 8 decimales)
  queda explicado arriba; **APT queda abierto y es bloqueante**.
- Criterio 3 (libros vs wallet): **falla en APT** (hueco $20 > tolerancia).
- Criterio 4 (coste): **falla** (p95 308 > 250) → B2 llevará caché por ciclo.

Lo que la agregación sí deja demostrado con datos vivos: el contador legacy
reporta 0 posiciones abiertas en ≥9 símbolos mientras el wallet muestra
cortos y largos reales — `maxOpenOrdersPerCoin` y `maxOpenOrdersTotal` no
están limitando nada, hoy. La urgencia de B2 sube; el atajo de saltarse los
criterios, no.
