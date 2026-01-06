const { chromium } = require('./frontend/node_modules/playwright');
const fs = require('fs');
const path = require('path');

(async () => {
  console.log('🔍 Starting Playwright debug session...');
  
  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext();
  const page = await context.newPage();
  
  const consoleLogs = [];
  const networkErrors = [];
  const pendingRequests = new Map();
  const completedRequests = new Set();
  
  // Capture console logs
  page.on('console', msg => {
    const text = msg.text();
    const type = msg.type();
    consoleLogs.push({ type, text, timestamp: Date.now() });
    if (type === 'error') {
      console.log(`[CONSOLE ${type.toUpperCase()}] ${text}`);
    }
  });
  
  // Capture network requests
  page.on('request', request => {
    const url = request.url();
    // Only track API requests
    if (url.includes('/api/') || url.includes('localhost:8002')) {
      pendingRequests.set(url, {
        url,
        method: request.method(),
        startTime: Date.now(),
        headers: request.headers()
      });
      console.log(`[REQUEST START] ${request.method()} ${url}`);
    }
  });
  
  // Capture network responses
  page.on('response', response => {
    const url = response.url();
    // Only track API requests
    if (url.includes('/api/') || url.includes('localhost:8002')) {
      const request = pendingRequests.get(url);
      if (request) {
        request.endTime = Date.now();
        request.duration = request.endTime - request.startTime;
        request.status = response.status();
        completedRequests.add(url);
        pendingRequests.delete(url);
        console.log(`[RESPONSE] ${response.status()} ${url} (${request.duration}ms)`);
      } else {
        // Response without tracked request
        console.log(`[RESPONSE UNTRACKED] ${response.status()} ${url}`);
      }
    }
  });
  
  // Capture network failures
  page.on('requestfailed', request => {
    const url = request.url();
    // Only track API requests
    if (url.includes('/api/') || url.includes('localhost:8002')) {
      networkErrors.push({
        url,
        failureText: request.failure()?.errorText || 'Unknown error',
        timestamp: Date.now()
      });
      pendingRequests.delete(url);
      console.log(`[NETWORK ERROR] ${url}: ${request.failure()?.errorText}`);
    }
  });
  
  try {
    console.log('📱 Navigating to http://localhost:3000...');
    await page.goto('http://localhost:3000', { waitUntil: 'domcontentloaded', timeout: 30000 });
    
    // Wait for first paint
    await page.waitForLoadState('domcontentloaded');
    console.log('✅ Initial DOM loaded');
    
    // Take initial screenshot
    await page.screenshot({ path: 'initial_load.png', fullPage: true });
    console.log('📸 Screenshot: initial_load.png');
    
    // Wait 10 seconds
    console.log('⏳ Waiting 10 seconds...');
    await page.waitForTimeout(10000);
    
    // Check for loading indicators
    const loadingElements = await page.locator('text=/loading|Loading|spinner|Spinner/i').count();
    console.log(`🔍 Found ${loadingElements} loading indicators after 10s`);
    
    await page.screenshot({ path: 'after_10s.png', fullPage: true });
    console.log('📸 Screenshot: after_10s.png');
    
    // Wait another 20 seconds (total 30s)
    console.log('⏳ Waiting 20 more seconds (total 30s)...');
    await page.waitForTimeout(20000);
    
    const loadingElements30s = await page.locator('text=/loading|Loading|spinner|Spinner/i').count();
    console.log(`🔍 Found ${loadingElements30s} loading indicators after 30s`);
    
    await page.screenshot({ path: 'after_30s.png', fullPage: true });
    console.log('📸 Screenshot: after_30s.png');
    
    // Check pending requests
    const stillPending = Array.from(pendingRequests.values());
    const longPending = stillPending.filter(req => (Date.now() - req.startTime) > 15000);
    
    // Summary
    console.log('\n📊 SUMMARY:');
    console.log('='.repeat(60));
    console.log(`Page still loading after 30s: ${loadingElements30s > 0 ? 'YES' : 'NO'}`);
    console.log(`\nConsole Errors (${consoleLogs.filter(l => l.type === 'error').length}):`);
    consoleLogs.filter(l => l.type === 'error').forEach(log => {
      console.log(`  - ${log.text}`);
    });
    console.log(`\nNetwork Errors (${networkErrors.length}):`);
    networkErrors.forEach(err => {
      console.log(`  - ${err.url}: ${err.failureText}`);
    });
    console.log(`\nPending Requests >15s (${longPending.length}):`);
    longPending.forEach(req => {
      console.log(`  - ${req.method} ${req.url} (pending for ${Math.round((Date.now() - req.startTime) / 1000)}s)`);
    });
    console.log(`\nAll Pending Requests (${stillPending.length}):`);
    stillPending.forEach(req => {
      console.log(`  - ${req.method} ${req.url} (pending for ${Math.round((Date.now() - req.startTime) / 1000)}s)`);
    });
    console.log('='.repeat(60));
    
  } catch (error) {
    console.error('❌ Error during test:', error);
  } finally {
    await browser.close();
  }
})();

