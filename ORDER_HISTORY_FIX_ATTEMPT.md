# Intento de Fix para `private/get-order-history` - 40101 Authentication Failure

## Problema
El endpoint `private/get-order-history` está devolviendo `40101 - Authentication failure` aunque:
- Las credenciales están correctas
- La IP está en la whitelist
- Otros endpoints funcionan (como `place_market_order`, `get_account_summary`)

## Cambio Realizado

### Orden de Parámetros en el JSON del Payload
Se modificó `sign_request()` en `crypto_com_trade.py` para asegurar que los parámetros en el JSON del payload estén ordenados alfabéticamente, igual que en el `string_to_sign`.

**Antes:**
```python
payload = {
    "id": request_id,
    "method": method,
    "api_key": self.api_key,
    "params": params,  # Podría tener parámetros en cualquier orden
    "nonce": nonce_ms
}
```

**Después:**
```python
# Asegurar que params esté ordenado alfabéticamente para coincidir con string_to_sign
if params:
    ordered_params = dict(sorted(params.items()))
else:
    ordered_params = {}

payload = {
    "id": request_id,
    "method": method,
    "api_key": self.api_key,
    "params": ordered_params,  # Parámetros ordenados alfabéticamente
    "nonce": nonce_ms
}
```

## Razón del Cambio
El `string_to_sign` ordena los parámetros alfabéticamente usando `_params_to_str()`, pero el JSON del payload podría tenerlos en otro orden. Algunos endpoints de Crypto.com pueden requerir que el orden en el JSON coincida exactamente con el orden en el `string_to_sign`.

## Próximos Pasos
1. Desplegar el cambio
2. Probar el endpoint `private/get-order-history`
3. Verificar los logs para confirmar si el problema se resolvió

## Nota
Si este cambio no resuelve el problema, podría ser:
- Un bug conocido de Crypto.com con este endpoint específico
- Permisos específicos requeridos para este endpoint
- Una diferencia en cómo Crypto.com valida la firma para este endpoint vs otros

