# Solución de Caché del Navegador

**Fecha:** 2025-12-01  
**Problema:** El navegador está mostrando JavaScript antiguo después de actualizaciones del frontend

## Solución Implementada

### 1. Headers de Cache-Control Mejorados

Se actualizó `frontend/next.config.ts` para forzar que el navegador no cachee archivos JavaScript y CSS:

```typescript
async headers() {
  return [
    {
      source: '/:path*',
      headers: [
        {
          key: 'Cache-Control',
          value: 'no-cache, no-store, must-revalidate, max-age=0',
        },
        {
          key: 'Pragma',
          value: 'no-cache',
        },
        {
          key: 'Expires',
          value: '0',
        },
      ],
    },
    {
      // Específico para archivos estáticos de Next.js
      source: '/_next/static/:path*',
      headers: [
        {
          key: 'Cache-Control',
          value: 'no-cache, no-store, must-revalidate, max-age=0',
        },
      ],
    },
    {
      // Específico para chunks de JavaScript
      source: '/_next/static/chunks/:path*',
      headers: [
        {
          key: 'Cache-Control',
          value: 'no-cache, no-store, must-revalidate, max-age=0',
        },
      ],
    },
  ];
}
```

### 2. Solución Inmediata para el Usuario

Si el navegador todavía muestra JavaScript antiguo:

#### Opción 1: Hard Refresh (Recomendado)
- **Mac**: `Cmd + Shift + R`
- **Windows/Linux**: `Ctrl + Shift + R`
- **Safari**: `Cmd + Option + R`

#### Opción 2: Limpiar Caché del Navegador
1. Abre DevTools (F12 o Cmd+Option+I)
2. Clic derecho en el botón de recargar
3. Selecciona "Empty Cache and Hard Reload"

#### Opción 3: Modo Incógnito
- Abre una ventana de incógnito/privada
- Navega a `https://dashboard.hilovivo.com`
- Esto evita completamente el caché

#### Opción 4: Limpiar Caché Manualmente
**Chrome/Edge:**
1. `Cmd/Ctrl + Shift + Delete`
2. Selecciona "Cached images and files"
3. Rango de tiempo: "All time"
4. Click "Clear data"

**Safari:**
1. Safari → Preferences → Advanced
2. Activa "Show Develop menu"
3. Develop → Empty Caches
4. `Cmd + Option + R` para hard refresh

**Firefox:**
1. `Cmd/Ctrl + Shift + Delete`
2. Selecciona "Cache"
3. Rango: "Everything"
4. Click "Clear Now"

### 3. Verificación

Después de hacer hard refresh, verifica que el JavaScript esté actualizado:

1. Abre DevTools (F12)
2. Ve a la pestaña "Network"
3. Recarga la página
4. Busca archivos `.js` o `.js.map`
5. Verifica que el tamaño y timestamp sean recientes

O verifica en la consola:
```javascript
// Debería mostrar la versión actual
console.log('Frontend version:', '0.40.0');
```

### 4. Prevención Futura

Con los headers actualizados, el navegador debería:
- No cachear archivos JavaScript y CSS
- Siempre solicitar la versión más reciente del servidor
- Actualizar automáticamente después de cada deploy

## Notas Técnicas

- Los headers `Cache-Control: no-cache` permiten al navegador verificar con el servidor si hay una versión nueva
- `no-store` previene que el navegador guarde el archivo en caché
- `must-revalidate` fuerza la validación con el servidor
- `max-age=0` establece que el caché expira inmediatamente

## Troubleshooting

Si después de todo esto todavía ves JavaScript antiguo:

1. **Verifica que el frontend se reconstruyó correctamente:**
   ```bash
   ssh hilovivo-aws
   cd /home/ubuntu/automated-trading-platform
   docker logs automated-trading-platform-frontend-aws-1 --tail 20
   ```

2. **Verifica que los headers se están enviando:**
   ```bash
   curl -I https://dashboard.hilovivo.com/_next/static/chunks/main.js
   # Debería mostrar: Cache-Control: no-cache, no-store, must-revalidate, max-age=0
   ```

3. **Fuerza un rebuild completo:**
   ```bash
   docker compose down frontend-aws
   docker compose build --no-cache frontend-aws
   docker compose up -d frontend-aws
   ```

## Referencias

- [Next.js Headers Documentation](https://nextjs.org/docs/app/api-reference/next-config-js/headers)
- [MDN Cache-Control](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Cache-Control)

