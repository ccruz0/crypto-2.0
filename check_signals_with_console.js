const { chromium } = require('./frontend/node_modules/playwright');

(async () => {
  console.log('🔍 Checking for duplicate signals requests with console logs...');
  
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
  
  // Capture ALL console logs
  page.on('console', msg => {
    const text = msg.text();
    const type = msg.type();
    consoleLogs.push({ type, text, timestamp: Date.now() });
    if (text.includes('signals') || text.includes('ALGO') || text.includes('Cache')) {
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
    
    // Summary
    console.log('\n📊 SIGNALS REQUESTS SUMMARY (first 10s):');
    console.log('='.repeat(60));
    Object.entries(requestsBySymbol).forEach(([symbol, reqs]) => {
      console.log(`${symbol}: ${reqs.length} request(s)`);
    });
    
    const algoCount = requestsBySymbol['ALGO_USDT']?.length || 0;
    console.log(`\n🔍 ALGO_USDT requests in first 10s: ${algoCount}`);
    
    console.log('\n📋 Cache-related console logs:');
    consoleLogs.filter(log => log.text.includes('Cache') || log.text.includes('getTradingSignals')).forEach(log => {
      console.log(`  [${log.type}] ${log.text}`);
    });
    
  } catch (error) {
    console.error('❌ Error during test:', error);
  } finally {
    await browser.close();
  }
})();



