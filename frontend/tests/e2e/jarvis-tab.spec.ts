import { test, expect } from '@playwright/test';

/**
 * Jarvis Control Center tab replaces OpenClaw and Agent Ops.
 */
test.describe('Jarvis Control Center tab', () => {
  test('shows Jarvis tab, hides OpenClaw, renders input and submit', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1500);

    const jarvisTab = page.getByRole('button', { name: 'Jarvis', exact: true });
    await expect(jarvisTab).toBeVisible({ timeout: 15000 });

    await expect(page.getByRole('button', { name: 'OpenClaw', exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Agent Ops', exact: true })).toHaveCount(0);

    await jarvisTab.click();
    await page.waitForTimeout(500);

    await expect(page.getByTestId('jarvis-tab')).toBeVisible();
    await expect(page.getByTestId('jarvis-prompt-input')).toBeVisible();
    await expect(page.getByTestId('jarvis-submit-button')).toBeVisible();
    await expect(page.getByTestId('jarvis-submit-button')).toHaveText('Submit to Jarvis');
    await expect(page.getByText('Operational Status')).toBeVisible();
  });

  test('submit while automation disabled shows clear message without crash', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1500);

    await page.getByRole('button', { name: 'Jarvis', exact: true }).click();
    await page.waitForTimeout(500);

    await page.getByTestId('jarvis-prompt-input').fill('Investigate stale market data for BTC');
    await page.getByTestId('jarvis-submit-button').click();

    await expect(page.getByTestId('jarvis-submit-message')).toBeVisible({ timeout: 5000 });
    await expect(page.getByTestId('jarvis-submit-message')).toContainText(/not executed|Unable to reach/i);
  });

  test('trading Portfolio tab still loads after Jarvis navigation', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1500);

    const portfolioTab = page.getByRole('button', { name: 'Portfolio', exact: true });
    await expect(portfolioTab).toBeVisible({ timeout: 15000 });
    await portfolioTab.click();
    await page.waitForTimeout(1000);

    await expect(page.locator('body')).not.toBeEmpty();
  });
});
