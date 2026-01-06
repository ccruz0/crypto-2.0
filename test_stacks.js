const { chromium } = require('./frontend/node_modules/playwright');

(async () => {
  const browser = await chromium.launch({ headless: false });
  const page = await browser.newPage();
  
  const signalsRequests = [];
  page.on('request', request => {
    const url = request.url();
    if (url.includes('/signals')) {
      const symbol = url.match(/symbol=([^&]+)/)?.[1] || 'unknown';
      signalsRequests.push({ symbol, url, timestamp: Date.now() });
    }
  });
  
  try {
    await page.goto('http://localhost:3000', { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(10000);
    
    // Get stacks from window
    const stacks = await page.evaluate(() => {
      return (window as any).__SIGNALS_HTTP__ || [];
    });
    
    console.log('\n📊 SIGNALS REQUESTS:');
    const bySymbol = {};
    signalsRequests.forEach(req => {
      if (!bySymbol[req.symbol]) bySymbol[req.symbol] = [];
      bySymbol[req.symbol].push(req);
    });
    Object.entries(bySymbol).forEach(([symbol, reqs]) => {
      console.log(`${symbol}: ${reqs.length} request(s)`);
    });
    
    console.log('\n📋 STACKS FOR ALGO_USDT:');
    const algoStacks = stacks.filter(s => s.symbol === 'ALGO_USDT');
    algoStacks.forEach((entry, idx) => {
      console.log(`\n[${idx + 1}] rid=${entry.rid} t=${entry.t}`);
      const lines = entry.stack.split('\n').slice(0, 12);
      console.log(lines.join('\n'));
    });
    
  } catch (error) {
    console.error('Error:', error);
  } finally {
    await browser.close();
  }
})();
