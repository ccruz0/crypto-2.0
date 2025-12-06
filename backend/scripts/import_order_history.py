#!/usr/bin/env python3
"""
Script to import historical orders into the database.
This script allows importing a list of executed orders from Crypto.com Exchange.

Usage:
    python scripts/import_order_history.py [CSV_FILE_PATH]

The script can read from:
    1. CSV file path provided as argument
    2. JSON file path provided as argument
    3. JSON input from stdin (interactive)

CSV format (from Crypto.com export):
    Order ID,Time (UTC),Pair,Order Type,Side,Order Amount,Average Price,Deal Volume,Total,Trigger Condition,Status
"""

import sys
import json
import csv
from datetime import datetime
from typing import List, Dict, Any

# Add parent directory to path
sys.path.insert(0, '/app')

from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum

def parse_csv_row(row: Dict[str, str]) -> Dict[str, Any]:
    """
    Parse CSV row from Crypto.com export format to API format.
    
    CSV format:
        Order ID,Time (UTC),Pair,Order Type,Side,Order Amount,Average Price,Deal Volume,Total,Trigger Condition,Status
    """
    order_id = row.get('Order ID', '').strip()
    if not order_id:
        raise ValueError("Order ID is required")
    
    time_str = row.get('Time (UTC)', '').strip()
    try:
        # Parse time: "2025-10-31 00:01:07.241"
        time_obj = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S.%f")
        create_time_ms = int(time_obj.timestamp() * 1000)
        update_time_ms = create_time_ms  # Use same time for create and update
    except ValueError:
        try:
            # Try without microseconds
            time_obj = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
            create_time_ms = int(time_obj.timestamp() * 1000)
            update_time_ms = create_time_ms
        except ValueError:
            raise ValueError(f"Invalid time format: {time_str}")
    
    return {
        'order_id': order_id,
        'instrument_name': row.get('Pair', '').strip(),
        'side': row.get('Side', '').strip().upper(),
        'order_type': row.get('Order Type', 'LIMIT').strip().upper(),
        'status': row.get('Status', '').strip().upper(),
        'quantity': row.get('Order Amount', '0').strip(),
        'price': row.get('Average Price', '0').strip(),
        'cumulative_quantity': row.get('Deal Volume', '0').strip(),
        'cumulative_value': row.get('Total', '0').strip(),
        'avg_price': row.get('Average Price', '0').strip(),
        'trigger_condition': row.get('Trigger Condition', '0').strip(),
        'create_time': create_time_ms,
        'update_time': update_time_ms
    }

def parse_order_data(order_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse order data from API format to database format.
    
    Expected format:
    {
        "order_id": "5755600476554550077",
        "instrument_name": "LDO_USD",
        "side": "BUY",
        "status": "FILLED",
        "order_type": "LIMIT",
        "quantity": "11902.4",
        "price": "0.8402",
        "cumulative_quantity": "11902.4",
        "cumulative_value": "10000.0",
        "avg_price": "0.8402",
        "create_time": 1698768000000,  # milliseconds
        "update_time": 1698768100000   # milliseconds
    }
    """
    order_id = str(order_data.get('order_id', ''))
    if not order_id:
        raise ValueError("order_id is required")
    
    symbol = order_data.get('instrument_name', '')
    if not symbol:
        raise ValueError("instrument_name is required")
    
    side_str = order_data.get('side', '').upper()
    if side_str not in ['BUY', 'SELL']:
        raise ValueError(f"Invalid side: {side_str}")
    side = OrderSideEnum.BUY if side_str == 'BUY' else OrderSideEnum.SELL
    
    status_str = order_data.get('status', '').upper()
    if status_str not in ['FILLED', 'CANCELLED', 'ACTIVE', 'PARTIALLY_FILLED']:
        # Default to FILLED for executed orders
        status_str = 'FILLED'
    status = OrderStatusEnum[status_str]
    
    order_type = order_data.get('order_type', 'LIMIT')
    
    # Parse quantities and prices (handle both string and numeric, remove commas)
    quantity_str = str(order_data.get('quantity', '0')).replace(',', '')
    quantity = float(quantity_str or '0')
    
    cumulative_quantity_str = str(order_data.get('cumulative_quantity', '0')).replace(',', '')
    cumulative_quantity = float(cumulative_quantity_str or str(quantity))
    
    # Price: prioritize limit_price, then price, then avg_price
    price_str = str(order_data.get('limit_price') or order_data.get('price') or order_data.get('avg_price') or '0').replace(',', '')
    price = float(price_str or '0')
    
    avg_price_str = str(order_data.get('avg_price') or price_str).replace(',', '')
    avg_price = float(avg_price_str or '0')
    
    cumulative_value_str = str(order_data.get('cumulative_value', '0')).replace(',', '')
    cumulative_value = float(cumulative_value_str or '0') or (cumulative_quantity * avg_price)
    
    # Parse trigger_condition (for stop/limit orders)
    trigger_condition_str = str(order_data.get('trigger_condition', '0')).replace(',', '')
    trigger_condition = float(trigger_condition_str or '0') if trigger_condition_str and float(trigger_condition_str or '0') > 0 else None
    
    # Parse timestamps (milliseconds to datetime)
    create_time = None
    if order_data.get('create_time'):
        try:
            create_time = datetime.fromtimestamp(order_data['create_time'] / 1000)
        except (ValueError, TypeError):
            pass
    
    update_time = None
    if order_data.get('update_time'):
        try:
            update_time = datetime.fromtimestamp(order_data['update_time'] / 1000)
        except (ValueError, TypeError):
            pass
    
    # Use cumulative_quantity as the executed quantity for filled orders
    executed_quantity = cumulative_quantity if cumulative_quantity > 0 else quantity
    
    # Set imported_at timestamp (current time when importing)
    imported_at = datetime.utcnow()
    
    return {
        'exchange_order_id': order_id,
        'client_oid': order_data.get('client_oid'),
        'symbol': symbol,
        'side': side,
        'order_type': order_type,
        'status': status,
        'price': price if price > 0 else None,
        'quantity': executed_quantity,
        'cumulative_quantity': cumulative_quantity,
        'cumulative_value': cumulative_value,
        'avg_price': avg_price if avg_price > 0 else None,
        'trigger_condition': trigger_condition,
        'exchange_create_time': create_time,
        'exchange_update_time': update_time or create_time or datetime.utcnow(),
        'imported_at': imported_at
    }

def import_orders(orders: List[Dict[str, Any]], db: SessionLocal) -> Dict[str, int]:
    """
    Import orders into the database.
    Returns a dict with counts: {'total': N, 'new': M, 'existing': K, 'errors': E}
    """
    stats = {'total': len(orders), 'new': 0, 'existing': 0, 'errors': 0}
    
    for i, order_data in enumerate(orders, 1):
        try:
            # Parse order data
            parsed = parse_order_data(order_data)
            order_id = parsed['exchange_order_id']
            
            # Check if order already exists
            existing = db.query(ExchangeOrder).filter(
                ExchangeOrder.exchange_order_id == order_id
            ).first()
            
            if existing:
                print(f"  [{i}/{stats['total']}] ⚠️  Order {order_id} ({parsed['symbol']}) already exists - skipping")
                stats['existing'] += 1
                continue
            
            # Create new order (order doesn't exist)
            # Set imported_at timestamp for newly imported orders
            if 'imported_at' not in parsed:
                parsed['imported_at'] = datetime.utcnow()
            new_order = ExchangeOrder(**parsed)
            db.add(new_order)
            stats['new'] += 1
            
            print(f"  [{i}/{stats['total']}] ✅ Order {order_id} ({parsed['symbol']} {parsed['side']}) - {parsed['quantity']} @ {parsed['price'] or 'MARKET'}")
            
        except Exception as e:
            stats['errors'] += 1
            print(f"  [{i}/{stats['total']}] ❌ Error importing order: {e}")
            continue
    
    # Commit all new orders
    if stats['new'] > 0:
        try:
            db.commit()
            print(f"\n✅ Successfully imported {stats['new']} new orders")
        except Exception as e:
            db.rollback()
            print(f"\n❌ Error committing orders: {e}")
            stats['errors'] += stats['new']
            stats['new'] = 0
    
    return stats

def read_csv_file(file_path: str) -> List[Dict[str, str]]:
    """Read CSV file and return list of rows as dictionaries"""
    rows = []
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
        # Find the header row (starts with "Order ID")
        header_idx = None
        for i, line in enumerate(lines):
            if 'Order ID' in line and 'Pair' in line:
                header_idx = i
                break
        
        if header_idx is None:
            raise ValueError("Could not find CSV header row with 'Order ID' and 'Pair'")
        
        # Skip lines before header
        remaining_lines = lines[header_idx:]
        
        # Read CSV from header
        reader = csv.DictReader(remaining_lines)
        for row in reader:
            # Skip empty rows
            order_id = row.get('Order ID', '').strip() if row.get('Order ID') else ''
            if not order_id:
                continue
            rows.append(row)
    
    return rows

def main():
    """Main function to import orders"""
    print("=" * 80)
    print("📋 IMPORTAR ÓRDENES HISTÓRICAS A LA BASE DE DATOS")
    print("=" * 80)
    print("\nEste script importa órdenes ejecutadas de Crypto.com Exchange.")
    print("Las órdenes que ya existen en la base de datos serán omitidas.\n")
    
    # Check if orders are provided as command-line argument
    orders = []
    
    if len(sys.argv) > 1:
        # Read orders from file
        file_path = sys.argv[1]
        print(f"📁 Leyendo órdenes desde: {file_path}")
        
        try:
            # Try CSV first
            if file_path.lower().endswith('.csv'):
                print("📄 Detectado formato CSV")
                csv_rows = read_csv_file(file_path)
                
                # Convert CSV rows to API format
                for row in csv_rows:
                    try:
                        api_format = parse_csv_row(row)
                        orders.append(api_format)
                    except Exception as e:
                        print(f"⚠️  Error parseando fila CSV: {e}")
                        continue
            else:
                # Try JSON
                print("📄 Detectado formato JSON")
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Handle both list and dict with 'data' key
                    if isinstance(data, list):
                        orders = data
                    elif isinstance(data, dict) and 'data' in data:
                        orders = data['data']
                    else:
                        print("❌ Formato inválido: el archivo debe contener una lista o un objeto con clave 'data'")
                        sys.exit(1)
        except FileNotFoundError:
            print(f"❌ Archivo no encontrado: {file_path}")
            sys.exit(1)
        except (json.JSONDecodeError, csv.Error) as e:
            print(f"❌ Error al parsear archivo: {e}")
            sys.exit(1)
    else:
        # Prompt for orders interactively
        print("Por favor, pega las órdenes en formato JSON (una lista o un objeto con clave 'data'):")
        print("(Presiona Ctrl+D o Ctrl+Z para terminar)\n")
        
        try:
            lines = []
            while True:
                try:
                    line = input()
                    lines.append(line)
                except EOFError:
                    break
            
            if not lines:
                print("❌ No se proporcionaron órdenes")
                sys.exit(1)
            
            json_str = '\n'.join(lines)
            data = json.loads(json_str)
            
            # Handle both list and dict with 'data' key
            if isinstance(data, list):
                orders = data
            elif isinstance(data, dict) and 'data' in data:
                orders = data['data']
            else:
                print("❌ Formato inválido: debe ser una lista o un objeto con clave 'data'")
                sys.exit(1)
                
        except json.JSONDecodeError as e:
            print(f"❌ Error al parsear JSON: {e}")
            sys.exit(1)
        except KeyboardInterrupt:
            print("\n❌ Operación cancelada por el usuario")
            sys.exit(1)
    
    if not orders:
        print("❌ No se encontraron órdenes para importar")
        sys.exit(1)
    
    print(f"\n📊 Encontradas {len(orders)} órdenes para importar\n")
    
    # Check for --yes or -y flag to skip confirmation
    auto_confirm = '--yes' in sys.argv or '-y' in sys.argv
    
    # Confirm import (unless auto_confirm is set)
    if not auto_confirm:
        print("⚠️  ADVERTENCIA: Este script solo agrega nuevas órdenes.")
        print("   Las órdenes que ya existen en la base de datos serán omitidas.")
        response = input("\n¿Continuar con la importación? (s/n): ").strip().lower()
        
        if response not in ['s', 'y', 'yes', 'sí', 'si']:
            print("❌ Importación cancelada")
            sys.exit(0)
    else:
        print("⚠️  ADVERTENCIA: Este script solo agrega nuevas órdenes.")
        print("   Las órdenes que ya existen en la base de datos serán omitidas.")
        print("   (Confirmación automática activada)\n")
    
    # Connect to database
    db = SessionLocal()
    
    try:
        print("\n🔄 Importando órdenes...\n")
        stats = import_orders(orders, db)
        
        print("\n" + "=" * 80)
        print("📊 RESUMEN DE IMPORTACIÓN")
        print("=" * 80)
        print(f"Total de órdenes procesadas: {stats['total']}")
        print(f"  ✅ Nuevas órdenes agregadas: {stats['new']}")
        print(f"  ⚠️  Órdenes ya existentes (omitidas): {stats['existing']}")
        print(f"  ❌ Errores: {stats['errors']}")
        print("=" * 80)
        
    finally:
        db.close()

if __name__ == '__main__':
    main()
