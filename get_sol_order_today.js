// Script para ejecutar en la consola del navegador del dashboard
// Para obtener la última orden SOL_USD SELL ejecutada hoy

// Obtener todas las órdenes ejecutadas desde el estado del componente
const getSOLOrderToday = () => {
  // Intentar obtener desde el estado de React (si está expuesto)
  if (window.__REACT_DEVTOOLS_GLOBAL_HOOK__) {
    console.log('React DevTools detectado');
  }
  
  // Buscar en el localStorage o sessionStorage
  const executedOrdersKey = Object.keys(localStorage).find(key => 
    key.includes('executed') || key.includes('order')
  );
  
  console.log('Buscando orden SOL_USD SELL de hoy...');
  
  // Método alternativo: buscar en el DOM
  const orderRows = document.querySelectorAll('[data-symbol="SOL_USD"], [data-instrument="SOL_USD"]');
  console.log(`Encontradas ${orderRows.length} filas con SOL_USD en el DOM`);
  
  // Si el dashboard tiene una función global para obtener órdenes
  if (window.getExecutedOrders) {
    const orders = window.getExecutedOrders();
    const solOrders = orders.filter(o => 
      o.instrument_name === 'SOL_USD' && 
      o.side === 'SELL' && 
      o.status === 'FILLED'
    );
    
    const today = new Date().toISOString().split('T')[0];
    const todayOrders = solOrders.filter(o => {
      if (o.update_datetime) {
        return o.update_datetime.startsWith(today);
      }
      if (o.update_time) {
        const dt = new Date(o.update_time);
        return dt.toISOString().split('T')[0] === today;
      }
      return false;
    });
    
    if (todayOrders.length > 0) {
      console.log('✅ Órdenes SOL_USD SELL de HOY encontradas:');
      todayOrders.forEach(order => {
        console.log({
          order_id: order.order_id,
          fecha: order.update_datetime || new Date(order.update_time).toISOString(),
          quantity: order.quantity,
          price: order.avg_price || order.price,
          cumulative_value: order.cumulative_value,
          order_type: order.order_type
        });
      });
      return todayOrders[0];
    }
  }
  
  console.log('No se encontró función getExecutedOrders. Intentando método alternativo...');
  
  // Método alternativo: hacer una llamada directa a la API
  fetch('/api/orders/history?limit=200&offset=0')
    .then(res => res.json())
    .then(data => {
      const orders = data.orders || [];
      const solOrders = orders.filter(o => 
        o.instrument_name === 'SOL_USD' && 
        o.side === 'SELL' && 
        o.status === 'FILLED'
      );
      
      const today = new Date().toISOString().split('T')[0];
      const todayOrders = solOrders.filter(o => {
        if (o.update_datetime) {
          return o.update_datetime.startsWith(today);
        }
        if (o.update_time) {
          const dt = new Date(o.update_time);
          return dt.toISOString().split('T')[0] === today;
        }
        return false;
      });
      
      if (todayOrders.length > 0) {
        console.log('✅ Órdenes SOL_USD SELL de HOY encontradas:');
        todayOrders.forEach(order => {
          console.log({
            order_id: order.order_id,
            fecha: order.update_datetime || new Date(order.update_time).toISOString(),
            quantity: order.quantity,
            price: order.avg_price || order.price,
            cumulative_value: order.cumulative_value,
            order_type: order.order_type
          });
        });
        return todayOrders[0];
      } else {
        console.log('No se encontraron órdenes de hoy. Última orden SOL_USD SELL:');
        if (solOrders.length > 0) {
          const last = solOrders[0];
          console.log({
            order_id: last.order_id,
            fecha: last.update_datetime || new Date(last.update_time).toISOString(),
            quantity: last.quantity,
            price: last.avg_price || last.price,
            cumulative_value: last.cumulative_value
          });
        }
      }
    })
    .catch(err => {
      console.error('Error al consultar API:', err);
      console.log('Por favor, ejecuta este script en la consola del navegador mientras estás en el dashboard');
    });
};

// Ejecutar automáticamente
getSOLOrderToday();







