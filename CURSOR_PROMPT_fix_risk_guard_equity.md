# Prompt Cursor — fix risk guard equity=0 (desbloquea órdenes reales) — aprobado por Carlos

⚠️ Este fix quita el último bloqueo para que las órdenes reales se ejecuten. Con el guardrail en 3
posiciones, $10/trade y solo DOT/ETH activos, el riesgo está acotado. Ten el kill switch a mano.
Patch en la raíz del repo: `fix_risk_guard_equity.patch`.

---

Trabaja en `ccruz0/crypto-2.0`. Objetivo (aprobado por Carlos): arreglar el risk guard que bloquea
TODA orden real con "Account equity must be positive to trade".

**Causa raíz (confirmada en runtime):**
En `crypto_com_trade.py`, el bloque del risk guard (en `place_market_order` ~3778 y `place_limit_order`
~4351) obtiene el equity así:
```python
summary = self.get_account_summary()
account_equity = float(summary.get("margin_equity") or summary.get("account_equity") or summary.get("equity") or 0)
```
Pero `get_account_summary()` devuelve un dict de posiciones (`accounts`/`position_balances`), **sin**
esas claves → todas devuelven None → `account_equity = 0` → `risk_guard.check_trade_allowed` bloquea
con "Account equity must be positive". Esto bloqueaba todas las órdenes reales (estaba enmascarado
mientras el bot iba en dry-run; al arreglar el live gate, salió).

Verificado en producción: `trade_client.get_equity_from_user_balance()` devuelve
`equity=37493.68, exposure=21822.65, daily_loss=0.0` (positivo y correcto). Esa es la función a usar.

**Cambio (aplicar el patch):**
```bash
git apply --check fix_risk_guard_equity.patch && git apply fix_risk_guard_equity.patch
```
Sustituye en los DOS sitios el bloque `summary = self.get_account_summary(); account_equity = ...;
total_margin_exposure = ...; daily_loss_pct = ...` por:
```python
account_equity, total_margin_exposure, daily_loss_pct = self.get_equity_from_user_balance()
```
`get_equity_from_user_balance()` ya existe (línea ~1477), lee los totales reales de `private/user-balance`
y lanza ValueError si equity ≤ 0 (el try/except externo lo convierte en bloqueo fail-safe, correcto).

**Test:** añade `backend/tests/test_risk_guard_equity_source.py` que parchee
`CryptoComTradeClient.get_equity_from_user_balance` para devolver `(37000.0, 21000.0, 0.0)` y verifique
que el camino del risk guard recibe `account_equity=37000` (no 0) y NO bloquea por "equity must be
positive". Añade un caso donde la función lanza ValueError → el guard bloquea (fail-safe). Usa el patrón
de mock de los tests existentes de crypto_com_trade.

**Restricciones:** no cambies la lógica de `risk_guard.check_trade_allowed` ni los umbrales; solo la
FUENTE del equity. No toques el live gate ni el bucle de trading.

**Entrega:** rama `fix/risk-guard-equity-source`, PR contra `main`. NO auto-merge. Pega el link.

**Validación post-deploy (con kill switch a mano):**
1. Deploy + health 200.
2. Espera una señal de DOT/ETH que dispare orden. Ya NO debe salir "Account equity must be positive".
3. Confirma en Crypto.com una orden real ~$10 (ID numérico). Si va a MARGIN y el exchange la rechaza por
   apalancamiento, considera poner esas monedas en SPOT (Margin=NO) — pero eso es decisión aparte.
4. Vigila: ≤3 posiciones, sin duplicados.

**Rollback:** revert del commit → vuelve a bloquear por equity (estado actual, seguro).
