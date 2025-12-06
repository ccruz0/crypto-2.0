#!/usr/bin/env node
/**
 * Script para probar la API del frontend
 */

const API_KEY = 'demo-key';

// Use localhost for development
function getApiBaseUrl() {
  return 'http://localhost:8001/api';
}

async function getDashboard() {
  // Use crypto data endpoint for real data
  const response = await fetch(`${getApiBaseUrl()}/crypto-data`, {
    headers: {
      'X-API-Key': API_KEY
    }
  });
  
  if (!response.ok) {
    throw new Error('Failed to fetch dashboard');
  }
  
  const data = await response.json();
  if (data.success && data.data) {
    // Convert crypto data to watchlist format
    return data.data.map((crypto) => ({
      id: Math.random(),
      symbol: crypto.symbol,
      exchange: 'CRYPTO_COM',
      buy_target: crypto.price * 0.95, // 5% below current price
      take_profit: crypto.price * 1.1, // 10% above current price
      stop_loss: crypto.price * 0.9,  // 10% below current price
      current_price: crypto.price,
      signals: {
        buy: crypto.change_percent > 0,
        sell: crypto.change_percent < 0
      },
      stop_loss_conservative: crypto.price * 0.85,
      stop_loss_aggressive: crypto.price * 0.95,
      take_profit_conservative: crypto.price * 1.05,
      take_profit_aggressive: crypto.price * 1.15
    }));
  }
  
  return [];
}

async function testDashboard() {
  try {
    console.log('🔍 Probando getDashboard()...');
    const dashboard = await getDashboard();
    console.log(`✅ Dashboard cargado: ${dashboard.length} items`);
    console.log('📊 Primeros 3 items:');
    dashboard.slice(0, 3).forEach((item, i) => {
      console.log(`  ${i+1}. ${item.symbol}: $${item.current_price} (${item.signals.buy ? 'BUY' : 'SELL'})`);
    });
    return true;
  } catch (error) {
    console.error('❌ Error:', error.message);
    return false;
  }
}

// Ejecutar prueba
testDashboard().then(success => {
  if (success) {
    console.log('\n✅ ¡API del frontend funcionando correctamente!');
    console.log('🌐 El dashboard debería mostrar datos reales');
  } else {
    console.log('\n❌ Hay problemas con la API del frontend');
  }
});

