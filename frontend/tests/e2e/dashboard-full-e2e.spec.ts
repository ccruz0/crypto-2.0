import { test, expect, Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

/**
 * Watchlist & Alert Buttons E2E Auditor
 * 
 * This test suite is a reliable auditor that will fail CI if:
 * - Alert buttons don't persist after reload
 * - Alert toggles change state unexpectedly after 10-20s wait
 * - Any 4xx/5xx request occurs on /api/dashboard/symbol/*
 * - Watchlist or alert buttons regress
 */

const DASHBOARD_URL = process.env.DASHBOARD_URL || process.env.DASHBOARD_BASE_URL || 'http://localhost:3000';
const API_URL = process.env.API_URL || (DASHBOARD_URL.includes('localhost') ? 'http://localhost:8002/api' : 'https://dashboard.hilovivo.com/api');

// Artifacts directory for debugging
const ARTIFACTS_DIR = path.join(__dirname, '../../test-results/e2e-artifacts');
if (!fs.existsSync(ARTIFACTS_DIR)) {
  fs.mkdirSync(ARTIFACTS_DIR, { recursive: true });
}

interface NetworkRequest {
  url: string;
  method: string;
  status: number;
  timestamp: number;
  responseBody?: string;
}

interface ConsoleMessage {
  type: string;
  text: string;
  timestamp: number;
}

interface AlertButtonState {
  symbol: string;
  master: boolean;
  buy: boolean;
  sell: boolean;
  timestamp: number;
}

test.describe('Watchlist & Alert Buttons E2E Auditor', () => {
  let page: Page;
  const networkRequests: NetworkRequest[] = [];
  const consoleMessages: ConsoleMessage[] = [];
  const criticalErrors: string[] = [];
  let testSymbol: string | null = null;

  test.beforeEach(async ({ page: testPage }) => {
    page = testPage;
    test.setTimeout(120000); // 2 minutes for e2e tests
    
    // Clear previous data
    networkRequests.length = 0;
    consoleMessages.length = 0;
    criticalErrors.length = 0;
    testSymbol = null;

    // Capture all network requests
    page.on('response', async (response) => {
      const url = response.url();
      const status = response.status();
      const method = response.request().method();
      
      networkRequests.push({
        url,
        method,
        status,
        timestamp: Date.now(),
      });

      // CRITICAL: Fail if any 4xx/5xx on /api/dashboard/symbol/*
      if (url.includes('/api/dashboard/symbol/') && status >= 400) {
        const errorMsg = `CRITICAL: ${status} ${method} ${url}`;
        criticalErrors.push(errorMsg);
        console.error(`❌ ${errorMsg}`);
      }
    });

    // Capture all console messages
    page.on('console', (msg) => {
      const text = msg.text();
      const type = msg.type();
      
      consoleMessages.push({
        type,
        text,
        timestamp: Date.now(),
      });

      // Fail on TDZ errors
      if (type === 'error' && text.includes('Cannot access') && text.includes('before initialization')) {
        criticalErrors.push(`TDZ Error: ${text}`);
      }
    });

    // Navigate to dashboard
    await page.goto(DASHBOARD_URL, { waitUntil: 'networkidle', timeout: 30000 });
    
    // Wait for dashboard to load
    await page.waitForSelector('h1:has-text("Trading Dashboard")', { timeout: 15000 });
    
    // Navigate to Watchlist tab
    await page.click('button:has-text("Watchlist")');
    await page.waitForTimeout(2000);
    
    // Wait for watchlist to load
    await page.waitForSelector('table, tr', { timeout: 10000 }).catch(() => {});
  });

  test.afterEach(async ({ }, testInfo) => {
    // Save artifacts on failure
    if (testInfo.status !== 'passed') {
      const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
      const testName = testInfo.title.replace(/[^a-zA-Z0-9]/g, '_');
      
      // Save console logs
      const consoleLogPath = path.join(ARTIFACTS_DIR, `${testName}-console-${timestamp}.json`);
      fs.writeFileSync(consoleLogPath, JSON.stringify(consoleMessages, null, 2));
      
      // Save network requests
      const networkLogPath = path.join(ARTIFACTS_DIR, `${testName}-network-${timestamp}.json`);
      fs.writeFileSync(networkLogPath, JSON.stringify(networkRequests, null, 2));
      
      // Save screenshot
      const screenshotPath = path.join(ARTIFACTS_DIR, `${testName}-screenshot-${timestamp}.png`);
      await page.screenshot({ path: screenshotPath, fullPage: true });
      
      console.log(`\n📦 Artifacts saved:`);
      console.log(`  - Console: ${consoleLogPath}`);
      console.log(`  - Network: ${networkLogPath}`);
      console.log(`  - Screenshot: ${screenshotPath}`);
    }

    // Fail if critical errors occurred
    if (criticalErrors.length > 0) {
      throw new Error(`Critical errors detected:\n${criticalErrors.join('\n')}`);
    }
  });

  /**
   * Find a test symbol (prefer BTC_USDT, fallback to first available)
   */
  async function findTestSymbol(): Promise<string> {
    // Try to find BTC_USDT or BTC_USD first
    const btcRow = page.locator('tr').filter({ hasText: /BTC_(USDT|USD)/i }).first();
    if (await btcRow.count() > 0) {
      const rowText = await btcRow.textContent();
      const match = rowText?.match(/BTC_(USDT|USD)/i);
      if (match) {
        return match[0].toUpperCase();
      }
    }

    // Fallback to ETH_USDT
    const ethRow = page.locator('tr').filter({ hasText: /ETH_(USDT|USD)/i }).first();
    if (await ethRow.count() > 0) {
      const rowText = await ethRow.textContent();
      const match = rowText?.match(/ETH_(USDT|USD)/i);
      if (match) {
        return match[0].toUpperCase();
      }
    }

    // Fallback to first row with alert buttons
    const allRows = await page.locator('tr').all();
    for (const row of allRows) {
      const buyButton = row.locator('button[data-testid*="alert-buy"]').first();
      if (await buyButton.count() > 0) {
        const rowText = await row.textContent();
        const match = rowText?.match(/([A-Z]+_(USDT|USD))/i);
        if (match) {
          return match[1].toUpperCase();
        }
      }
    }

    throw new Error('No test symbol found with alert buttons');
  }

  /**
   * Get current alert button states for a symbol
   */
  async function getAlertButtonState(symbol: string): Promise<AlertButtonState> {
    const row = page.locator('tr').filter({ hasText: new RegExp(symbol, 'i') }).first();
    
    if (await row.count() === 0) {
      throw new Error(`Row not found for symbol: ${symbol}`);
    }

    // Get master alert button state
    const masterButton = row.locator(`button[data-testid*="alert-master"]`).first();
    const masterText = await masterButton.textContent().catch(() => '');
    const masterEnabled = masterText?.includes('✅') || false;

    // Get BUY button state
    const buyButton = row.locator(`button[data-testid*="alert-buy"]`).first();
    const buyText = await buyButton.textContent().catch(() => '');
    const buyEnabled = buyText?.includes('✅') || false;

    // Get SELL button state
    const sellButton = row.locator(`button[data-testid*="alert-sell"]`).first();
    const sellText = await sellButton.textContent().catch(() => '');
    const sellEnabled = sellText?.includes('✅') || false;

    return {
      symbol,
      master: masterEnabled,
      buy: buyEnabled,
      sell: sellEnabled,
      timestamp: Date.now(),
    };
  }

  /**
   * Click an alert button and wait for state to update
   */
  async function clickAlertButton(symbol: string, type: 'master' | 'buy' | 'sell'): Promise<void> {
    const row = page.locator('tr').filter({ hasText: new RegExp(symbol, 'i') }).first();
    
    let button;
    switch (type) {
      case 'master':
        button = row.locator(`button[data-testid*="alert-master"]`).first();
        break;
      case 'buy':
        button = row.locator(`button[data-testid*="alert-buy"]`).first();
        break;
      case 'sell':
        button = row.locator(`button[data-testid*="alert-sell"]`).first();
        break;
    }

    if (await button.count() === 0) {
      throw new Error(`Button not found: ${type} for ${symbol}`);
    }

    await button.click();
    
    // Wait for API call and state update
    await page.waitForTimeout(2000);
    
    // Wait for "Saved" message if present
    const savedMessage = row.locator('text=/Saved/i').first();
    if (await savedMessage.count() > 0) {
      await page.waitForTimeout(500);
    }
  }

  test('should find and interact with alert buttons', async () => {
    testSymbol = await findTestSymbol();
    console.log(`✅ Using test symbol: ${testSymbol}`);

    const initialState = await getAlertButtonState(testSymbol);
    console.log(`📊 Initial state:`, initialState);

    // Verify all buttons exist
    const row = page.locator('tr').filter({ hasText: new RegExp(testSymbol, 'i') }).first();
    const masterButton = row.locator(`button[data-testid*="alert-master"]`).first();
    const buyButton = row.locator(`button[data-testid*="alert-buy"]`).first();
    const sellButton = row.locator(`button[data-testid*="alert-sell"]`).first();

    expect(await masterButton.count()).toBeGreaterThan(0);
    expect(await buyButton.count()).toBeGreaterThan(0);
    expect(await sellButton.count()).toBeGreaterThan(0);
  });

  test('should toggle alert buttons and verify state changes', async () => {
    testSymbol = await findTestSymbol();
    console.log(`✅ Using test symbol: ${testSymbol}`);

    // Get initial state
    const initialState = await getAlertButtonState(testSymbol);
    console.log(`📊 Initial state:`, initialState);

    // Toggle BUY button
    await clickAlertButton(testSymbol, 'buy');
    const afterBuyToggle = await getAlertButtonState(testSymbol);
    expect(afterBuyToggle.buy).not.toBe(initialState.buy);
    console.log(`✅ BUY toggled: ${initialState.buy} -> ${afterBuyToggle.buy}`);

    // Toggle SELL button
    await clickAlertButton(testSymbol, 'sell');
    const afterSellToggle = await getAlertButtonState(testSymbol);
    expect(afterSellToggle.sell).not.toBe(initialState.sell);
    console.log(`✅ SELL toggled: ${initialState.sell} -> ${afterSellToggle.sell}`);

    // Toggle master button
    await clickAlertButton(testSymbol, 'master');
    const afterMasterToggle = await getAlertButtonState(testSymbol);
    expect(afterMasterToggle.master).not.toBe(initialState.master);
    console.log(`✅ Master toggled: ${initialState.master} -> ${afterMasterToggle.master}`);

    // Verify no 4xx/5xx errors on /api/dashboard/symbol/*
    const symbolApiErrors = networkRequests.filter(req => 
      req.url.includes('/api/dashboard/symbol/') && req.status >= 400
    );
    
    if (symbolApiErrors.length > 0) {
      throw new Error(`API errors on /api/dashboard/symbol/*:\n${JSON.stringify(symbolApiErrors, null, 2)}`);
    }
  });

  test('should persist alert button states after page reload', async () => {
    testSymbol = await findTestSymbol();
    console.log(`✅ Using test symbol: ${testSymbol}`);

    // Get initial state
    const initialState = await getAlertButtonState(testSymbol);
    console.log(`📊 Initial state:`, initialState);

    // Toggle all buttons to a known state (all ON)
    if (!initialState.buy) {
      await clickAlertButton(testSymbol, 'buy');
    }
    if (!initialState.sell) {
      await clickAlertButton(testSymbol, 'sell');
    }
    if (!initialState.master) {
      await clickAlertButton(testSymbol, 'master');
    }

    // Verify all are ON
    const afterToggle = await getAlertButtonState(testSymbol);
    expect(afterToggle.buy).toBe(true);
    expect(afterToggle.sell).toBe(true);
    expect(afterToggle.master).toBe(true);
    console.log(`✅ All toggles set to ON:`, afterToggle);

    // Reload page
    await page.reload({ waitUntil: 'networkidle' });
    await page.waitForSelector('h1:has-text("Trading Dashboard")', { timeout: 15000 });
    await page.click('button:has-text("Watchlist")');
    await page.waitForTimeout(3000);

    // Find the same symbol again
    const rowAfterReload = page.locator('tr').filter({ hasText: new RegExp(testSymbol, 'i') }).first();
    await expect(rowAfterReload).toBeVisible({ timeout: 10000 });

    // Verify state persisted
    const afterReload = await getAlertButtonState(testSymbol);
    console.log(`📊 After reload:`, afterReload);

    // CRITICAL: State must persist (or be synced from backend correctly)
    // Allow for backend sync, but buttons should not be in initial state
    expect(afterReload.buy).toBe(true);
    expect(afterReload.sell).toBe(true);
    expect(afterReload.master).toBe(true);
  });

  test('should not change alert button states unexpectedly after wait period', async () => {
    testSymbol = await findTestSymbol();
    console.log(`✅ Using test symbol: ${testSymbol}`);

    // Set all buttons to ON
    const initialState = await getAlertButtonState(testSymbol);
    
    if (!initialState.buy) {
      await clickAlertButton(testSymbol, 'buy');
    }
    if (!initialState.sell) {
      await clickAlertButton(testSymbol, 'sell');
    }
    if (!initialState.master) {
      await clickAlertButton(testSymbol, 'master');
    }

    // Verify all are ON
    const afterSet = await getAlertButtonState(testSymbol);
    expect(afterSet.buy).toBe(true);
    expect(afterSet.sell).toBe(true);
    expect(afterSet.master).toBe(true);
    console.log(`✅ All toggles set to ON:`, afterSet);

    // Wait 15 seconds (simulating refresh loops)
    console.log(`⏳ Waiting 15 seconds to check for unexpected state changes...`);
    await page.waitForTimeout(15000);

    // Check state again
    const afterWait = await getAlertButtonState(testSymbol);
    console.log(`📊 After 15s wait:`, afterWait);

    // CRITICAL: State should not have changed unexpectedly
    // Allow for backend sync, but if backend says ON, it should stay ON
    if (afterSet.buy && !afterWait.buy) {
      throw new Error(`BUY button unexpectedly changed from ON to OFF after wait period`);
    }
    if (afterSet.sell && !afterWait.sell) {
      throw new Error(`SELL button unexpectedly changed from ON to OFF after wait period`);
    }
    if (afterSet.master && !afterWait.master) {
      throw new Error(`Master button unexpectedly changed from ON to OFF after wait period`);
    }
  });

  test('should handle all alert button interactions without errors', async () => {
    testSymbol = await findTestSymbol();
    console.log(`✅ Using test symbol: ${testSymbol}`);

    // Get initial state
    const initialState = await getAlertButtonState(testSymbol);

    // Toggle each button multiple times
    for (let i = 0; i < 2; i++) {
      await clickAlertButton(testSymbol, 'buy');
      await page.waitForTimeout(1000);
      
      await clickAlertButton(testSymbol, 'sell');
      await page.waitForTimeout(1000);
      
      await clickAlertButton(testSymbol, 'master');
      await page.waitForTimeout(1000);
    }

    // Verify no critical errors
    const symbolApiErrors = networkRequests.filter(req => 
      req.url.includes('/api/dashboard/symbol/') && req.status >= 400
    );

    if (symbolApiErrors.length > 0) {
      throw new Error(`API errors during interactions:\n${JSON.stringify(symbolApiErrors, null, 2)}`);
    }

    // Verify no console errors related to alerts
    const alertErrors = consoleMessages.filter(msg => 
      msg.type === 'error' && (
        msg.text.includes('alert') ||
        msg.text.includes('405') ||
        msg.text.includes('Method Not Allowed')
      )
    );

    if (alertErrors.length > 0) {
      console.warn('⚠️ Console errors related to alerts:', alertErrors);
      // Don't fail for console errors, but log them
    }
  });

  test('should verify no TDZ errors occur', async () => {
    // Navigate through all tabs to trigger all useMemo hooks
    const tabs = ['Portfolio', 'Watchlist', 'Open Orders', 'Monitoring'];
    
    for (const tab of tabs) {
      await page.click(`button:has-text("${tab}")`);
      await page.waitForTimeout(1000);
    }

    // Check for TDZ errors
    const tdzErrors = consoleMessages.filter(msg => 
      msg.type === 'error' && 
      msg.text.includes('Cannot access') && 
      msg.text.includes('before initialization')
    );

    if (tdzErrors.length > 0) {
      throw new Error(`TDZ errors detected:\n${tdzErrors.map(e => e.text).join('\n')}`);
    }
  });

  test('should verify watchlist renders correctly', async () => {
    // Verify watchlist table is visible
    const watchlistTable = page.locator('table').first();
    await expect(watchlistTable).toBeVisible({ timeout: 10000 });

    // Verify at least one row exists (or empty state message)
    const rows = await page.locator('tr').count();
    const emptyMessage = page.locator('text=/no.*watchlist|empty/i').first();
    
    if (rows === 0 && (await emptyMessage.count()) === 0) {
      throw new Error('Watchlist table is empty and no empty state message found');
    }
  });
});
