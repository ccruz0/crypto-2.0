// Script to check and fix frontend localStorage filters
// Run this in the browser console on the dashboard page

console.log('🔍 Checking frontend filters for BTC_USDT...');

// Check deleted_coins
const deletedCoins = JSON.parse(localStorage.getItem('deleted_coins') || '[]');
console.log('📋 Deleted coins in localStorage:', deletedCoins);

if (deletedCoins.includes('BTC_USDT') || deletedCoins.some(c => c.toUpperCase() === 'BTC_USDT')) {
  console.log('⚠️  BTC_USDT found in deleted_coins! Removing...');
  const updated = deletedCoins.filter(c => c.toUpperCase() !== 'BTC_USDT');
  localStorage.setItem('deleted_coins', JSON.stringify(updated));
  console.log('✅ Removed BTC_USDT from deleted_coins');
  console.log('🔄 Please refresh the page to see BTC_USDT');
} else {
  console.log('✅ BTC_USDT is NOT in deleted_coins');
}

// Check watchlist_order
const watchlistOrder = JSON.parse(localStorage.getItem('watchlist_order') || '{}');
console.log('📋 Watchlist order:', Object.keys(watchlistOrder).length, 'coins');

// Check if BTC_USDT is in topCoins data
console.log('💡 Tip: Check the Network tab to see if BTC_USDT is in the /api/market/top-coins-data response');







