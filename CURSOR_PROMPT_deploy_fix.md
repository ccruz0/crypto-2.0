# Prompt para Cursor — quitar el endpoint trigger roto (fix de raíz) y desplegar

Copia todo lo de abajo en el agente de Cursor, en la raíz del repo `crypto-2.0`.
El patch está en la raíz del repo: `fix_trigger_orders_remove_legacy_endpoint.patch`.

---

Trabaja en `ccruz0/crypto-2.0`. Objetivo (aprobado por Carlos): eliminar de raíz el ruido
`ERR_INTERNAL` de trigger orders **dejando de llamar al endpoint legacy roto** y confiando en el
endpoint *advanced*, que ya cubre las trigger orders en cada ciclo.

**Causa raíz**
`private/get-trigger-orders` devuelve `ERR_INTERNAL` (50001) para esta cuenta en cada poll (auth OK).
En `fetch_unified_open_orders` se llamaba a ese endpoint y, al fallar, se marcaba
`trigger_orders_status=api_error` y se logueaba un WARNING cada 5-6s. Las trigger orders
(TAKE_PROFIT / STOP) ya llegan por `private/advanced/get-open-orders` y se clasifican con
`classify_advanced_open_order(is_trigger=True)`, poblando `all_raw_orders`. La reconciliación de
`exchange_sync` usa `all_raw_orders`, así que no depende de `trigger_raw`.

**Cambio 1 — código (aplicar el patch)**
```bash
git apply --check fix_trigger_orders_remove_legacy_endpoint.patch
git apply fix_trigger_orders_remove_legacy_endpoint.patch
```
Sustituye, en `backend/app/services/unified_open_orders_fetch.py`, todo el bloque `try/except` que
llamaba a `trade_client.get_trigger_orders(...)` por la inicialización de variables
(`trigger_raw=[]`, `trigger_status="ok"`, errores a `None`) más un comentario explicativo. Ya NO se
llama al endpoint legacy.

**Cambio 2 — actualizar el test existente**
En `backend/tests/test_crypto_com_advanced_open_orders.py`, reemplaza el test
`test_unified_fetch_trigger_50001_advanced_success_non_fatal` (que asumía el comportamiento viejo)
por este, que refleja el nuevo:

```python
def test_unified_fetch_skips_broken_legacy_trigger_endpoint_uses_advanced():
    from app.services.brokers.crypto_com_trade import CryptoComTradeClient

    real_client = CryptoComTradeClient.__new__(CryptoComTradeClient)
    mock_client = MagicMock()
    mock_client.get_open_orders.return_value = build_private_api_success([_legacy_sell_82k()])
    # Aunque el mock devolviera error, el endpoint legacy ya NO debe llamarse:
    mock_client.get_trigger_orders.return_value = build_private_api_error(
        sync_status="api_error", error_message="ERR_INTERNAL", error_code=50001,
    )
    mock_client.get_advanced_open_orders.return_value = build_private_api_success(
        [_advanced_margin_buy_59k(), _advanced_tp("tp-71000", "71000"), _advanced_tp("tp-78000", "78000")]
    )
    mock_client._map_incoming_order.side_effect = lambda raw, is_trigger=False: real_client._map_incoming_order(
        raw, is_trigger
    )

    result = fetch_unified_open_orders(mock_client)

    # El endpoint legacy roto no se llama
    mock_client.get_trigger_orders.assert_not_called()
    # Sin error de trigger; estado limpio
    assert result["sync_status"] == "ok"
    assert result["data_verified"] is True
    assert result["trigger_orders_status"] == "ok"
    assert result["trigger_orders_error"] is None
    assert result["trigger_orders_error_code"] is None
    # Las TP siguen presentes, vía advanced
    tp_orders = [o for o in result["orders"] if o.is_trigger]
    assert len(tp_orders) == 2
    assert {float(o.trigger_price) for o in tp_orders} == {71000.0, 78000.0}
```

**Cambio 3 — (opcional, follow-up secundario)**
`backend/app/api/routes_orders.py:~1173` también llama a `trade_client.get_trigger_orders()` (ruta
on-demand de limpieza de órdenes stale; hoy degrada sin romper). Para coherencia, cámbiala para NO
usar el endpoint legacy: usa `fetch_unified_open_orders(trade_client)` y construye el set de IDs
desde `fetch_result["all_raw_orders"]`. Márcalo como cambio separado si prefieres; NO es la fuente
del ruido de cada ciclo.

**Restricciones**
- Un objetivo. No toques el bucle de trading, ni umbrales de alertas de host, ni reabras PR #61.
- No cambies la clasificación de advanced ni la reconciliación de cancelaciones.

**Validación**
```bash
cd backend
pytest tests/test_crypto_com_advanced_open_orders.py tests/test_crypto_com_sync_status.py -q
pytest tests/test_exchange_sync_scheduling.py -q
```
Todos deben pasar (incluido el test renombrado).

**Entrega**
- Rama: `fix/remove-broken-legacy-trigger-endpoint` desde `origin/main`.
- Commit: `fix(orders): stop calling broken legacy get-trigger-orders; rely on advanced (ERR_INTERNAL/50001)`.
- Push + PR contra `main`. Pega el link.

**Deploy (tras merge)**
`scripts/deploy_production_via_ssm.sh` o `docs/DEPLOY_MAIN_TO_AWS_RUNBOOK.md`.

**Verificación post-deploy (read-only)**
```bash
curl -s https://dashboard.hilovivo.com/dashboard/open-orders-summary \
 | python3 -c 'import sys,json;d=json.load(sys.stdin);print("count",d["count"],"status",d["trigger_orders_status"],"err",d.get("trigger_orders_error"))'
```
Esperado: `status ok`, `err None`, `count 5` estable, y desaparecen los WARNING
`Trigger orders fetch failed` en los logs (ya no se llama al endpoint).
