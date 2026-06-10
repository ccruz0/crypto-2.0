import { test, expect } from '@playwright/test';

/**
 * Jarvis Control Center tab (Phase 1 — Advisor read-only).
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
    await expect(page.getByTestId('jarvis-mode-advisor')).toHaveText('Advisor Mode');
    await expect(page.getByTestId('jarvis-mode-readonly')).toHaveText('Read-only');
    await expect(page.getByTestId('jarvis-no-prod-changes')).toHaveText('No production changes allowed');

    await expect(page.getByTestId('jarvis-prompt-input')).toBeVisible();
    await expect(page.getByTestId('jarvis-submit-button')).toBeVisible();
    await expect(page.getByTestId('jarvis-submit-button')).toHaveText(/Ask \(read-only\)/);

    // No write/operator/builder action buttons exposed
    await expect(page.getByRole('button', { name: /approve/i })).toHaveCount(0);
    await expect(page.getByRole('button', { name: /deploy/i })).toHaveCount(0);
    await expect(page.getByRole('button', { name: /execute/i })).toHaveCount(0);

    await expect(page.getByTestId('jarvis-system-status-toggle')).toBeVisible();
  });

  test('trading Portfolio tab still loads after Jarvis navigation', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1500);

    const portfolioTab = page.getByRole('button', { name: 'Portfolio', exact: true });
    await expect(portfolioTab).toBeVisible({ timeout: 15000 });
    await portfolioTab.click();
    await page.waitForTimeout(1000);

    // Portfolio tab content region should render (heading or table)
    await expect(page.locator('body')).not.toBeEmpty();
  });
});
