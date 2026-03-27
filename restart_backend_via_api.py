#!/usr/bin/env python3
"""
Reiniciar backend usando el endpoint de API
"""

import requests
import time

AWS_BACKEND_URL = "https://dashboard.hilovivo.com"

def restart_backend():
    print("=" * 70)
    print("🔄 REINICIANDO BACKEND VÍA API")
    print("=" * 70)
    print()
    
    try:
        # Intentar reiniciar vía endpoint de monitoring
        restart_url = f"{AWS_BACKEND_URL}/api/monitoring/restart-backend"
        print(f"📡 Llamando a: {restart_url}")
        
        response = requests.post(restart_url, timeout=30)
        
        if response.status_code == 200:
            print("   ✅ Backend reiniciado exitosamente")
            data = response.json()
            print(f"   → Respuesta: {data.get('message', 'OK')}")
        elif response.status_code == 401:
            print("   ⚠️  Requiere autenticación")
            print("   → El reinicio debe hacerse manualmente en el servidor")
        else:
            print(f"   ⚠️  Código de respuesta: {response.status_code}")
            print(f"   → {response.text[:200]}")
        
        print()
        print("⏳ Esperando 10 segundos para que el backend se reinicie...")
        time.sleep(10)
        
        # Verificar que el backend responde
        print()
        print("🔍 Verificando que el backend responde...")
        health_url = f"{AWS_BACKEND_URL}/api/health"
        response = requests.get(health_url, timeout=10)
        if response.status_code == 200:
            print("   ✅ Backend está respondiendo después del reinicio")
        else:
            print(f"   ⚠️  Backend no responde aún (código: {response.status_code})")
        
        print()
        print("=" * 70)
        print("✅ PROCESO COMPLETADO")
        print("=" * 70)
        print()
        print("💡 NOTA: Si el reinicio vía API no funcionó, necesitas:")
        print("   1. Conectarte al servidor AWS vía SSH")
        print("   2. Ejecutar: docker compose --profile aws restart backend")
        print("   3. O usar el script: ./restart_backend_aws.sh")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        print()
        print("💡 Alternativa: Reinicia manualmente en el servidor AWS:")
        print("   ssh ubuntu@54.254.150.31")
        print("   cd ~/crypto-2.0")
        print("   docker compose --profile aws restart backend")

if __name__ == "__main__":
    restart_backend()















