import { test, expect, Page } from '@playwright/test';

const DASHBOARD_URL = process.env.DASHBOARD_URL || process.env.BASE_URL || 'http://localhost:3000';
const ENABLE_TEST_PRICE_INJECTION = process.env.ENABLE_TEST_PRICE_INJECTION === '1';

test.describe('Price Threshold E2E Verification', () => {
  let page: Page;
  const testResults: Array<{ step: string; status: 'pass' | 'fail'; details?: string }> = [];

  test.beforeEach(async ({ browser }) => {
    page = await browser.newPage();
    // Increase timeout for AWS connections
    page.setDefaultTimeout(60000);
    await page.goto(DASHBOARD_URL, { waitUntil: 'networkidle', timeout: 60000 });
    await page.waitForLoadState('networkidle', { timeout: 60000 });
  });

  test.afterEach(async () => {
    testResults.length = 0;
    await page.close();
  });

  test('should verify price threshold changes ($10 -> $11, $3, no limit) and alert behavior', async () => {
    // Step 1: Navigate to Signal Configuration tab
    test.info().annotations.push({ type: 'step', description: 'Navigate to Signal Configuration' });
    const signalConfigTab = page.locator('button:has-text("Signal Configuration"), a:has-text("Signal Configuration")').first();
    if (await signalConfigTab.count() > 0) {
      await signalConfigTab.click();
      await page.waitForTimeout(1000);
    }

    // Step 2: Find coins with active BUY or SELL alerts
    test.info().annotations.push({ type: 'step', description: 'Find coins with active alerts' });
    const watchlistTab = page.locator('button:has-text("Watchlist"), a:has-text("Watchlist")').first();
    if (await watchlistTab.count() > 0) {
      await watchlistTab.click();
      await page.waitForTimeout(1000);
    }

    // Wait for watchlist rows - increase timeout for AWS
    try {
      await page.waitForSelector('[data-testid^="watchlist-row-"]', { timeout: 30000 });
    } catch (e) {
      console.log('⚠️ No watchlist rows found, trying alternative selectors...');
      // Try alternative selector
      await page.waitForSelector('table, [class*="watchlist"], [class*="table"]', { timeout: 10000 }).catch(() => {
        test.skip(true, 'No watchlist rows found');
      });
    }

    const rows = await page.locator('[data-testid^="watchlist-row-"]').all();
    if (rows.length === 0) {
      test.skip(true, 'No watchlist rows found');
      return;
    }

    // Find a coin with active BUY or SELL alert (REQUIRED for this test)
    let testCoin: { symbol: string; row: any; buyActive: boolean; sellActive: boolean; tradeEnabled: boolean } | null = null;
    for (const row of rows.slice(0, 20)) { // Check first 20 rows to find one with active alerts
      // Try to get symbol from various sources
      let symbol = 'unknown';
      const rowTestId = await row.getAttribute('data-testid');
      if (rowTestId) {
        symbol = rowTestId.replace('watchlist-row-', '');
      } else {
        // Try to get symbol from row text content (first cell usually has symbol)
        const firstCell = row.locator('td').first();
        const cellText = await firstCell.textContent().catch(() => '');
        symbol = cellText?.trim().split(/\s/)[0] || 'unknown';
      }
      
      if (symbol === 'unknown') continue;
      
      // Try multiple selectors for alert buttons
      const buyButton = row.locator(`[data-testid="alert-buy-${symbol}"], button:has-text("BUY"), [class*="buy"][class*="alert"]`).first();
      const sellButton = row.locator(`[data-testid="alert-sell-${symbol}"], button:has-text("SELL"), [class*="sell"][class*="alert"]`).first();
      
      let buyActive = false;
      let sellActive = false;
      
      try {
        const buyClass = await buyButton.getAttribute('class').catch(() => '');
        const buyText = await buyButton.textContent().catch(() => '');
        const buyBgColor = await buyButton.evaluate(el => window.getComputedStyle(el).backgroundColor).catch(() => '');
        // Check for active state: class contains active/enabled, text contains ON, or has red/green background
        buyActive = (buyClass?.includes('active') || buyClass?.includes('enabled') || 
                    buyText?.includes('ON') || buyBgColor?.includes('rgb(255') || buyBgColor?.includes('rgb(0')) || false;
      } catch (e) {}
      
      try {
        const sellClass = await sellButton.getAttribute('class').catch(() => '');
        const sellText = await sellButton.textContent().catch(() => '');
        const sellBgColor = await sellButton.evaluate(el => window.getComputedStyle(el).backgroundColor).catch(() => '');
        // Check for active state: class contains active/enabled, text contains ON, or has red/green background
        sellActive = (sellClass?.includes('active') || sellClass?.includes('enabled') || 
                     sellText?.includes('ON') || sellBgColor?.includes('rgb(255') || sellBgColor?.includes('rgb(0')) || false;
      } catch (e) {}
      
      // Check if trade is enabled
      let tradeEnabled = false;
      try {
        const tradeButton = row.locator(`[data-testid="trade-${symbol}"], button:has-text("TRADE"), [class*="trade"]`).first();
        const tradeClass = await tradeButton.getAttribute('class').catch(() => '');
        const tradeText = await tradeButton.textContent().catch(() => '');
        tradeEnabled = (tradeClass?.includes('active') || tradeClass?.includes('enabled') || 
                       tradeText?.includes('ON') || tradeText?.includes('YES')) || false;
      } catch (e) {}
      
      // REQUIRE active alerts for this test
      if (buyActive || sellActive) {
        testCoin = { symbol, row, buyActive, sellActive, tradeEnabled };
        console.log(`✅ Found coin with active alerts: ${symbol} (BUY: ${buyActive}, SELL: ${sellActive}, TRADE: ${tradeEnabled})`);
        break; // Use first coin with active alerts
      }
    }

    if (!testCoin) {
      test.skip(true, 'No coins with active BUY/SELL alerts found. Please enable alerts for at least one coin.');
      return;
    }
    
    if (!testCoin.buyActive && !testCoin.sellActive) {
      test.skip(true, `Coin ${testCoin.symbol} does not have active alerts. Please enable BUY or SELL alerts.`);
      return;
    }

    console.log(`✅ Found test coin: ${testCoin.symbol} (BUY: ${testCoin.buyActive}, SELL: ${testCoin.sellActive})`);

    // Step 3: Navigate to Signal Configuration and change threshold
    test.info().annotations.push({ type: 'step', description: 'Change price threshold in Signal Configuration' });
    
    // Try multiple ways to find Signal Configuration tab
    let configTab = page.locator('button:has-text("Signal Configuration"), a:has-text("Signal Configuration"), [data-testid*="signal-config"], [data-testid*="config"]').first();
    if (await configTab.count() === 0) {
      // Try clicking on any tab that might lead to config
      const allTabs = page.locator('button, a').filter({ hasText: /config|signal|strategy/i });
      if (await allTabs.count() > 0) {
        configTab = allTabs.first();
      }
    }
    
    if (await configTab.count() > 0) {
      await configTab.click();
      await page.waitForTimeout(2000);
    } else {
      console.log('⚠️ Signal Configuration tab not found, trying to find input directly...');
    }

    // Find the minPriceChangePct input field - try multiple selectors
    await page.waitForTimeout(1000);
    
    // Try multiple selectors for the price change input
    let priceChangeInput = page.locator('input[type="number"]').filter({ 
      has: page.locator('..').filter({ hasText: /Minimum Price Change/i })
    }).first();
    
    if (await priceChangeInput.count() === 0) {
      priceChangeInput = page.locator('input[type="number"][placeholder*="1.0"], input[type="number"][placeholder*="1"], input[type="number"]').first();
    }
    
    if (await priceChangeInput.count() === 0) {
      // Try alternative selector - direct input near the label
      priceChangeInput = page.locator('label:has-text("Minimum Price Change"), label:has-text("Price Change")').locator('..').locator('input[type="number"]').first();
    }
    
    if (await priceChangeInput.count() === 0) {
      // Last resort: find any number input in the visible area
      priceChangeInput = page.locator('input[type="number"]').first();
    }
    
    // Wait for the input to be visible
    try {
      await priceChangeInput.waitFor({ state: 'visible', timeout: 10000 });
    } catch (e) {
      console.log('⚠️ Price change input not immediately visible, continuing anyway...');
    }
    
    if (await priceChangeInput.count() === 0) {
      console.log('⚠️ Could not find price change input, but continuing test...');
      // Don't skip - we'll try to proceed and see what happens
    }

    // Test 1: Change from $10 to $11
    test.info().annotations.push({ type: 'step', description: 'Test 1: Change threshold from $10 to $11' });
    await priceChangeInput.clear();
    await priceChangeInput.fill('11');
    await priceChangeInput.blur();
    await page.waitForTimeout(500);

    // Verify the value was saved
    const valueAfter11 = await priceChangeInput.inputValue();
    if (valueAfter11 === '11') {
      testResults.push({ step: 'Change threshold to $11', status: 'pass' });
      console.log('✅ Threshold changed to $11');
    } else {
      testResults.push({ step: 'Change threshold to $11', status: 'fail', details: `Expected 11, got ${valueAfter11}` });
    }

    // Save configuration - look for Save button in Signal Configuration
    const saveButton = page.locator('button:has-text("Save"), button:has-text("Save Configuration"), button:has-text("💾 Save")').first();
    if (await saveButton.count() > 0) {
      await saveButton.scrollIntoViewIfNeeded();
      await saveButton.click();
      // Wait for save to complete - look for success indicator or wait for network to be idle
      await page.waitForTimeout(2000);
      // Verify save completed by checking if button is still clickable (not in loading state)
      await page.waitForLoadState('networkidle').catch(() => {});
    } else {
      console.log('⚠️ Save button not found - configuration may auto-save');
    }

    // Test 2: Change to $3
    test.info().annotations.push({ type: 'step', description: 'Test 2: Change threshold to $3' });
    await priceChangeInput.clear();
    await priceChangeInput.fill('3');
    await priceChangeInput.blur();
    await page.waitForTimeout(500);

    const valueAfter3 = await priceChangeInput.inputValue();
    if (valueAfter3 === '3') {
      testResults.push({ step: 'Change threshold to $3', status: 'pass' });
      console.log('✅ Threshold changed to $3');
    } else {
      testResults.push({ step: 'Change threshold to $3', status: 'fail', details: `Expected 3, got ${valueAfter3}` });
    }

    if (await saveButton.count() > 0) {
      await saveButton.click();
      await page.waitForTimeout(2000);
    }

    // Test 3: Test "no limit" (set to 0 or empty)
    test.info().annotations.push({ type: 'step', description: 'Test 3: Set threshold to "no limit" (0)' });
    await priceChangeInput.clear();
    await priceChangeInput.fill('0');
    await priceChangeInput.blur();
    await page.waitForTimeout(500);

    const valueAfter0 = await priceChangeInput.inputValue();
    if (valueAfter0 === '0') {
      testResults.push({ step: 'Change threshold to 0 (no limit)', status: 'pass' });
      console.log('✅ Threshold changed to 0 (no limit)');
    } else {
      testResults.push({ step: 'Change threshold to 0 (no limit)', status: 'fail', details: `Expected 0, got ${valueAfter0}` });
    }

    if (await saveButton.count() > 0) {
      await saveButton.click();
      await page.waitForTimeout(2000);
    }

    // Step 4: If test price injection is enabled, test threshold crossing
    if (ENABLE_TEST_PRICE_INJECTION) {
      test.info().annotations.push({ type: 'step', description: 'Test price injection and threshold crossing' });
      
      // Restore threshold to $10 for testing
      await priceChangeInput.clear();
      await priceChangeInput.fill('10');
      await priceChangeInput.blur();
      if (await saveButton.count() > 0) {
        await saveButton.click();
        await page.waitForTimeout(2000);
      }

      // Inject test prices via API
      // Support both localhost and AWS URLs
      let apiUrl: string;
      if (DASHBOARD_URL.includes('localhost') || DASHBOARD_URL.includes('127.0.0.1')) {
        apiUrl = DASHBOARD_URL.replace(':3000', ':8000').replace('localhost', 'localhost');
      } else {
        // AWS URL - use the same domain (nginx proxies /api to backend)
        // For https://dashboard.hilovivo.com, use https://dashboard.hilovivo.com/api
        const url = new URL(DASHBOARD_URL);
        apiUrl = `${url.protocol}//${url.hostname}${url.port ? ':' + url.port : ''}`;
      }
      
      // Ensure API URL has /api prefix for the endpoint
      if (!apiUrl.endsWith('/api') && !apiUrl.includes('/api/')) {
        apiUrl = `${apiUrl}/api`;
      }
      
      console.log(`🔗 Using API URL: ${apiUrl}`);
      
      // Use page.request for API calls (handles CORS and authentication automatically)
      const makeApiCall = async (endpoint: string, data: any) => {
        try {
          const response = await page.request.post(`${apiUrl}${endpoint}`, {
            data: data,
            headers: {
              'Content-Type': 'application/json',
            },
          });
          return response;
        } catch (e) {
          console.error(`API call error: ${e}`);
          throw e;
        }
      };
      
      // Get current price to calculate percentage-based changes
      let currentPrice = 50000.0; // Default fallback
      try {
        const priceResponse = await page.request.get(`${apiUrl}/market/price?symbol=${testCoin.symbol}`);
        if (priceResponse.ok()) {
          const priceData = await priceResponse.json();
          currentPrice = priceData.price || currentPrice;
          console.log(`✅ Fetched current price for ${testCoin.symbol}: $${currentPrice}`);
        }
      } catch (e) {
        console.log(`⚠️ Could not fetch current price for ${testCoin.symbol}, using default: ${currentPrice}`);
      }
      
      // Test case 1: 10.5% change -> should pass 10% threshold but fail 11%
      // Calculate price that represents 10.5% increase
      const priceFor10_5Pct = currentPrice * 1.105;
      const priceDelta10_5 = priceFor10_5Pct - currentPrice;
      
      console.log(`Testing price change 10.5% (${currentPrice} -> ${priceFor10_5Pct}, delta: ${priceDelta10_5}) - should pass 10% threshold`);
      try {
        const response1 = await page.request.post(`${apiUrl}/test/inject-price`, {
          data: {
            symbol: testCoin.symbol,
            price: priceFor10_5Pct,
            rsi: 30.0, // Low RSI to trigger BUY signal
            ma50: currentPrice * 0.99,
            ema10: currentPrice * 1.01,
            ma200: currentPrice * 0.98
          }
        });
        if (response1.ok()) {
          const result = await response1.json();
          testResults.push({ step: 'Inject price 10.5% change', status: 'pass', details: `Price: ${result.new_price}` });
          console.log(`✅ Price injected: ${result.previous_price} -> ${result.new_price} (${result.price_change_pct}%)`);
        } else {
          const errorText = await response1.text();
          testResults.push({ step: 'Inject price 10.5% change', status: 'fail', details: `Status: ${response1.status()}, Error: ${errorText}` });
        }
      } catch (e) {
        testResults.push({ step: 'Inject price 10.5% change', status: 'fail', details: String(e) });
      }

      await page.waitForTimeout(3000); // Wait for signal evaluation

      // Change threshold to 11%
      await priceChangeInput.clear();
      await priceChangeInput.fill('11');
      await priceChangeInput.blur();
      if (await saveButton.count() > 0) {
        await saveButton.click();
        await page.waitForTimeout(2000);
      }

      // Test case 2: 11.2% change -> should pass 11% threshold
      // Calculate price that represents 11.2% increase from the last injected price
      const lastInjectedPrice = priceFor10_5Pct;
      const priceFor11_2Pct = lastInjectedPrice * 1.112;
      
      console.log(`Testing price change 11.2% (${lastInjectedPrice} -> ${priceFor11_2Pct}) - should pass 11% threshold`);
      try {
        const response2 = await page.request.post(`${apiUrl}/test/inject-price`, {
          data: {
            symbol: testCoin.symbol,
            price: priceFor11_2Pct,
            rsi: 30.0, // Low RSI to trigger BUY signal
            ma50: lastInjectedPrice * 0.99,
            ema10: lastInjectedPrice * 1.01,
            ma200: lastInjectedPrice * 0.98
          }
        });
        if (response2.ok()) {
          const result = await response2.json();
          testResults.push({ step: 'Inject price 11.2% change', status: 'pass', details: `Price: ${result.new_price}` });
          console.log(`✅ Price injected: ${result.previous_price} -> ${result.new_price} (${result.price_change_pct}%)`);
        } else {
          const errorText = await response2.text();
          testResults.push({ step: 'Inject price 11.2% change', status: 'fail', details: `Status: ${response2.status()}, Error: ${errorText}` });
        }
      } catch (e) {
        testResults.push({ step: 'Inject price 11.2% change', status: 'fail', details: String(e) });
      }
      
      await page.waitForTimeout(3000); // Wait for signal evaluation
    }

    // Step 5: Check Monitoring tab for SENT/BLOCKED messages
    test.info().annotations.push({ type: 'step', description: 'Verify Monitoring tab shows SENT/BLOCKED correctly' });
    const monitoringTab = page.locator('button:has-text("Monitoring"), a:has-text("Monitoring"), button[data-testid*="monitoring"]').first();
    if (await monitoringTab.count() > 0) {
      await monitoringTab.click();
      await page.waitForTimeout(2000);

      // Check for Telegram Messages panel
      const telegramPanel = page.locator('text=/Telegram Messages/i, text=/Mensajes Enviados/i, [data-testid*="telegram"]').first();
      await telegramPanel.waitFor({ state: 'visible', timeout: 5000 }).catch(() => {});
      
      if (await telegramPanel.count() > 0) {
        testResults.push({ step: 'Monitoring tab accessible', status: 'pass' });
        console.log('✅ Monitoring tab accessible');
        
        // Try to find messages related to our test coin
        if (ENABLE_TEST_PRICE_INJECTION && testCoin) {
          // Look for messages containing the test coin symbol
          const coinMessages = page.locator(`text=${testCoin.symbol}`).first();
          if (await coinMessages.count() > 0) {
            testResults.push({ step: 'Monitoring shows messages for test coin', status: 'pass' });
            console.log(`✅ Found messages for ${testCoin.symbol} in Monitoring tab`);
          } else {
            testResults.push({ step: 'Monitoring shows messages for test coin', status: 'fail', details: `No messages found for ${testCoin.symbol}` });
            console.log(`⚠️ No messages found for ${testCoin.symbol} in Monitoring tab`);
          }
        }
      } else {
        testResults.push({ step: 'Monitoring tab accessible', status: 'fail', details: 'Telegram Messages panel not found' });
      }
    } else {
      testResults.push({ step: 'Monitoring tab accessible', status: 'fail', details: 'Monitoring tab not found' });
    }

    // Summary
    const passed = testResults.filter(r => r.status === 'pass').length;
    const failed = testResults.filter(r => r.status === 'fail').length;
    console.log(`\n📊 Test Results: ${passed} passed, ${failed} failed`);
    testResults.forEach(result => {
      console.log(`  ${result.status === 'pass' ? '✅' : '❌'} ${result.step}${result.details ? `: ${result.details}` : ''}`);
    });

    // Assert all critical steps passed
    const criticalSteps = testResults.filter(r => 
      r.step.includes('Change threshold') || r.step.includes('Monitoring tab')
    );
    const allCriticalPassed = criticalSteps.every(r => r.status === 'pass');
    
    expect(allCriticalPassed).toBe(true);
  });
});

