# Criterio de salida de la sombra (PASO B1 → B2)

Fecha: 2026-08-20 · Estado: **abierto**, la sombra empieza al desplegar B1.

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

_(se rellena durante la sombra)_

| fecha | símbolo | legacy | shadow | quién acierta vs wallet | causa |
|---|---|---|---|---|---|
| | | | | | |
