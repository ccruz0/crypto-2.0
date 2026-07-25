import { test, expect } from '@playwright/test';

/**
 * Production Diagnostics Phase 4B proposal eligibility UI (read-only in production).
 * Tab lives under the Ops nav group.
 */
test.describe('Production Diagnostics Phase 4B', () => {
  test('shows proposal eligibility panel without OpenClaw tab', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1500);

    await expect(page.getByRole('button', { name: 'OpenClaw', exact: true })).toHaveCount(0);

    await page.getByTestId('ops-nav-toggle').click();
    await expect(page.getByTestId('ops-nav-menu')).toBeVisible({ timeout: 15000 });
    await page.getByRole('menuitem', { name: 'Production Diagnostics', exact: true }).click();
    await page.waitForTimeout(500);

    await expect(page.getByTestId('production-diagnostics-tab')).toBeVisible();
    await expect(page.getByText('Read-only incident investigations')).toBeVisible();
  });
});
