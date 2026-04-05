import { Page, Locator } from '@playwright/test';

/**
 * Capture UI state from the DOM for a specific tab
 */
export interface UIRow {
  symbol: string;
  [key: string]: unknown;
}

/**
 * Extract symbol from a row using data-testid attribute
 */
export function extractSymbolFromRow(row: Locator): Promise<string | null> {
  return row.getAttribute('data-testid').then(attr => {
    if (!attr) return null;
    // Extract symbol from patterns like "watchlist-row-BTC_USDT" or "portfolio-row-ETH_USDT"
    const match = attr.match(/(?:watchlist|portfolio|monitoring)-row-(.+)$/);
    return match ? match[1] : null;
  }).catch(() => null);
}

/**
 * Get toggle state from a button or element
 * Looks for common patterns: ✅/❌, YES/NO, enabled/disabled, checked attributes
 */
export async function getToggleState(element: Locator): Promise<boolean | null> {
  try {
    const text = await element.textContent();
    if (text) {
      const normalized = text.trim().toLowerCase();
      if (normalized.includes('✅') || normalized.includes('yes') || normalized.includes('enabled') || normalized.includes('on')) {
        return true;
      }
      if (normalized.includes('❌') || normalized.includes('no') || normalized.includes('disabled') || normalized.includes('off')) {
        return false;
      }
    }
    
    // Check for checked attribute
    const checked = await element.getAttribute('aria-checked');
    if (checked === 'true') return true;
    if (checked === 'false') return false;
    
    // Check for data-state or similar attributes
    const dataState = await element.getAttribute('data-state');
    if (dataState === 'checked' || dataState === 'enabled') return true;
    if (dataState === 'unchecked' || dataState === 'disabled') return false;
    
    return null;
  } catch {
    return null;
  }
}

/**
 * Wait for tab to be fully loaded
 */
export async function waitForTabLoad(page: Page, tabName: string, timeout: number = 15000): Promise<void> {
  // Click the tab button
  const tabButton = page.locator(`[data-testid="tab-${tabName}"]`).first();
  if (await tabButton.count() === 0) {
    // Fallback to text-based selector
    try {
      await page.click(`button:has-text("${tabName}")`);
    } catch {
      // Try alternative text matching
      const buttons = page.locator('button');
      const count = await buttons.count();
      for (let i = 0; i < count; i++) {
        const button = buttons.nth(i);
        const text = await button.textContent().catch(() => '');
        if (text.toLowerCase().includes(tabName.toLowerCase())) {
          await button.click();
          break;
        }
      }
    }
  } else {
    await tabButton.click();
  }
  
  // Wait for network to be idle
  await page.waitForLoadState('networkidle', { timeout });
  await page.waitForTimeout(1000); // Additional wait for React to update
}

