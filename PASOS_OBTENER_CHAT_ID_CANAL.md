# Pasos para Obtener el Chat ID del Canal "Hilovivo-alerts"

## ⚠️ Lo que acabas de hacer
Reenviaste un mensaje **tuyo** a @userinfobot, por eso te mostró tu información personal:
- ID: 839853931 (tu usuario)
- First: CARLOS

## ✅ Lo que necesitas hacer

### Paso 1: Ve al canal "Hilovivo-alerts"
1. Abre Telegram
2. Busca el canal "Hilovivo-alerts" (no tu chat personal)
3. Ábrelo

### Paso 2: Reenvía un mensaje DEL CANAL
1. En el canal "Hilovivo-alerts", busca cualquier mensaje que esté **en el canal**
2. Mantén presionado ese mensaje (o haz clic derecho)
3. Selecciona "Reenviar" o "Forward"
4. Selecciona `@userinfobot` como destinatario
5. Envía el mensaje

### Paso 3: El bot te mostrará información del CANAL
El bot debería responder con algo como:
```
Chat ID: -1001234567890  ← Este es el que necesitas (número NEGATIVO)
Title: Hilovivo-alerts
Type: channel
```

## 🔍 Cómo saber si es correcto

- ✅ **Correcto**: El Chat ID será un número **NEGATIVO** (ejemplo: `-1001234567890`)
- ✅ **Correcto**: El título será "Hilovivo-alerts" o similar
- ❌ **Incorrecto**: Si el ID es `839853931` (positivo) = es tu usuario, no el canal
- ❌ **Incorrecto**: Si el First Name es "CARLOS" = es tu usuario, no el canal

## 📝 Alternativa: Si no hay mensajes en el canal

Si el canal está vacío o no puedes reenviar mensajes:

1. **Envía un mensaje en el canal** (cualquier texto)
2. Luego reenvía ese mensaje a @userinfobot
3. O usa el Método 2 (API de Telegram) que está en la guía

## 🎯 Una vez que tengas el Chat ID negativo

Actualiza `.env.aws` con ese número negativo y reinicia el backend.


