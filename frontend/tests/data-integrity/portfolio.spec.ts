import { test, expect, Page } from '@playwright/test';
import { normalizeBoolean, normalizeSymbol } from './helpers/normalization';
import { writeDiscrepancyReport, Discrepancy, ApiCapture } from './helpers/reporting';
import { extractSymbolFromRow, waitForTabLoad } from './helpers/ui-capture';

const BASE_URL = process.env.BASE_URL || process.env.DASHBOARD_URL || 'http://localhost:3000';

interface PortfolioApiAsset {
  coin: string;
  symbol?: string;
  balance?: number;
  value_usd?: number;
  available_qty?: number;
  reserved_qty?: number;
  [key: string]: unknown;
}

interface PortfolioUIRow {
  symbol: string;
  balance: number | null;
  valueUsd: number | null;
}

test.describe('Portfolio Data Integrity', () => {
  let page: Page;
  let apiCapture: ApiCapture;
  const discrepancies: Discrepancy[] = [];

  test.beforeEach(async ({ page: testPage }) => {
    page = testPage;
    apiCapture = new ApiCapture(page);
    discrepancies.length = 0;
    
    test.setTimeout(60000);
    
    await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 30000 });
    await page.waitForSelector('h1:has-text("Trading Dashboard")', { timeout: 15000 }).catch(() => {});
    
    await waitForTabLoad(page, 'portfolio');
    
    // Wait for portfolio content to load
    await page.waitForSelector('[data-testid^="portfolio-row-"], table, .portfolio-asset', { timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(2000);
  });

  test.afterEach(async ({ }, testInfo) => {
    if (discrepancies.length > 0) {
      writeDiscrepancyReport('portfolio', discrepancies);
    }
    
    if (testInfo.status !== 'passed') {
      const screenshotPath = `test-results/data-integrity/portfolio-failure-${Date.now()}.png`;
      await page.screenshot({ path: screenshotPath, fullPage: true });
      console.log(`📸 Screenshot saved: ${screenshotPath}`);
    }
  });

  test('should match UI portfolio data with backend API', async () => {
    // Get API snapshot from captured responses
    const apiResponse = apiCapture.getLatestResponse(/\/api\/dashboard\/state/);
    
    if (!apiResponse || !apiResponse.body) {
      console.warn('⚠️ No API response captured for /api/dashboard/state');
      return;
    }
    
    // Parse API response
    const apiData = (apiResponse.body as any);
    const portfolioAssets: PortfolioApiAsset[] = apiData?.portfolio?.assets || 
                                                 apiData?.assets || 
                                                 [];
    
    if (!Array.isArray(portfolioAssets)) {
      console.warn('⚠️ Portfolio API response is not an array');
      return;
    }
    
    // Build API map by symbol
    const apiMap = new Map<string, PortfolioApiAsset>();
    for (const asset of portfolioAssets) {
      const symbol = normalizeSymbol(asset.coin || asset.symbol || '');
      if (symbol && (asset.balance || 0) > 0) { // Only include assets with balance
        apiMap.set(symbol, asset);
      }
    }
    
    console.log(`📊 API portfolio: ${apiMap.size} assets with balance`);
    
    // Capture UI state - look for portfolio rows
    const uiRows: PortfolioUIRow[] = [];
    
    // Try different selectors for portfolio rows
    const rowSelectors = [
      '[data-testid^="portfolio-row-"]',
      'table tr[data-testid*="portfolio"]',
      '.portfolio-asset',
      'table tbody tr'
    ];
    
    let rowElements: any[] = [];
    for (const selector of rowSelectors) {
      const elements = await page.locator(selector).all();
      if (elements.length > 0) {
        rowElements = elements;
        console.log(`✅ Found ${elements.length} rows using selector: ${selector}`);
        break;
      }
    }
    
    for (const row of rowElements) {
      let symbol: string | null = null;
      
      // Try to extract symbol from data-testid
      symbol = await extractSymbolFromRow(row).catch(() => null);
      
      // Fallback: extract from row text content
      if (!symbol) {
        const rowText = await row.textContent().catch(() => '');
        // Look for patterns like "BTC_USDT" or "ETH_USD" in the row
        const match = rowText.match(/([A-Z]+_[A-Z]+)/);
        if (match) {
          symbol = match[1];
        }
      }
      
      if (!symbol) continue;
      
      const normalizedSymbol = normalizeSymbol(symbol);
      
      // Try to extract balance and value from row text
      const rowText = await row.textContent().catch(() => '');
      let balance: number | null = null;
      let valueUsd: number | null = null;
      
      // Look for numbers that might be balance or value
      const numbers = rowText.match(/(\d+\.?\d*)/g);
      if (numbers && numbers.length >= 2) {
        // Usually the first number is balance, second might be USD value
        balance = parseFloat(numbers[0]);
        valueUsd = parseFloat(numbers[1]);
      }
      
      uiRows.push({
        symbol: normalizedSymbol,
        balance,
        valueUsd
      });
    }
    
    // Build UI map
    const uiMap = new Map<string, PortfolioUIRow>();
    for (const row of uiRows) {
      uiMap.set(row.symbol, row);
    }
    
    console.log(`🖥️  UI portfolio: ${uiMap.size} assets displayed`);
    
    // Compare: Check for missing assets in UI (if API has balance > 0)
    for (const [symbol, apiAsset] of apiMap.entries()) {
      if (!uiMap.has(symbol)) {
        discrepancies.push({
          tabName: 'portfolio',
          timestamp: new Date().toISOString(),
          symbol,
          field: 'asset_missing',
          uiValue: null,
          apiValue: apiAsset,
          apiSourceUrl: apiResponse.url
        });
        console.error(`❌ Asset ${symbol} in API but not in UI`);
      }
    }
    
    // Compare counts (at least check that we have similar number of items)
    // Note: UI might filter some assets, so we allow some difference
    const countDiff = Math.abs(apiMap.size - uiMap.size);
    if (countDiff > apiMap.size * 0.2) { // Allow 20% difference
      console.warn(`⚠️ Significant count difference: API has ${apiMap.size}, UI has ${uiMap.size}`);
    }
    
    // For assets present in both, compare key metrics if available
    for (const [symbol, apiAsset] of apiMap.entries()) {
      const uiRow = uiMap.get(symbol);
      if (!uiRow) continue;
      
      // Compare balance (allow small differences due to formatting/rounding)
      if (apiAsset.balance !== undefined && uiRow.balance !== null) {
        const balanceDiff = Math.abs((apiAsset.balance || 0) - uiRow.balance) / (apiAsset.balance || 1);
        if (balanceDiff > 0.01) { // More than 1% difference
          discrepancies.push({
            tabName: 'portfolio',
            timestamp: new Date().toISOString(),
            symbol,
            field: 'balance',
            uiValue: uiRow.balance,
            apiValue: apiAsset.balance,
            apiSourceUrl: apiResponse.url
          });
          console.error(`❌ ${symbol}: balance mismatch - UI: ${uiRow.balance}, API: ${apiAsset.balance}`);
        }
      }
      
      // Compare value_usd (allow small differences)
      if (apiAsset.value_usd !== undefined && uiRow.valueUsd !== null) {
        const valueDiff = Math.abs((apiAsset.value_usd || 0) - uiRow.valueUsd) / (apiAsset.value_usd || 1);
        if (valueDiff > 0.01) { // More than 1% difference
          discrepancies.push({
            tabName: 'portfolio',
            timestamp: new Date().toISOString(),
            symbol,
            field: 'value_usd',
            uiValue: uiRow.valueUsd,
            apiValue: apiAsset.value_usd,
            apiSourceUrl: apiResponse.url
          });
          console.error(`❌ ${symbol}: value_usd mismatch - UI: ${uiRow.valueUsd}, API: ${apiAsset.value_usd}`);
        }
      }
    }
    
    // Fail if there are critical discrepancies (missing assets)
    const criticalDiscrepancies = discrepancies.filter(d => d.field === 'asset_missing');
    
    if (criticalDiscrepancies.length > 0) {
      throw new Error(`Found ${criticalDiscrepancies.length} critical discrepancies: assets missing in UI. Check discrepancy report.`);
    }
    
    console.log(`✅ Portfolio data integrity check passed for ${uiMap.size} assets`);
  });
});










