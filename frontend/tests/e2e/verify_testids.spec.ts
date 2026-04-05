import { test, expect } from '@playwright/test';

/**
 * Debug script to verify testids exist in deployed UI
 */
test('verify testids in deployed UI', async ({ page }) => {
  const baseURL = process.env.DASHBOARD_URL || process.env.BASE_URL || 'http://localhost:3000';
  
  console.log(`Navigating to ${baseURL}`);
  await page.goto(baseURL, { waitUntil: 'networkidle' });
  await page.waitForTimeout(3000);
  
  // Try multiple ways to navigate to Monitoring
  const monitoringSelectors = [
    'text=/^Monitoring$/i',
    'text=/^Monitor$/i',
    'a[href*="monitoring"]',
    'button:has-text("Monitoring")',
    'button:has-text("Monitor")',
  ];
  
  let navigated = false;
  for (const selector of monitoringSelectors) {
    try {
      const tab = page.locator(selector).first();
      if (await tab.isVisible({ timeout: 2000 })) {
        await tab.click();
        await page.waitForTimeout(2000);
        navigated = true;
        break;
      }
    } catch (e) {
      // Try next selector
    }
  }
  
  // If no tab found, try direct URL
  if (!navigated) {
    await page.goto(`${baseURL}/monitoring`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(3000);
  }
  
  // Wait for any monitoring content to appear
  await page.waitForSelector('h3:has-text("Active Alerts")', { timeout: 30000 });
  await page.waitForTimeout(2000);
  
  // Check if testids exist in DOM (even if not visible yet)
  const testidsInDOM = await page.evaluate(() => {
    const lastUpdated = document.querySelector('[data-testid="monitor-last-updated"]');
    const window = document.querySelector('[data-testid="monitor-window"]');
    return {
      lastUpdated: lastUpdated ? lastUpdated.outerHTML : null,
      window: window ? window.outerHTML : null,
      lastUpdatedText: lastUpdated ? lastUpdated.textContent : null,
      windowText: window ? window.textContent : null,
    };
  });
  
  console.log('\n📋 DOM Verification:');
  console.log('===================');
  console.log('\n[data-testid="monitor-last-updated"]:');
  console.log('  outerHTML:', testidsInDOM.lastUpdated || 'NOT FOUND');
  console.log('  innerText:', testidsInDOM.lastUpdatedText || 'NOT FOUND');
  console.log('\n[data-testid="monitor-window"]:');
  console.log('  outerHTML:', testidsInDOM.window || 'NOT FOUND');
  console.log('  innerText:', testidsInDOM.windowText || 'NOT FOUND');
  
  // Take screenshot
  await page.screenshot({ path: 'test-results/testids_verification.png', fullPage: true });
  console.log('\n✅ Screenshot saved: test-results/testids_verification.png');
  
  // If testids not found, wait a bit more and check again
  if (!testidsInDOM.lastUpdated || !testidsInDOM.window) {
    console.log('\n⚠️  Testids not found initially, waiting 10s and retrying...');
    await page.waitForTimeout(10000);
    
    const retryCheck = await page.evaluate(() => {
      const lastUpdated = document.querySelector('[data-testid="monitor-last-updated"]');
      const window = document.querySelector('[data-testid="monitor-window"]');
      return {
        lastUpdated: lastUpdated ? lastUpdated.outerHTML : null,
        window: window ? window.outerHTML : null,
        lastUpdatedText: lastUpdated ? lastUpdated.textContent : null,
        windowText: window ? window.textContent : null,
      };
    });
    
    console.log('\n📋 Retry DOM Verification:');
    console.log('  lastUpdated:', retryCheck.lastUpdated || 'NOT FOUND');
    console.log('  window:', retryCheck.window || 'NOT FOUND');
    
    // Assertions
    expect(retryCheck.lastUpdated).not.toBeNull();
    expect(retryCheck.window).not.toBeNull();
    expect(retryCheck.lastUpdatedText).toContain('Last updated');
    expect(retryCheck.windowText).toMatch(/Window:\s*30\s*min/i);
  } else {
    // Assertions
    expect(testidsInDOM.lastUpdated).not.toBeNull();
    expect(testidsInDOM.window).not.toBeNull();
    expect(testidsInDOM.lastUpdatedText).toContain('Last updated');
    expect(testidsInDOM.windowText).toMatch(/Window:\s*30\s*min/i);
  }
});
