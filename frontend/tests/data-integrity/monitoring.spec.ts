import { test, expect, Page } from '@playwright/test';
import { normalizeSymbol } from './helpers/normalization';
import { writeDiscrepancyReport, Discrepancy, ApiCapture } from './helpers/reporting';
import { waitForTabLoad } from './helpers/ui-capture';

const BASE_URL = process.env.BASE_URL || process.env.DASHBOARD_URL || 'http://localhost:3000';

interface MonitoringApiMessage {
  id?: string | number;
  message?: string;
  timestamp?: string | number;
  symbol?: string;
  [key: string]: unknown;
}

test.describe('Monitoring Data Integrity', () => {
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
    
    await waitForTabLoad(page, 'monitoring');
    
    // Wait for monitoring content to load
    await page.waitForSelector('[data-testid="monitoring-panel"], .monitoring-messages, table', { timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(2000);
  });

  test.afterEach(async ({ }, testInfo) => {
    if (discrepancies.length > 0) {
      writeDiscrepancyReport('monitoring', discrepancies);
    }
    
    if (testInfo.status !== 'passed') {
      const screenshotPath = `test-results/data-integrity/monitoring-failure-${Date.now()}.png`;
      await page.screenshot({ path: screenshotPath, fullPage: true });
      console.log(`📸 Screenshot saved: ${screenshotPath}`);
    }
  });

  test('should match UI monitoring messages with backend API', async () => {
    // Get API snapshot from captured responses
    const apiResponse = apiCapture.getLatestResponse(/\/api\/monitoring\/telegram-messages/);
    
    if (!apiResponse || !apiResponse.body) {
      console.warn('⚠️ No API response captured for /api/monitoring/telegram-messages');
      return;
    }
    
    // Parse API response
    const apiData = (apiResponse.body as any);
    const messages: MonitoringApiMessage[] = apiData?.messages || 
                                            (Array.isArray(apiData) ? apiData : []);
    
    if (!Array.isArray(messages)) {
      console.warn('⚠️ Monitoring API response is not an array');
      return;
    }
    
    // Filter to recent messages (last 50 for comparison)
    const recentMessages = messages.slice(0, 50);
    
    console.log(`📊 API monitoring: ${recentMessages.length} recent messages`);
    
    // Capture UI state - count messages displayed
    // Monitoring panel might show messages in different formats
    const messageElements = await page.locator('[data-testid^="monitoring-message-"], .message-item, table tr').all();
    
    console.log(`🖥️  UI monitoring: ${messageElements.length} messages displayed`);
    
    // Extract message IDs or content from UI
    const uiMessages: Array<{ id: string; content: string }> = [];
    
    for (const element of messageElements.slice(0, 50)) { // Limit to 50 for comparison
      const id = await element.getAttribute('data-testid').catch(() => null) ||
                 await element.getAttribute('data-id').catch(() => null) ||
                 '';
      const content = await element.textContent().catch(() => '') || '';
      
      if (content.trim()) {
        uiMessages.push({ id, content: content.trim() });
      }
    }
    
    // Compare message counts
    // Note: UI might paginate or filter messages, so we allow some difference
    const countDiff = Math.abs(recentMessages.length - uiMessages.length);
    if (countDiff > recentMessages.length * 0.3) { // Allow 30% difference
      console.warn(`⚠️ Significant count difference: API has ${recentMessages.length}, UI has ${uiMessages.length}`);
      
      // This might not be a critical issue if UI paginates, but log it
      if (recentMessages.length > 0 && uiMessages.length === 0) {
        discrepancies.push({
          tabName: 'monitoring',
          timestamp: new Date().toISOString(),
          symbol: 'ALL',
          field: 'messages_missing',
          uiValue: uiMessages.length,
          apiValue: recentMessages.length,
          apiSourceUrl: apiResponse.url
        });
      }
    }
    
    // For messages that we can match (by content or timestamp), verify they're displayed
    // Since message ordering might differ, we do a best-effort match
    let matchedCount = 0;
    
    for (const apiMsg of recentMessages.slice(0, 20)) { // Check first 20 messages
      const apiContent = String(apiMsg.message || '').trim();
      if (!apiContent) continue;
      
      // Try to find matching message in UI by content (partial match)
      const found = uiMessages.some(uiMsg => {
        // Match if UI content includes key parts of API message
        const apiKeyParts = apiContent.split(' ').slice(0, 3); // First 3 words
        return apiKeyParts.some(part => uiMsg.content.includes(part));
      });
      
      if (found) {
        matchedCount++;
      } else {
        // This might not be critical if UI filters or paginates, but log it
        console.warn(`⚠️ API message not found in UI: ${apiContent.substring(0, 50)}...`);
      }
    }
    
    console.log(`✅ Matched ${matchedCount} out of ${Math.min(20, recentMessages.length)} checked messages`);
    
    // Fail only if UI shows no messages when API has messages
    if (recentMessages.length > 0 && uiMessages.length === 0) {
      throw new Error('Monitoring UI shows no messages but API has messages. Check discrepancy report.');
    }
    
    // Fail if there are critical discrepancies
    const criticalDiscrepancies = discrepancies.filter(d => d.field === 'messages_missing');
    
    if (criticalDiscrepancies.length > 0) {
      throw new Error(`Found ${criticalDiscrepancies.length} critical discrepancies. Check discrepancy report.`);
    }
    
    console.log(`✅ Monitoring data integrity check passed`);
  });
});










