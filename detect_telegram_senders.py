#!/usr/bin/env python3
"""
Script para detectar qué servicios están enviando mensajes a Telegram
"""
import os
import sys
import subprocess
from datetime import datetime, timedelta

def run_command(cmd):
    """Ejecuta un comando y retorna el output"""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=30
        )
        return result.stdout.strip()
    except Exception as e:
        return f"Error: {e}"

def check_docker_logs():
    """Revisa los logs de Docker para encontrar mensajes de Telegram"""
    print("=" * 80)
    print("🔍 REVISANDO LOGS DE DOCKER PARA MENSAJES DE TELEGRAM")
    print("=" * 80)
    
    # Buscar mensajes enviados a Telegram
    cmd = "docker compose logs --tail=500 backend 2>&1 | grep -E 'send.*message|Telegram.*sent|BUY SIGNAL|ORDER.*CREATED|send_buy_signal|send_order_created|send_executed_order|send_sl_tp' | tail -20"
    output = run_command(cmd)
    
    if output and "Error" not in output:
        print("\n📨 ÚLTIMOS MENSAJES DE TELEGRAM ENVIADOS:")
        print("-" * 80)
        print(output)
    else:
        print("\n⚠️  No se encontraron mensajes recientes de Telegram en los logs")
    
    # Buscar qué servicios están activos
    print("\n" + "=" * 80)
    print("🔧 SERVICIOS ACTIVOS QUE PUEDEN ENVIAR MENSAJES")
    print("=" * 80)
    
    services = [
        ("SignalMonitorService", "signal_monitor|Signal Monitor|monitor_signals"),
        ("SLTPCheckerService", "sl_tp|SL/TP|send_sl_tp"),
        ("ExchangeSyncService", "exchange_sync|Exchange Sync"),
        ("DailySummaryService", "daily_summary|Daily Summary"),
        ("BuyIndexMonitor", "buy_index|Buy Index"),
    ]
    
    for service_name, pattern in services:
        cmd = f"docker compose logs --tail=200 backend 2>&1 | grep -i '{pattern}' | tail -5"
        output = run_command(cmd)
        if output and "Error" not in output:
            print(f"\n✅ {service_name} - ACTIVO:")
            print(output[:500])  # Limitar output
        else:
            print(f"\n❌ {service_name} - No hay actividad reciente")

def check_environment():
    """Verifica la configuración del entorno"""
    print("\n" + "=" * 80)
    print("⚙️  CONFIGURACIÓN DEL ENTORNO")
    print("=" * 80)
    
    # Verificar variables de entorno en el contenedor
    cmd = "docker compose exec -T backend env 2>&1 | grep -E 'APP_ENV|TELEGRAM' || echo 'Container no disponible'"
    output = run_command(cmd)
    
    print("\n📋 Variables de entorno en el contenedor:")
    if output:
        for line in output.split('\n'):
            if 'TELEGRAM' in line or 'APP_ENV' in line:
                # Ocultar valores sensibles
                if 'TOKEN' in line:
                    parts = line.split('=')
                    if len(parts) == 2:
                        print(f"  {parts[0]}=***{'*' * min(10, len(parts[1]))}")
                    else:
                        print(f"  {line}")
                else:
                    print(f"  {line}")
    
    # Verificar archivo .env local
    print("\n📋 Variables en .env local:")
    if os.path.exists('.env'):
        with open('.env', 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and ('TELEGRAM' in line or 'APP_ENV' in line):
                    if 'TOKEN' in line:
                        parts = line.split('=')
                        if len(parts) == 2:
                            print(f"  {parts[0]}=***{'*' * min(10, len(parts[1]))}")
                        else:
                            print(f"  {line}")
                    else:
                        print(f"  {line}")
    else:
        print("  ⚠️  No se encontró archivo .env")

def check_signal_monitor_status():
    """Verifica el estado del Signal Monitor"""
    print("\n" + "=" * 80)
    print("📊 ESTADO DEL SIGNAL MONITOR")
    print("=" * 80)
    
    cmd = "docker compose logs --tail=100 backend 2>&1 | grep -E 'Signal Monitor|watchlist.*alert_enabled|No watchlist items' | tail -10"
    output = run_command(cmd)
    
    if output:
        print(output)
    else:
        print("⚠️  No se encontró información del Signal Monitor")

def check_recent_telegram_activity():
    """Busca actividad reciente de Telegram en los logs"""
    print("\n" + "=" * 80)
    print("📱 ACTIVIDAD RECIENTE DE TELEGRAM (últimas 2 horas)")
    print("=" * 80)
    
    # Buscar cualquier referencia a Telegram en los últimos logs
    cmd = "docker compose logs --since=2h backend 2>&1 | grep -i 'telegram\|send.*message\|alert\|signal' | tail -30"
    output = run_command(cmd)
    
    if output and "Error" not in output:
        print(output)
    else:
        print("⚠️  No se encontró actividad reciente de Telegram")

def main():
    print("\n" + "=" * 80)
    print("🔍 DETECTOR DE ENVIADORES DE MENSAJES A TELEGRAM")
    print("=" * 80)
    print(f"⏰ Fecha/Hora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    check_environment()
    check_signal_monitor_status()
    check_docker_logs()
    check_recent_telegram_activity()
    
    print("\n" + "=" * 80)
    print("✅ ANÁLISIS COMPLETADO")
    print("=" * 80)
    print("\n💡 NOTAS:")
    print("  - Si no hay mensajes en los logs, puede que:")
    print("    1. No hay watchlist items con alert_enabled=true")
    print("    2. Las variables TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID no están configuradas")
    print("    3. Los mensajes están viniendo del servidor AWS (no local)")
    print("  - Para ver mensajes de AWS, necesitas acceder a los logs del servidor AWS")
    print("\n")

if __name__ == "__main__":
    main()

