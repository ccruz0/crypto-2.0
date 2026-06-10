import { test, expect } from '@playwright/test';

/**
 * Jarvis Control Center tab (Advisor + Builder stub UI).
 * Verifies navigation labels and that OpenClaw tab was removed.
 */
test.describe('Jarvis Control Center tab', () => {
  test('shows Jarvis tab, hides OpenClaw, displays Advisor mode labels', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1500);

    const jarvisTab = page.getByRole('button', { name: 'Jarvis', exact: true });
    await expect(jarvisTab).toBeVisible({ timeout: 15000 });

    await expect(page.getByRole('button', { name: 'OpenClaw', exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Agent Ops', exact: true })).toHaveCount(0);

    await jarvisTab.click();
    await page.waitForTimeout(500);

    await expect(page.getByTestId('jarvis-tab')).toBeVisible();
    await expect(page.getByTestId('jarvis-mode-advisor')).toBeVisible();
    await expect(page.getByTestId('jarvis-mode-readonly')).toHaveText('Read-only');
    await expect(page.getByTestId('jarvis-no-prod-changes')).toHaveText('No production changes allowed');

    await expect(page.getByTestId('jarvis-prompt-input')).toBeVisible();
    await expect(page.getByTestId('jarvis-submit-button')).toBeVisible();
    await expect(page.getByTestId('jarvis-submit-button')).toHaveText(/Ask \(read-only\)/);

    // No write/operator/builder execution buttons exposed
    await expect(page.getByRole('button', { name: /approve/i })).toHaveCount(0);
    await expect(page.getByRole('button', { name: /deploy/i })).toHaveCount(0);
    await expect(page.getByRole('button', { name: /execute/i })).toHaveCount(0);
    await expect(page.getByRole('button', { name: /open pr/i })).toHaveCount(0);

    await expect(page.getByTestId('jarvis-system-status-toggle')).toBeVisible();
  });

  test('shows Builder mode selector when control API is available', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1500);

    await page.getByRole('button', { name: 'Jarvis', exact: true }).click();
    await page.waitForTimeout(1000);

    const builderMode = page.getByTestId('jarvis-mode-builder');
    const builderCount = await builderMode.count();
    if (builderCount === 0) {
      test.skip(true, 'Control API unavailable in this environment (expected on PROD/trading-only).');
    }

    await builderMode.click();
    await expect(page.getByTestId('jarvis-builder-status-panel')).toBeVisible();
    await expect(page.getByTestId('jarvis-builder-form')).toBeVisible();
    await expect(page.getByTestId('jarvis-builder-submit-button')).toBeVisible();

    const unavailable = page.getByTestId('jarvis-builder-unavailable');
    if (await unavailable.count()) {
      await expect(unavailable).toContainText('Builder Mode unavailable in this environment.');
      await expect(page.getByTestId('jarvis-builder-submit-button')).toBeDisabled();
    }
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
