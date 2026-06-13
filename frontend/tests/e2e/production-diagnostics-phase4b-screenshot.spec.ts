import { test, expect } from '@playwright/test';

const mockInvestigation = {
  investigation_id: 'inv-screenshot-1',
  objective: 'Why are open orders empty?',
  category: 'orders',
  template_id: 'generic',
  status: 'completed',
  summary: 'Trigger order sync failure blocks cache refresh.',
  evidence: [],
  evidence_count: 2,
  root_cause: 'Trigger order API failure blocks cache updates',
  confidence: 75,
  ranked_causes: [],
  impact: 'Dashboard shows zero open orders.',
  recommended_fix: 'Allow cache updates when trigger sync fails.',
  verification_steps: ['Re-run reconcile after fix.'],
  next_action: 'Propose patch behind approval gate.',
  proposal_task_id: 'task-demo-1',
  proposal_status: 'waiting_for_approval',
};

const mockEligibility = {
  eligible: false,
  reasons: ['phase4b_proposals_disabled'],
  confidence: 75,
  fix_template_candidates: [
    {
      fix_template_id: 'orders.trigger_50001_cache_independent',
      match: 'Trigger order API failure blocks cache updates',
    },
  ],
  existing_proposal_task_id: 'task-demo-1',
};

test('capture phase4b eligibility panel screenshot', async ({ page }) => {
  await page.route('**/api/jarvis/investigations?**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        investigations: [
          {
            investigation_id: mockInvestigation.investigation_id,
            objective: mockInvestigation.objective,
            status: mockInvestigation.status,
            confidence: mockInvestigation.confidence,
            evidence_count: mockInvestigation.evidence_count,
          },
        ],
      }),
    });
  });

  await page.route('**/api/jarvis/investigations/presets', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ presets: [] }),
    });
  });

  await page.route(`**/api/jarvis/investigations/${mockInvestigation.investigation_id}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockInvestigation),
    });
  });

  await page.route(
    `**/api/jarvis/proposals/eligibility/${mockInvestigation.investigation_id}`,
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockEligibility),
      });
    },
  );

  await page.route('**/api/jarvis/tasks/execution/task-demo-1', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        task_id: 'task-demo-1',
        objective: 'Propose patch for open orders cache',
        task: 'patch_proposal',
        status: 'waiting_for_approval',
        artifacts: [{ name: 'proposal.patch' }, { name: 'proposal_summary.md' }],
      }),
    });
  });

  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1500);

  await page.getByRole('button', { name: 'Production Diagnostics', exact: true }).click();
  await page.waitForTimeout(500);

  await page.getByText('Why are open orders empty?').click();
  await expect(page.getByTestId('proposal-eligibility-panel')).toBeVisible({ timeout: 10000 });
  await expect(page.getByTestId('phase4b-disabled-notice')).toBeVisible();

  await page.screenshot({
    path: 'test-results/phase4b-eligibility-panel.png',
    fullPage: true,
  });
});
