#!/usr/bin/env python3
"""Script to display Crypto.com Exchange portfolio"""
from app.services.brokers.crypto_com_trade import trade_client

print("📊 CARTERA DE CRYPTO.COM EXCHANGE")
print("=" * 70)

# Get balances
response = trade_client.get_account_summary()

if 'accounts' in response:
    accounts = response['accounts']
    
    # Filter only positive balances and sort
    positive_balances = []
    for acc in accounts:
        balance = float(acc.get('balance', 0))
        if balance > 0:
            positive_balances.append({
                'currency': acc.get('currency', ''),
                'balance': balance,
                'available': float(acc.get('available', balance)),
                'locked': balance - float(acc.get('available', balance))
            })
    
    # Sort by balance descending
    positive_balances.sort(key=lambda x: x['balance'], reverse=True)
    
    print(f"\n✅ Total de assets con balance: {len(positive_balances)}\n")
    print(f"{'Asset':<12} {'Balance':<30} {'Available':<30} {'Locked':<20}")
    print("-" * 95)
    
    for acc in positive_balances:
        currency = acc['currency']
        balance = acc['balance']
        available = acc['available']
        locked = acc['locked']
        
        # Format numbers according to size
        if balance >= 1000000:
            balance_str = f"{balance:,.2f}"
        elif balance >= 1:
            balance_str = f"{balance:,.4f}"
        else:
            balance_str = f"{balance:.8f}"
        
        if available >= 1000000:
            available_str = f"{available:,.2f}"
        elif available >= 1:
            available_str = f"{available:,.4f}"
        else:
            available_str = f"{available:.8f}"
        
        locked_str = f"{locked:.4f}" if locked > 0 else "0"
        
        print(f"{currency:<12} {balance_str:>29} {available_str:>29} {locked_str:>19}")
    
    print("\n" + "=" * 70)
    
    # Calculate totals in USD if available
    usd_assets = [acc for acc in positive_balances if acc['currency'] in ['USD', 'USDT']]
    if usd_assets:
        total_usd = sum(acc['balance'] for acc in usd_assets)
        print(f"💰 Balance en USD/USDT: ${total_usd:,.2f}")

print("\n🔍 ÓRDENES ABIERTAS:")
print("=" * 70)

orders_response = trade_client.get_open_orders()

if 'data' in orders_response:
    orders = orders_response['data']
    
    if orders:
        print(f"\n✅ Total de órdenes abiertas: {len(orders)}\n")
        print(f"{'Symbol':<15} {'Side':<8} {'Status':<15} {'Quantity':<20} {'Price':<20}")
        print("-" * 85)
        
        for order in orders[:10]:  # Show first 10
            symbol = order.get('instrument_name', '')
            side = order.get('side', '')
            status = order.get('status', '')
            quantity = order.get('quantity', '0')
            price = order.get('price', '0')
            
            print(f"{symbol:<15} {side:<8} {status:<15} {str(quantity):<20} {str(price):<20}")
        
        if len(orders) > 10:
            print(f"\n... y {len(orders) - 10} órdenes más")
    else:
        print("\n✅ No hay órdenes abiertas")
else:
    print("\n⚠️ No se pudo obtener órdenes abiertas")

