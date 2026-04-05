import { test, expect, Page } from '@playwright/test';

const DASHBOARD_URL = process.env.DASHBOARD_URL || 'https://dashboard.hilovivo.com';

test.describe('Watchlist Alert Buttons', () => {
  let page: Page;
  const alertMessages: string[] = [];
  const errors: Array<{ message: string; symbol?: string }> = [];

  test.beforeEach(async ({ browser }) => {
    page = await browser.newPage();
    
    // Intercept and store all dialog/alert messages
    page.on('dialog', async dialog => {
      const message = dialog.message();
      alertMessages.push(message);
      console.log(`⚠️ Alert dialog detected: ${message}`);
      
      // Check if it's an error
      if (message.includes('Error') || message.includes('502') || message.includes('5') || message.includes('HTTP error')) {
        errors.push({ message });
      }
      
      // Dismiss the dialog
      await dialog.dismiss();
    });

    // Also listen for console errors
    page.on('console', msg => {
      if (msg.type() === 'error') {
        const text = msg.text();
        if (text.includes('502') || text.includes('Error') || text.includes('HTTP error')) {
          errors.push({ message: text });
          console.log(`❌ Console error detected: ${text}`);
        }
      }
    });

    // Navigate to dashboard
    await page.goto(DASHBOARD_URL, { waitUntil: 'networkidle' });
    
    // Wait for the page to be fully loaded
    await page.waitForLoadState('networkidle');
  });

  test.afterEach(async () => {
    // Clear messages and errors between tests
    alertMessages.length = 0;
    errors.length = 0;
    await page.close();
  });

  test('should click all BUY and SELL alert buttons without errors', async () => {
    // Navigate to Watchlist tab
    // Look for the Watchlist tab button - it might be a button or link
    const watchlistTab = page.locator('button:has-text("Watchlist"), a:has-text("Watchlist"), [data-testid="tab-watchlist"]').first();
    
    if (await watchlistTab.count() > 0) {
      await watchlistTab.click();
    } else {
      // Try to find it by looking for tabs/buttons with text containing "Watchlist"
      const allButtons = page.locator('button, a');
      const watchlistText = await allButtons.filter({ hasText: /watchlist/i }).first();
      
      if (await watchlistText.count() > 0) {
        await watchlistText.click();
      } else {
        // Fallback: assume we're already on the watchlist or it's the default view
        console.log('⚠️ Watchlist tab not found, assuming already on watchlist');
      }
    }

    // Wait for watchlist rows to load
    await page.waitForSelector('[data-testid^="watchlist-row-"]', { timeout: 10000 });
    
    // Get all watchlist rows
    const rows = await page.locator('[data-testid^="watchlist-row-"]').all();
    
    console.log(`✅ Found ${rows.length} watchlist rows`);

    if (rows.length === 0) {
      test.skip(true, 'No watchlist rows found - skipping test');
      return;
    }

    // For each row, find and click BUY and SELL alert buttons
    for (const row of rows) {
      // Extract symbol from row's data-testid
      const rowTestId = await row.getAttribute('data-testid');
      const symbol = rowTestId?.replace('watchlist-row-', '') || 'unknown';
      
      console.log(`🔄 Processing row for ${symbol}`);

      // Find BUY alert button
      const buyButton = row.locator(`[data-testid="alert-buy-${symbol}"]`);
      const buyButtonCount = await buyButton.count();
      
      if (buyButtonCount > 0) {
        console.log(`  ↳ Clicking BUY alert button for ${symbol}`);
        await buyButton.click();
        // Small delay to allow for API call
        await page.waitForTimeout(500);
        
        // Check if any errors occurred
        if (errors.length > 0) {
          const recentErrors = errors.filter(e => e.message.includes(symbol) || !e.symbol);
          if (recentErrors.length > 0) {
            throw new Error(`Error after clicking BUY button for ${symbol}: ${recentErrors[recentErrors.length - 1].message}`);
          }
        }
      } else {
        console.log(`  ↳ BUY button not found for ${symbol}`);
      }

      // Find SELL alert button
      const sellButton = row.locator(`[data-testid="alert-sell-${symbol}"]`);
      const sellButtonCount = await sellButton.count();
      
      if (sellButtonCount > 0) {
        console.log(`  ↳ Clicking SELL alert button for ${symbol}`);
        await sellButton.click();
        // Small delay to allow for API call
        await page.waitForTimeout(500);
        
        // Check if any errors occurred
        if (errors.length > 0) {
          const recentErrors = errors.filter(e => e.message.includes(symbol) || !e.symbol);
          if (recentErrors.length > 0) {
            throw new Error(`Error after clicking SELL button for ${symbol}: ${recentErrors[recentErrors.length - 1].message}`);
          }
        }
      } else {
        console.log(`  ↳ SELL button not found for ${symbol}`);
      }
    }

    // Wait a bit more for any delayed errors
    await page.waitForTimeout(1000);

    // Final check: fail test if any error alerts were detected
    const errorAlerts = alertMessages.filter(msg =>
      /error/i.test(msg) ||
      /HTTP error/i.test(msg) ||
      /502/i.test(msg) ||
      /5\d\d/.test(msg) ||
      /timeout/i.test(msg)
    );

    if (errorAlerts.length > 0) {
      throw new Error(`Alert errors detected after clicking all buttons:\n${errorAlerts.join('\n')}`);
    }

    if (errors.length > 0) {
      const errorMessages = errors.map(e => e.message).join('\n');
      throw new Error(`Errors detected after clicking all buttons:\n${errorMessages}`);
    }

    console.log(`✅ Successfully clicked all alert buttons without errors`);
  });
});









