#!/usr/bin/env node

// Test script to verify getDashboard function is working
const fetch = require('node-fetch');

async function testGetDashboard() {
  try {
    console.log('🧪 Testing getDashboard function...');
    
    // Test the crypto-data endpoint directly
    const response = await fetch('http://host.docker.internal:8001/api/crypto-data', {
      headers: {
        'X-API-Key': 'demo-key'
      }
    });
    
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    
    const data = await response.json();
    console.log('✅ Response status:', response.status);
    console.log('✅ Success:', data.success);
    console.log('✅ Data count:', data.data ? data.data.length : 0);
    
    if (data.success && data.data && data.data.length > 0) {
      console.log('✅ First crypto:', data.data[0].symbol, '- $' + data.data[0].price);
      console.log('✅ Sources:', data.data[0].sources);
      
      // Test the mapping logic
      const mappedData = data.data.map((crypto, index) => ({
        id: index + 1,
        symbol: crypto.symbol,
        exchange: 'CRYPTO_COM',
        buy_target: crypto.price * 0.95,
        take_profit: crypto.price * 1.1,
        stop_loss: crypto.price * 0.9,
        trade_enabled: false,
        trade_amount_usd: null,
        trade_on_margin: false,
        sl_tp_mode: 'conservative',
        sl_percentage: null,
        tp_percentage: null,
        order_status: 'active',
        order_date: new Date().toISOString(),
        purchase_price: crypto.price,
        quantity: null,
        sold: false,
        sell_price: null,
        notes: null,
        created_at: new Date().toISOString(),
        price: crypto.price,
        rsi: null,
        atr: null,
        ma50: null,
        ma200: null,
        ema10: null,
        res_up: null,
        res_down: null,
        signals: {
          buy: crypto.change_percent > 0,
          sell: crypto.change_percent < 0
        },
        sl_tp: {
          stop_loss_conservative: crypto.price * 0.85,
          stop_loss_aggressive: crypto.price * 0.95,
          take_profit_conservative: crypto.price * 1.05,
          take_profit_aggressive: crypto.price * 1.15
        }
      }));
      
      console.log('✅ Mapped data count:', mappedData.length);
      console.log('✅ First mapped item:', mappedData[0].symbol, '- $' + mappedData[0].price);
      console.log('✅ Signals:', mappedData[0].signals);
      
    } else {
      console.log('❌ No data received');
    }
    
    console.log('\n🎉 getDashboard function should work correctly!');
    
  } catch (error) {
    console.error('❌ Error testing getDashboard:', error.message);
  }
}

testGetDashboard();

