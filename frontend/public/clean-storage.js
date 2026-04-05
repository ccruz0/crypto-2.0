// Script para limpiar localStorage de valores obsoletos de trade_amount_usd
// Ejecutar en la consola del navegador (F12) con: 
//   fetch('/clean-storage.js').then(r => r.text()).then(eval)

(function() {
  console.log('🧹 Limpiando localStorage de valores obsoletos...');
  
  // Obtener todos los símbolos del backend (los que están en la watchlist)
  const backendSymbols = [
    'AAVE_USD', 'ADA_USD', 'ADA_USDT', 'AKT_USDT', 'ALGO_USDT', 
    'APT_USDT', 'BONK_USD', 'BTC_USDT', 'CRO_USDT', 'DGB_USDT',
    'DOGE_USD', 'DOT_USD', 'ETH_USD', 'ETH_USDT', 'LDO_USD',
    'NEAR_USDT', 'SOL_USD', 'SUI_USDT', 'TON_USDT', 'XRP_USDT'
  ].map(s => s.toUpperCase());
  
  // Limpiar watchlist_amounts
  const amounts = localStorage.getItem('watchlist_amounts');
  if (amounts) {
    try {
      const amountsObj = JSON.parse(amounts);
      const cleaned = {};
      let removedCount = 0;
      
      Object.entries(amountsObj).forEach(([symbol, value]) => {
        const symbolUpper = symbol.toUpperCase();
        // Solo mantener valores para símbolos que NO están en el backend
        // O valores que no son "10" (valor obsoleto)
        if (!backendSymbols.includes(symbolUpper)) {
          cleaned[symbol] = value;
        } else if (value !== '10' && value !== '10.0' && value !== '10.00') {
          // Si el símbolo está en backend pero el valor no es 10, mantenerlo
          cleaned[symbol] = value;
        } else {
          removedCount++;
        }
      });
      
      localStorage.setItem('watchlist_amounts', JSON.stringify(cleaned));
      console.log(`✅ Limpiado localStorage: ${removedCount} valores obsoletos eliminados`);
      console.log(`📊 Valores restantes:`, cleaned);
      
      // Recargar la página para aplicar los cambios
      console.log('🔄 Recargando página...');
      setTimeout(() => location.reload(), 1000);
    } catch (err) {
      console.error('❌ Error limpiando localStorage:', err);
    }
  } else {
    console.log('ℹ️ No hay valores en localStorage para limpiar');
  }
})();












