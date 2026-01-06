const { chromium } = require('./frontend/node_modules/playwright');

(async () => {
  console.log('🔍 Checking for duplicate signals requests...');
  
  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext();
  const page = await context.newPage();
  
  const signalsRequests = [];
  const consoleLogs = [];
  
  // Capture all signals requests
  page.on('request', request => {
    const url = request.url();
    if (url.includes('/signals')) {
      signalsRequests.push({
        url,
        symbol: url.match(/symbol=([^&]+)/)?.[1] || 'unknown',
        timestamp: Date.now(),
        method: request.method(),
      });
      console.log(`[SIGNALS REQUEST] ${request.method()} ${url}`);
    }
  });
  
  // Capture console logs
  page.on('console', msg => {
    const text = msg.text();
    const type = msg.type();
    if (type === 'error' || type === 'warn' || text.includes('signals') || text.includes('ALGO')) {
      consoleLogs.push({ type, text, timestamp: Date.now() });
      console.log(`[CONSOLE ${type.toUpperCase()}] ${text}`);
    }
  });
  
  try {
    console.log('📱 Navigating to http://localhost:3000...');
    await page.goto('http://localhost:3000', { waitUntil: 'domcontentloaded', timeout: 30000 });
    
    // Wait 10 seconds to capture all initial requests
    console.log('⏳ Waiting 10 seconds to capture all signals requests...');
    await page.waitForTimeout(10000);
    
    // Count requests per symbol
    const requestsBySymbol = {};
    signalsRequests.forEach(req => {
      const symbol = req.symbol;
      if (!requestsBySymbol[symbol]) {
        requestsBySymbol[symbol] = [];
      }
      requestsBySymbol[symbol].push(req);
    });
    
    // Take screenshot of network tab (if we can access it)
    await page.screenshot({ path: 'net_signals_filter.png', fullPage: true });
    console.log('📸 Screenshot: net_signals_filter.png');
    
    // Summary
    console.log('\n📊 SIGNALS REQUESTS SUMMARY (first 10s):');
    console.log('='.repeat(60));
    Object.entries(requestsBySymbol).forEach(([symbol, reqs]) => {
      console.log(`${symbol}: ${reqs.length} request(s)`);
      reqs.forEach((req, idx) => {
        const timeSinceStart = req.timestamp - signalsRequests[0].timestamp;
        console.log(`  ${idx + 1}. ${req.method} ${req.url} (at ${Math.round(timeSinceStart)}ms)`);
      });
    });
    
    const algoCount = requestsBySymbol['ALGO_USDT']?.length || 0;
    console.log(`\n🔍 ALGO_USDT requests in first 10s: ${algoCount}`);
    if (algoCount > 1) {
      console.log(`⚠️ DUPLICATE DETECTED: ALGO_USDT requested ${algoCount} times!`);
    }
    
    console.log(`\nTotal signals requests: ${signalsRequests.length}`);
    console.log('='.repeat(60));
    
  } catch (error) {
    console.error('❌ Error during test:', error);
  } finally {
    await browser.close();
  }
})();


