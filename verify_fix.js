const { chromium } = require('./frontend/node_modules/playwright');
const fs = require('fs');
const path = require('path');

(async () => {
  console.log('🔍 Verifying signals duplicate fix...');
  
  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext();
  const page = await context.newPage();
  
  const signalsRequests = [];
  
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
    }
  });
  
  try {
    console.log('📱 Navigating to http://localhost:3000...');
    await page.goto('http://localhost:3000', { waitUntil: 'domcontentloaded', timeout: 30000 });
    
    // Wait for initial load
    await page.waitForTimeout(2000);
    await page.screenshot({ path: 'pw_fixed_initial.png', fullPage: true });
    console.log('📸 Screenshot: pw_fixed_initial.png');
    
    // Wait 10 seconds
    console.log('⏳ Waiting 10 seconds...');
    await page.waitForTimeout(10000);
    await page.screenshot({ path: 'pw_fixed_10s.png', fullPage: true });
    console.log('📸 Screenshot: pw_fixed_10s.png');
    
    // Count requests per symbol
    const requestsBySymbol = {};
    signalsRequests.forEach(req => {
      const symbol = req.symbol;
      if (!requestsBySymbol[symbol]) {
        requestsBySymbol[symbol] = [];
      }
      requestsBySymbol[symbol].push(req);
    });
    
    const algoCount = requestsBySymbol['ALGO_USDT']?.length || 0;
    console.log(`\n📊 ALGO_USDT requests in first 10s: ${algoCount}`);
    console.log(`Status: ${algoCount <= 1 ? '✅ FIXED' : '⚠️ STILL HAS DUPLICATES'}`);
    
  } catch (error) {
    console.error('❌ Error:', error);
  } finally {
    await browser.close();
  }
})();



