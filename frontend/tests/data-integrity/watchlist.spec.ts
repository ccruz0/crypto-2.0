import { test, expect, Page } from '@playwright/test';
import { normalizeBoolean, normalizeSymbol, normalizeStatus } from './helpers/normalization';
import { writeDiscrepancyReport, Discrepancy, ApiCapture } from './helpers/reporting';
import { extractSymbolFromRow, getToggleState, waitForTabLoad } from './helpers/ui-capture';

const BASE_URL = process.env.BASE_URL || process.env.DASHBOARD_URL || 'http://localhost:3000';

interface WatchlistApiItem {
  id?: number;
  symbol: string;
  trade_enabled?: boolean | string | number;
  alert_enabled?: boolean | string | number;
  buy_alert_enabled?: boolean | string | number;
  sell_alert_enabled?: boolean | string | number;
  instrument_name?: string;
  [key: string]: unknown;
}

interface WatchlistUIRow {
  symbol: string;
  tradeEnabled: boolean | null;
  buyAlertEnabled: boolean | null;
  sellAlertEnabled: boolean | null;
  masterAlertEnabled: boolean | null;
}

test.describe('Watchlist Data Integrity', () => {
  let page: Page;
  let apiCapture: ApiCapture;
  const discrepancies: Discrepancy[] = [];

  test.beforeEach(async ({ page: testPage }) => {
    page = testPage;
    apiCapture = new ApiCapture(page);
    discrepancies.length = 0;
    
    test.setTimeout(60000); // 60 seconds for data integrity tests
    
    // Navigate to dashboard
    await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 30000 });
    
    // Wait for dashboard to load
    await page.waitForSelector('h1:has-text("Trading Dashboard")', { timeout: 15000 }).catch(() => {});
    
    // Navigate to Watchlist tab
    await waitForTabLoad(page, 'watchlist');
    
    // Wait for watchlist table/rows to appear
    await page.waitForSelector('[data-testid^="watchlist-row-"], table, tr', { timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(2000); // Additional wait for data to load
  });

  test.afterEach(async ({ }, testInfo) => {
    // Write discrepancy report if there are any
    if (discrepancies.length > 0) {
      writeDiscrepancyReport('watchlist', discrepancies);
    }
    
    // Take screenshot on failure
    if (testInfo.status !== 'passed') {
      const screenshotPath = `test-results/data-integrity/watchlist-failure-${Date.now()}.png`;
      await page.screenshot({ path: screenshotPath, fullPage: true });
      console.log(`📸 Screenshot saved: ${screenshotPath}`);
    }
  });

  test('should match UI toggle states with backend API data', async () => {
    // Get API snapshot from captured responses
    const apiResponse = apiCapture.getLatestResponse(/\/api\/dashboard[^/]*$/);
    
    if (!apiResponse || !apiResponse.body) {
      console.warn('⚠️ No API response captured for /api/dashboard');
      return;
    }
    
    // Parse API response
    const apiData = Array.isArray(apiResponse.body) ? apiResponse.body : 
                   (apiResponse.body as any)?.items || 
                   (apiResponse.body as any)?.coins || 
                   [];
    
    if (!Array.isArray(apiData)) {
      console.warn('⚠️ API response is not an array');
      return;
    }
    
    // Build API map by symbol
    const apiMap = new Map<string, WatchlistApiItem>();
    for (const item of apiData as WatchlistApiItem[]) {
      const symbol = normalizeSymbol(item.symbol || item.instrument_name || '');
      if (symbol) {
        apiMap.set(symbol, item);
      }
    }
    
    console.log(`📊 API data: ${apiMap.size} symbols`);
    
    // Capture UI state
    const uiRows: WatchlistUIRow[] = [];
    const rowElements = await page.locator('[data-testid^="watchlist-row-"]').all();
    
    console.log(`🖥️  UI rows found: ${rowElements.length}`);
    
    for (const row of rowElements) {
      const symbol = await extractSymbolFromRow(row);
      if (!symbol) continue;
      
      const normalizedSymbol = normalizeSymbol(symbol);
      
      // Get toggle states from UI
      const tradeToggle = row.locator(`[data-testid="trading-toggle-${symbol}"]`).first();
      const buyAlertToggle = row.locator(`[data-testid="toggle-buy-alert-${symbol}"], [data-testid="alert-buy-${symbol}"]`).first();
      const sellAlertToggle = row.locator(`[data-testid="toggle-sell-alert-${symbol}"], [data-testid="alert-sell-${symbol}"]`).first();
      const masterAlertToggle = row.locator(`[data-testid="toggle-alert-master-${symbol}"], [data-testid="alert-master-${symbol}"]`).first();
      
      const tradeEnabled = await getToggleState(tradeToggle).catch(() => null);
      const buyAlertEnabled = await getToggleState(buyAlertToggle).catch(() => null);
      const sellAlertEnabled = await getToggleState(sellAlertToggle).catch(() => null);
      const masterAlertEnabled = await getToggleState(masterAlertToggle).catch(() => null);
      
      uiRows.push({
        symbol: normalizedSymbol,
        tradeEnabled,
        buyAlertEnabled,
        sellAlertEnabled,
        masterAlertEnabled
      });
    }
    
    // Build UI map
    const uiMap = new Map<string, WatchlistUIRow>();
    for (const row of uiRows) {
      uiMap.set(row.symbol, row);
    }
    
    // Compare: Check for missing rows in UI
    for (const [symbol, apiItem] of apiMap.entries()) {
      if (!uiMap.has(symbol)) {
        discrepancies.push({
          tabName: 'watchlist',
          timestamp: new Date().toISOString(),
          symbol,
          field: 'row_missing',
          uiValue: null,
          apiValue: apiItem,
          apiSourceUrl: apiResponse.url
        });
        console.error(`❌ Symbol ${symbol} in API but not in UI`);
      }
    }
    
    // Compare: Check for extra rows in UI (might be filtered, but log for awareness)
    for (const [symbol, uiRow] of uiMap.entries()) {
      if (!apiMap.has(symbol)) {
        console.warn(`⚠️ Symbol ${symbol} in UI but not in API (might be filtered)`);
      }
    }
    
    // Compare toggle states for each symbol
    for (const [symbol, apiItem] of apiMap.entries()) {
      const uiRow = uiMap.get(symbol);
      if (!uiRow) continue;
      
      // Compare trade_enabled
      const apiTradeEnabled = normalizeBoolean(apiItem.trade_enabled);
      if (uiRow.tradeEnabled !== null && apiTradeEnabled !== null && uiRow.tradeEnabled !== apiTradeEnabled) {
        discrepancies.push({
          tabName: 'watchlist',
          timestamp: new Date().toISOString(),
          symbol,
          field: 'trade_enabled',
          uiValue: uiRow.tradeEnabled,
          apiValue: apiItem.trade_enabled,
          apiSourceUrl: apiResponse.url
        });
        console.error(`❌ ${symbol}: trade_enabled mismatch - UI: ${uiRow.tradeEnabled}, API: ${apiItem.trade_enabled}`);
      }
      
      // Compare buy_alert_enabled
      const apiBuyAlertEnabled = normalizeBoolean(apiItem.buy_alert_enabled);
      if (uiRow.buyAlertEnabled !== null && apiBuyAlertEnabled !== null && uiRow.buyAlertEnabled !== apiBuyAlertEnabled) {
        discrepancies.push({
          tabName: 'watchlist',
          timestamp: new Date().toISOString(),
          symbol,
          field: 'buy_alert_enabled',
          uiValue: uiRow.buyAlertEnabled,
          apiValue: apiItem.buy_alert_enabled,
          apiSourceUrl: apiResponse.url
        });
        console.error(`❌ ${symbol}: buy_alert_enabled mismatch - UI: ${uiRow.buyAlertEnabled}, API: ${apiItem.buy_alert_enabled}`);
      }
      
      // Compare sell_alert_enabled
      const apiSellAlertEnabled = normalizeBoolean(apiItem.sell_alert_enabled);
      if (uiRow.sellAlertEnabled !== null && apiSellAlertEnabled !== null && uiRow.sellAlertEnabled !== apiSellAlertEnabled) {
        discrepancies.push({
          tabName: 'watchlist',
          timestamp: new Date().toISOString(),
          symbol,
          field: 'sell_alert_enabled',
          uiValue: uiRow.sellAlertEnabled,
          apiValue: apiItem.sell_alert_enabled,
          apiSourceUrl: apiResponse.url
        });
        console.error(`❌ ${symbol}: sell_alert_enabled mismatch - UI: ${uiRow.sellAlertEnabled}, API: ${apiItem.sell_alert_enabled}`);
      }
      
      // Compare master alert_enabled (should match if buy OR sell is enabled)
      const apiAlertEnabled = normalizeBoolean(apiItem.alert_enabled);
      if (uiRow.masterAlertEnabled !== null && apiAlertEnabled !== null) {
        // Master alert should be true if either buy or sell is enabled
        const expectedMaster = apiBuyAlertEnabled === true || apiSellAlertEnabled === true;
        if (uiRow.masterAlertEnabled !== expectedMaster && uiRow.masterAlertEnabled !== apiAlertEnabled) {
          discrepancies.push({
            tabName: 'watchlist',
            timestamp: new Date().toISOString(),
            symbol,
            field: 'alert_enabled',
            uiValue: uiRow.masterAlertEnabled,
            apiValue: apiItem.alert_enabled,
            apiSourceUrl: apiResponse.url
          });
          console.error(`❌ ${symbol}: alert_enabled mismatch - UI: ${uiRow.masterAlertEnabled}, API: ${apiItem.alert_enabled}`);
        }
      }
    }
    
    // Fail if there are critical discrepancies
    const criticalDiscrepancies = discrepancies.filter(d => 
      d.field === 'row_missing' || 
      d.field === 'trade_enabled' || 
      d.field === 'buy_alert_enabled' || 
      d.field === 'sell_alert_enabled'
    );
    
    if (criticalDiscrepancies.length > 0) {
      throw new Error(`Found ${criticalDiscrepancies.length} critical discrepancies between UI and API. Check discrepancy report.`);
    }
    
    console.log(`✅ Watchlist data integrity check passed for ${uiMap.size} symbols`);
  });
});










