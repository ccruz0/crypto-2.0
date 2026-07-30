# 🔴 Prompt Cursor — fix live gate (DINERO REAL) — aprobado por Carlos

⚠️ **Este cambio hace que el bot ejecute órdenes REALES con dinero.** Sigue el checklist y la
validación por fases al pie de la letra. Patch en la raíz del repo: `fix_live_gate_aws.patch`.

---

Trabaja en `ccruz0/crypto-2.0`. Objetivo (aprobado por Carlos): que el bucle automático ejecute
órdenes reales en AWS, en vez de simularlas.

**Causa raíz (confirmada):** en AWS `self.live_trading` está pinneado a False; las 5 funciones de
orden hacían `actual_dry_run = dry_run or not self.live_trading` → siempre dry, aunque el caller pase
`dry_run=False` desde la BD (LIVE). El bot simulaba todo.

## PRE-DEPLOY — checklist obligatorio (NO desplegar sin esto)
1. `maxOpenOrdersTotal = 3` y `maxOpenOrdersPerCoin = 1` en la config (dashboard → "Límites de órdenes abiertas"). Verifica `get_trading_limits()` los devuelve.
2. `amount_usd = 10` en TODAS las monedas con `trade_enabled=true` (DOT, ETH, BTC, DGB, ALGO). Verifica en config/DB.
3. `SYSTEM_CORE_GUARDS_ENABLED=true` y kill switch probado.
4. Confirma que no hay más monedas con Trade=YES de las esperadas.

## Cambio de código
```bash
git apply --check fix_live_gate_aws.patch && git apply fix_live_gate_aws.patch
```
Añade `_resolve_actual_dry_run(self, dry_run)` en `crypto_com_trade.py`: en AWS devuelve el `dry_run`
del caller (autoritativo); fuera de AWS mantiene `dry_run or not self.live_trading`. Y sustituye las 5
asignaciones por `actual_dry_run = self._resolve_actual_dry_run(dry_run)`. El gate de mutación
(`require_mutation_allowed_for_broker` / `assert_exchange_mutation_allowed`) sigue como segunda barrera.

## Test
Crea `backend/tests/test_resolve_actual_dry_run.py`:
```python
from unittest.mock import patch
from app.services.brokers.crypto_com_trade import CryptoComTradeClient

def _client(live):
    c = CryptoComTradeClient.__new__(CryptoComTradeClient)
    c.live_trading = live
    return c

def test_aws_uses_caller_dry_run():
    c = _client(False)  # AWS pinnea live_trading=False
    with patch("app.core.runtime.is_aws_runtime", return_value=True):
        assert c._resolve_actual_dry_run(False) is False  # LIVE -> orden real
        assert c._resolve_actual_dry_run(True) is True     # caller dry -> dry

def test_local_honors_live_trading():
    with patch("app.core.runtime.is_aws_runtime", return_value=False):
        assert _client(True)._resolve_actual_dry_run(False) is False
        assert _client(False)._resolve_actual_dry_run(False) is True
```
Corre: `cd backend && pytest tests/test_resolve_actual_dry_run.py -q`

## Entrega
Rama `fix/live-gate-aws-real-execution`, PR contra `main`. NO auto-merge. Pega el link.

## VALIDACIÓN POR FASES (tras merge + deploy) — con el kill switch a mano
1. Deploy. Confirma health 200.
2. En logs backend-aws: en el próximo intento de orden, ya NO debe aparecer `DRY_RUN: place_market_order`
   para símbolos LIVE; debe verse la llamada real al exchange.
3. Espera/fuerza **UNA** señal en una moneda a $10 y confirma en Crypto.com que aparece una orden
   **real** (ID numérico, no `dry_`), importe ~$10.
4. Vigila 15-30 min: nº de posiciones abiertas ≤ 3, sin duplicados, SL/TP creándose.
5. Si algo raro → **kill switch** + revertir el commit (vuelve a dry). Rollback sin dependencias nuevas.

## Rollback
Revertir el commit → `actual_dry_run` vuelve a forzar dry en AWS.
