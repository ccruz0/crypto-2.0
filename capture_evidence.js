const { chromium } = require('./frontend/node_modules/playwright');

(async () => {
  console.log('🔍 Capturing evidence for duplicate signals requests...');
  
  const browser = await chromium.launch({ headless: false });
  const page = await browser.newPage();
  
  const signalsRequests = [];
  
  // Capture all signals requests
  page.on('request', request => {
    const url = request.url();
    if (url.includes('/signals')) {
      const symbol = url.match(/symbol=([^&]+)/)?.[1] || 'unknown';
      signalsRequests.push({ symbol, url, timestamp: Date.now() });
    }
  });
  
  try {
    console.log('📱 Navigating to http://localhost:3000...');
    await page.goto('http://localhost:3000', { waitUntil: 'networkidle', timeout: 60000 });
    
    console.log('⏳ Waiting 15 seconds for all requests...');
    await page.waitForTimeout(15000);
    
    // Get stacks from window
    const stacks = await page.evaluate(() => {
      const all = window.__SIGNALS_HTTP__ || [];
      return {
        all: all,
        algo: all.filter(x => x.symbol === 'ALGO_USDT')
      };
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
    
    console.log('\n📋 ALGO_USDT STACKS:');
    console.log(JSON.stringify(stacks.algo, null, 2));
    
    if (stacks.algo.length > 0) {
      console.log('\n📋 FIRST TWO STACKS FOR ALGO_USDT:');
      stacks.algo.slice(0, 2).forEach((entry, idx) => {
        console.log(`\n[${idx + 1}] rid=${entry.rid} t=${entry.t}`);
        const lines = entry.stack.split('\n').slice(0, 12);
        console.log(lines.join('\n'));
      });
    }
    
    // Take screenshot
    await page.screenshot({ path: 'evidence_network.png', fullPage: true });
    console.log('\n📸 Screenshot saved: evidence_network.png');
    
  } catch (error) {
    console.error('❌ Error:', error);
  } finally {
    await browser.close();
  }
})();

