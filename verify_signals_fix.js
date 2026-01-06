const { chromium } = require('./frontend/node_modules/playwright');
const fs = require('fs');
const path = require('path');

(async () => {
  console.log('🔍 Verifying signals duplicate fix...');
  
  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext();
  const page = await context.newPage();
  
  const signalsRequests = [];
  const consoleLogs = [];
  
  // Capture all signals requests
  page.on('request', request => {
    const url = request.url();
    if (url.includes('/signals')) {
      const symbol = url.match(/symbol=([^&]+)/)?.[1] || 'unknown';
      signalsRequests.push({
        url,
        symbol,
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
    if (text.includes('signals') || text.includes('ALGO') || text.includes('dedupe') || text.includes('call#')) {
      consoleLogs.push({ type, text, timestamp: Date.now() });
      console.log(`[CONSOLE ${type.toUpperCase()}] ${text}`);
    }
  });
  
  try {
    console.log('📱 Navigating to http://localhost:3000...');
    await page.goto('http://localhost:3000', { waitUntil: 'domcontentloaded', timeout: 30000 });
    
    // Wait for initial load
    await page.waitForTimeout(2000);
    
    // Wait 10 seconds to capture all requests
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
    
    // Get call counts from window
    const callCounts = await page.evaluate(() => {
      return window.__SIGNALS_CALLS__ || {};
    });
    
    const algoRequests = requestsBySymbol['ALGO_USDT'] || [];
    const algoCalls = callCounts['ALGO_USDT'] || 0;
    
    console.log('\n📊 RESULTS:');
    console.log('='.repeat(60));
    console.log(`ALGO_USDT HTTP requests: ${algoRequests.length}`);
    console.log(`ALGO_USDT function calls: ${algoCalls}`);
    console.log(`Status: ${algoRequests.length === 1 ? '✅ FIXED (1 request)' : `⚠️ STILL HAS DUPLICATES (${algoRequests.length} requests)`}`);
    console.log('='.repeat(60));
    
    // Take screenshots
    await page.screenshot({ path: 'net_signals_after.png', fullPage: true });
    console.log('📸 Screenshot: net_signals_after.png');
    
    // Log all signals requests
    console.log('\n📋 All signals requests:');
    Object.entries(requestsBySymbol).forEach(([symbol, reqs]) => {
      console.log(`  ${symbol}: ${reqs.length} request(s)`);
    });
    
  } catch (error) {
    console.error('❌ Error:', error);
  } finally {
    await browser.close();
  }
})();

