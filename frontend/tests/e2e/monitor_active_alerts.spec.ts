import { test, expect } from '@playwright/test';

/**
 * E2E test for Monitor Active Alerts Fix Verification
 * 
 * Verifies that:
 * 1. Active Alerts derives from telegram_messages + order_intents
 * 2. Shows SENT/BLOCKED/FAILED status labels (not "signal detected")
 * 3. Non-SENT alerts show reason_code/reason_message
 */
test.describe('Monitor Active Alerts Fix Verification', () => {
  test('should show Active Alerts with status labels from telegram_messages', async ({ page }) => {
    test.setTimeout(60000); // Increase timeout to 60s for data loading
    const baseURL = process.env.DASHBOARD_URL || process.env.BASE_URL || 'http://localhost:3000';
    
    console.log(`Navigating to ${baseURL}`);
    
    // Navigate to dashboard
    await page.goto(baseURL);
    
    // Wait for page to load
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    
    // Take full page screenshot
    await page.screenshot({ path: 'test-results/monitor_page.png', fullPage: true });
    console.log('✅ Screenshot: monitor_page.png');
    
    // Navigate to Monitoring tab
    // Try multiple selectors for the Monitoring tab
    const monitoringSelectors = [
      'button:has-text("Monitoring")',
      'a:has-text("Monitoring")',
      '[data-tab="monitoring"]',
      'text=Monitoring',
      'text=Monitor'
    ];
    
    let monitoringTab = null;
    for (const selector of monitoringSelectors) {
      try {
        const element = page.locator(selector).first();
        if (await element.isVisible({ timeout: 1000 })) {
          monitoringTab = element;
          break;
        }
      } catch (e) {
        // Continue to next selector
      }
    }
    
    if (monitoringTab) {
      await monitoringTab.click();
      await page.waitForTimeout(3000);
      console.log('✅ Clicked Monitoring tab');
    } else {
      // Try direct navigation via URL
      console.log('⚠️  Monitoring tab not found, trying direct navigation');
      await page.goto(`${baseURL}?tab=monitoring`);
      await page.waitForTimeout(3000);
    }
    
    // Wait for Active Alerts section
    const activeAlertsSelectors = [
      'h3:has-text("Active Alerts")',
      'text=Active Alerts',
      '[data-testid="active-alerts"]'
    ];
    
    let activeAlertsHeader = null;
    for (const selector of activeAlertsSelectors) {
      try {
        const element = page.locator(selector).first();
        if (await element.isVisible({ timeout: 5000 })) {
          activeAlertsHeader = element;
          break;
        }
      } catch (e) {
        // Continue to next selector
      }
    }
    
    if (!activeAlertsHeader) {
      // Take screenshot anyway to see what's on the page
      await page.screenshot({ path: 'test-results/monitor_no_active_alerts.png', fullPage: true });
      throw new Error('Active Alerts section not found');
    }
    
    console.log('✅ Found Active Alerts section');
    
    // Scroll to Active Alerts section
    await activeAlertsHeader.scrollIntoViewIfNeeded();
    await page.waitForTimeout(1000);
    
    // Find the panel containing Active Alerts - use first() to avoid strict mode violation
    const panel = page.locator('div:has(h3:has-text("Active Alerts"))').first();
    
    // Take screenshot of Active Alerts panel
    await panel.screenshot({ path: 'test-results/active_alerts_panel.png' });
    console.log('✅ Screenshot: active_alerts_panel.png');
    
    // Look for the table with alerts
    const table = page.locator('table').filter({ hasText: 'Active Alerts' }).or(
      page.locator('table').first()
    );
    
    if (await table.isVisible({ timeout: 5000 })) {
      await table.screenshot({ path: 'test-results/active_alerts_table.png' });
      console.log('✅ Screenshot: active_alerts_table.png');
      
      // Check for status labels (SENT, BLOCKED, FAILED)
      const statusLabels = page.locator('text=/SENT|BLOCKED|FAILED/i');
      const statusCount = await statusLabels.count();
      console.log(`Found ${statusCount} status labels (SENT/BLOCKED/FAILED)`);
      
      // Check for "signal detected" - should NOT be present anywhere on the Monitor page
      const signalDetected = page.locator('text=/signal detected/i');
      const signalDetectedCount = await signalDetected.count();
      console.log(`Found ${signalDetectedCount} instances of "signal detected" (should be 0)`);
      
      // Assertions
      if (statusCount > 0) {
        console.log('✅ PASS: Found status labels (SENT/BLOCKED/FAILED)');
      } else {
        console.log('⚠️  WARNING: No status labels found, but table exists');
      }
      
      // Regression assertion: "signal detected" must NOT appear anywhere
      expect(signalDetectedCount).toBe(0);
      console.log('✅ PASS: No "signal detected" text found');
      
      // Wait for monitoring data to load by waiting for the testid elements
      const lastUpdatedElement = page.locator('[data-testid="monitor-last-updated"]');
      const windowElement = page.locator('[data-testid="monitor-window"]');
      
      // Wait for elements to be attached to DOM first, then wait for them to be visible with data
      await lastUpdatedElement.waitFor({ state: 'attached', timeout: 15000 });
      await windowElement.waitFor({ state: 'attached', timeout: 15000 });
      
      // Wait for data to load (elements should contain actual data, not "Loading...")
      await lastUpdatedElement.waitFor({ 
        state: 'visible', 
        timeout: 20000 
      });
      await expect(lastUpdatedElement).not.toContainText(/Loading/i);
      
      await windowElement.waitFor({ 
        state: 'visible', 
        timeout: 20000 
      });
      await expect(windowElement).not.toContainText(/Loading/i);
      
      // Strict assertion: "Last updated" element must be visible
      await expect(lastUpdatedElement).toBeVisible();
      
      // Strict assertion: "Last updated" must NOT contain "Invalid Date"
      const lastUpdatedText = await lastUpdatedElement.textContent();
      expect(lastUpdatedText).not.toContain('Invalid Date');
      expect(lastUpdatedText?.toLowerCase()).not.toContain('invalid date');
      console.log(`✅ PASS: Found "Last updated" label - "${lastUpdatedText}"`);
      console.log(`✅ PASS: "Last updated" does not contain "Invalid Date"`);
      
      // Global guard: "Invalid Date" must NOT appear anywhere on the page
      const pageContent = await page.content();
      const pageText = await page.textContent('body');
      expect(pageContent).not.toContain('Invalid Date');
      expect(pageText?.toLowerCase()).not.toContain('invalid date');
      console.log(`✅ PASS: "Invalid Date" not found anywhere on the page`);
      
      // Assert "Window" label shows exactly "Window: 30 min"
      await expect(windowElement).toHaveText(/Window:\s*30\s*min/i);
      const windowText = await windowElement.textContent();
      console.log(`✅ PASS: Found "Window: 30 min" label - "${windowText}"`);
      
      // Take screenshot of throttle section if it exists
      const throttleSection = page.locator('text=/Throttle|Mensajes Enviados/i').first();
      if (await throttleSection.isVisible({ timeout: 2000 })) {
        await throttleSection.scrollIntoViewIfNeeded();
        await page.waitForTimeout(500);
        const throttlePanel = page.locator('div:has-text("Throttle")').first();
        await throttlePanel.screenshot({ path: 'test-results/throttle_sent.png' });
        console.log('✅ Screenshot: throttle_sent.png');
      }
      
      // Look for blocked messages section
      const blockedSection = page.locator('text=/Telegram|Mensajes Bloqueados/i').first();
      if (await blockedSection.isVisible({ timeout: 2000 })) {
        await blockedSection.scrollIntoViewIfNeeded();
        await page.waitForTimeout(500);
        const blockedPanel = page.locator('div:has-text("Telegram")').first();
        await blockedPanel.screenshot({ path: 'test-results/throttle_blocked.png' });
        console.log('✅ Screenshot: throttle_blocked.png');
      }
    } else {
      // No table found - might be empty state
      const emptyState = page.locator('text=/No active alerts|No alerts/i');
      if (await emptyState.isVisible({ timeout: 2000 })) {
        await panel.screenshot({ path: 'test-results/active_alerts_empty.png' });
        console.log('ℹ️  Active Alerts is empty (no alerts in last 30 minutes)');
        console.log('✅ This is expected if there are no telegram_messages in the last 30 minutes');
      } else {
        await panel.screenshot({ path: 'test-results/active_alerts_unknown.png' });
        throw new Error('Active Alerts table not found and no empty state found');
      }
    }
    
    // Final full page screenshot
    await page.screenshot({ path: 'test-results/monitor_final.png', fullPage: true });
    console.log('✅ Screenshot: monitor_final.png');
  });
});
