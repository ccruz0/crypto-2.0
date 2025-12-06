#!/usr/bin/env python3
"""
Script para verificar el estado de trade_enabled en la base de datos
"""
import os
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

def get_database_url():
    """Obtener la URL de la base de datos desde variables de entorno"""
    # Intentar diferentes fuentes de configuración
    db_url = os.getenv("DATABASE_URL")
    
    if not db_url:
        # Construir desde variables individuales
        db_user = os.getenv("POSTGRES_USER", "trader")
        db_password = os.getenv("POSTGRES_PASSWORD", "traderpass")
        db_host = os.getenv("POSTGRES_HOST", "localhost")
        db_port = os.getenv("POSTGRES_PORT", "5432")
        db_name = os.getenv("POSTGRES_DB", "atp")
        
        db_url = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
    
    return db_url

def verify_trade_enabled():
    """Verificar el estado de trade_enabled para todas las monedas"""
    try:
        db_url = get_database_url()
        print(f"🔗 Conectando a la base de datos...")
        print(f"   URL: {db_url.split('@')[1] if '@' in db_url else 'localhost'}")  # No mostrar credenciales
        
        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()
        
        # Consultar todas las monedas con sus estados de trade_enabled
        query = text("""
            SELECT 
                id,
                symbol,
                exchange,
                trade_enabled,
                trade_amount_usd,
                alert_enabled,
                is_deleted,
                updated_at,
                created_at
            FROM watchlist_items
            WHERE is_deleted = false
            ORDER BY symbol ASC
        """)
        
        result = session.execute(query)
        rows = result.fetchall()
        
        if not rows:
            print("\n❌ No se encontraron monedas en la base de datos")
            return
        
        print(f"\n📊 Encontradas {len(rows)} monedas en la base de datos:\n")
        print("=" * 100)
        print(f"{'Symbol':<15} {'Trade':<8} {'Amount USD':<12} {'Alert':<8} {'Updated':<20}")
        print("=" * 100)
        
        trade_yes_count = 0
        trade_no_count = 0
        
        for row in rows:
            symbol = row.symbol or "N/A"
            trade_enabled = "✅ YES" if row.trade_enabled else "❌ NO"
            amount = f"${row.trade_amount_usd:,.2f}" if row.trade_amount_usd else "N/A"
            alert = "✅ YES" if row.alert_enabled else "❌ NO"
            updated = str(row.updated_at) if row.updated_at else str(row.created_at) if row.created_at else "N/A"
            
            print(f"{symbol:<15} {trade_enabled:<8} {amount:<12} {alert:<8} {updated[:19]}")
            
            if row.trade_enabled:
                trade_yes_count += 1
            else:
                trade_no_count += 1
        
        print("=" * 100)
        print(f"\n📈 Resumen:")
        print(f"   ✅ Trade YES: {trade_yes_count} monedas")
        print(f"   ❌ Trade NO:  {trade_no_count} monedas")
        print(f"   📊 Total:     {len(rows)} monedas")
        
        # Verificar específicamente las monedas que aparecen en el dashboard
        dashboard_symbols = ["ETH_USDT", "SOL_USDT", "LDO_USD", "BTC_USD"]
        print(f"\n🔍 Verificación de monedas del dashboard:")
        print("=" * 100)
        
        for symbol in dashboard_symbols:
            query_specific = text("""
                SELECT 
                    symbol,
                    trade_enabled,
                    trade_amount_usd,
                    updated_at,
                    created_at
                FROM watchlist_items
                WHERE symbol = :symbol AND is_deleted = false
            """)
            
            result_specific = session.execute(query_specific, {"symbol": symbol})
            row_specific = result_specific.fetchone()
            
            if row_specific:
                status = "✅ YES" if row_specific.trade_enabled else "❌ NO"
                amount = f"${row_specific.trade_amount_usd:,.2f}" if row_specific.trade_amount_usd else "N/A"
                updated = str(row_specific.updated_at) if row_specific.updated_at else str(row_specific.created_at) if row_specific.created_at else "N/A"
                print(f"   {symbol:<15} Trade: {status:<8} Amount: {amount:<12} Updated: {updated[:19]}")
            else:
                print(f"   {symbol:<15} ⚠️  No encontrada en la base de datos")
        
        print("=" * 100)
        
        session.close()
        print("\n✅ Verificación completada")
        
    except Exception as e:
        print(f"\n❌ Error al verificar la base de datos: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    verify_trade_enabled()

