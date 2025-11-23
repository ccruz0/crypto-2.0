#!/usr/bin/env python3
"""Script mejorado para ver los últimos mensajes de Telegram"""
import subprocess
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

def check_logs():
    """Check Docker logs for Telegram messages"""
    print("🔍 Buscando en logs de Docker...\n")
    
    try:
        # Get logs with more context
        result = subprocess.run(
            ['docker', 'compose', 'logs', '--tail=2000', '--since=24h', 'backend'],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            print(f"⚠️ Error obteniendo logs: {result.stderr[:200]}")
            return []
        
        lines = result.stdout.split('\n')
        
        # Find lines that mention Telegram
        telegram_lines = []
        for i, line in enumerate(lines):
            line_lower = line.lower()
            if any(keyword in line_lower for keyword in [
                'telegram message sent',
                '[tg]',
                '[telegram]',
                'send_message',
                'buy order created',
                'sell order created',
                'order executed',
                'sl/tp orders',
                'buy signal',
                'sell signal',
                'protección activada'
            ]):
                # Get context (previous and next lines)
                context_start = max(0, i-2)
                context_end = min(len(lines), i+3)
                context = '\n'.join(lines[context_start:context_end])
                telegram_lines.append({
                    'line_num': i,
                    'content': line,
                    'context': context
                })
        
        return telegram_lines[-3:] if len(telegram_lines) >= 3 else telegram_lines
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return []

def check_recent_orders():
    """Check for recent orders that might have triggered Telegram messages"""
    print("\n🔍 Buscando órdenes recientes que podrían haber generado mensajes...\n")
    
    try:
        from app.database import SessionLocal
        from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
        from datetime import datetime, timedelta
        
        db = SessionLocal()
        try:
            # Get orders from last 24 hours
            yesterday = datetime.utcnow() - timedelta(hours=24)
            
            recent_orders = db.query(ExchangeOrder).filter(
                ExchangeOrder.created_at >= yesterday
            ).order_by(ExchangeOrder.created_at.desc()).limit(10).all()
            
            if recent_orders:
                print(f"📊 Encontradas {len(recent_orders)} órdenes recientes:\n")
                for order in recent_orders[:3]:
                    print(f"  • {order.symbol} {order.side} - {order.status}")
                    print(f"    Creada: {order.created_at}")
                    print(f"    ID: {order.exchange_order_id}\n")
                return True
            else:
                print("  ℹ️ No se encontraron órdenes en las últimas 24 horas")
                return False
        finally:
            db.close()
            
    except Exception as e:
        print(f"  ⚠️ No se pudo consultar la base de datos: {e}")
        return False

def main():
    print("=" * 80)
    print("📱 VERIFICACIÓN DE MENSAJES DE TELEGRAM")
    print("=" * 80)
    
    # Check logs
    telegram_messages = check_logs()
    
    if telegram_messages:
        print(f"\n✅ Encontrados {len(telegram_messages)} mensajes relacionados con Telegram:\n")
        for i, msg in enumerate(telegram_messages, 1):
            print(f"\n{'='*80}")
            print(f"📩 Mensaje #{i}")
            print(f"{'='*80}")
            print(msg['content'])
            if len(telegram_messages) > 1 and i < len(telegram_messages):
                print()
    else:
        print("\n❌ No se encontraron mensajes de Telegram en los logs de las últimas 24 horas.")
        print("\n💡 Posibles razones:")
        print("   • No se han enviado mensajes recientemente")
        print("   • Los logs fueron rotados o limpiados")
        print("   • El servicio de Telegram está deshabilitado")
    
    # Check recent orders
    check_recent_orders()
    
    print("\n" + "=" * 80)
    print("\n💡 Para ver logs en tiempo real:")
    print("   docker compose logs -f backend | grep -i telegram")
    print("=" * 80)

if __name__ == "__main__":
    main()

