// Script para pegar en la consola del navegador (F12) en la página del dashboard
// Copia y pega todo este código en la consola y presiona Enter

(function() {
  console.log('🔧 Iniciando fix para BTC_USDT...');
  
  // Detectar automáticamente la URL de la API
  function getApiUrl() {
    const hostname = window.location.hostname;
    
    // Si estamos en localhost, usar localhost
    if (hostname === 'localhost' || hostname === '127.0.0.1') {
      return 'http://localhost:8002/api';
    }
    
    // Si estamos en AWS (IP o dominio)
    if (hostname.includes('54.254.150.31') || hostname.includes('hilovivo') || hostname.includes('ec2')) {
      // Si es dominio hilovivo, usar el mismo dominio (Nginx proxy)
      if (hostname.includes('hilovivo')) {
        return `${window.location.protocol}//${hostname}/api`;
      }
      // Si es IP de AWS, usar puerto 8002 (según environment.ts línea 103)
      return 'http://54.254.150.31:8002/api';
    }
    
    // Por defecto, intentar usar el mismo hostname con puerto 8002
    return `http://${hostname}:8002/api`;
  }
  
  const API_URL = getApiUrl();
  console.log('🌐 API URL detectada:', API_URL);
  
  const fixes = [];
  let needsReload = false;
  
  // 1. Limpiar deleted_coins
  try {
    const deletedCoins = JSON.parse(localStorage.getItem('deleted_coins') || '[]');
    const beforeCount = deletedCoins.length;
    const updated = deletedCoins.filter(c => c.toUpperCase() !== 'BTC_USDT');
    
    if (beforeCount !== updated.length) {
      localStorage.setItem('deleted_coins', JSON.stringify(updated));
      fixes.push(`✅ Removido BTC_USDT de deleted_coins`);
      needsReload = true;
    } else {
      fixes.push(`✅ BTC_USDT no estaba en deleted_coins`);
    }
  } catch (e) {
    fixes.push(`❌ Error: ${e.message}`);
  }
  
  // 2. Verificar watchlist_order
  try {
    const watchlistOrder = JSON.parse(localStorage.getItem('watchlist_order') || '{}');
    if ('BTC_USDT' in watchlistOrder) {
      fixes.push(`✅ BTC_USDT tiene orden: ${watchlistOrder['BTC_USDT']}`);
    } else {
      fixes.push(`ℹ️ BTC_USDT no tiene orden específica (normal)`);
    }
  } catch (e) {
    fixes.push(`⚠️ Error verificando watchlist_order: ${e.message}`);
  }
  
  // 3. Verificar si está en los datos actuales
  try {
    // Intentar encontrar BTC_USDT en el estado de React (si está disponible)
    const reactElements = document.querySelectorAll('[data-testid*="BTC_USDT"], [data-testid*="btc_usdt"]');
    if (reactElements.length > 0) {
      fixes.push(`✅ BTC_USDT encontrado en el DOM (${reactElements.length} elementos)`);
    } else {
      fixes.push(`⚠️ BTC_USDT no encontrado en el DOM - puede necesitar recarga`);
      needsReload = true;
    }
  } catch (e) {
    fixes.push(`ℹ️ No se pudo verificar DOM: ${e.message}`);
  }
  
  // Mostrar resultados
  console.log('\n📋 Resultados:');
  fixes.forEach(fix => console.log(fix));
  
  if (needsReload) {
    console.log('\n🔄 Recargando página en 2 segundos...');
    setTimeout(() => {
      window.location.reload();
    }, 2000);
  } else {
    console.log('\n✅ No se necesitan cambios. Si BTC_USDT aún no aparece, verifica:');
    console.log('   1. Que el backend esté devolviendo BTC_USDT en /api/market/top-coins-data');
    console.log('   2. Que no haya otros filtros activos en el frontend');
    console.log('   3. Intenta hacer un hard refresh (Cmd+Shift+R o Ctrl+Shift+R)');
  }
})();







