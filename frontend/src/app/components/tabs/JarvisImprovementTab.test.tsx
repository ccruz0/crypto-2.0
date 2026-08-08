import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import JarvisImprovementTab from '@/app/components/tabs/JarvisImprovementTab';
import type { JarvisImprovementRecommendation } from '@/app/api';

vi.mock('@/app/api', () => ({
  getJarvisImprovementRecommendations: vi.fn(),
  getJarvisImprovementTemplates: vi.fn(),
  getJarvisImprovementTools: vi.fn(),
  getJarvisImprovementTrends: vi.fn(),
  getJarvisImprovementQuality: vi.fn(),
  executeJarvisImprovementRecommendation: vi.fn(),
}));

import {
  executeJarvisImprovementRecommendation,
  getJarvisImprovementQuality,
  getJarvisImprovementRecommendations,
  getJarvisImprovementTemplates,
  getJarvisImprovementTools,
  getJarvisImprovementTrends,
} from '@/app/api';

const mockGetRecs = vi.mocked(getJarvisImprovementRecommendations);
const mockGetTemplates = vi.mocked(getJarvisImprovementTemplates);
const mockGetTools = vi.mocked(getJarvisImprovementTools);
const mockGetTrends = vi.mocked(getJarvisImprovementTrends);
const mockGetQuality = vi.mocked(getJarvisImprovementQuality);
const mockExecute = vi.mocked(executeJarvisImprovementRecommendation);

const sampleRec: JarvisImprovementRecommendation = {
  id: 'template-insuff-open_orders_empty',
  category: 'template_gap',
  priority: 'high',
  priority_score: 80,
  title: 'Improve evidence collectors',
  recommendation: 'Add mandatory collectors for open orders',
  reason: 'High insufficient_evidence rate',
  evidence: ['3 investigations insufficient'],
  expected_benefit: 'Fewer insufficient results',
  impact: 'high',
  frequency: 3,
  confidence: 70,
};

afterEach(() => {
  cleanup();
});

beforeEach(() => {
  vi.clearAllMocks();
  mockGetRecs.mockResolvedValue({
    recommendations: [sampleRec],
    backlog: [sampleRec],
    by_priority: { high: [sampleRec], medium: [], low: [] },
    counts: { total: 1, high: 1, medium: 0, low: 0 },
    read_only: true,
  });
  mockGetTemplates.mockResolvedValue({
    gaps: [],
    recommendations: [],
    summary: {},
    template_metrics: [],
    read_only: true,
  });
  mockGetTools.mockResolvedValue({
    tools: [],
    low_utility_tools: [],
    high_value_tools: [],
    recommendations: [],
    summary: {},
    read_only: true,
  });
  mockGetTrends.mockResolvedValue({
    quality_scores: {},
    false_positives: {},
    period_rates: {},
    recurring_incidents: [],
    open_orders_share_pct: 0,
    quality_score_daily: [],
    recommendations: [],
    read_only: true,
  });
  mockGetQuality.mockResolvedValue({
    quality_score: 70,
    recommendation_count: 1,
    high_priority_count: 1,
    suppressed_recommendations: 0,
    duplicate_recommendations: 0,
    evidence_coverage: 100,
    read_only: true,
  });
});

describe('JarvisImprovementTab Execute', () => {
  it('queues a dry-run task when Execute is clicked', async () => {
    mockExecute.mockResolvedValue({
      recommendation_id: sampleRec.id,
      task_id: 'abcd1234-ffff-eeee-dddd-cccccccccccc',
      status: 'waiting_for_approval',
      objective: 'Jarvis improvement recommendation',
      approval_required: true,
      approval_status: 'pending',
      dry_run: true,
      message: 'Queued dry-run Jarvis task',
    });

    const user = userEvent.setup();
    render(<JarvisImprovementTab />);

    const button = await screen.findByTestId(`jarvis-improvement-execute-${sampleRec.id}`);
    expect(button).toHaveTextContent('Execute');
    await user.click(button);

    await waitFor(() => {
      expect(mockExecute).toHaveBeenCalledWith(
        expect.objectContaining({
          id: sampleRec.id,
          title: sampleRec.title,
          recommendation: sampleRec.recommendation,
        }),
      );
    });

    expect(
      await screen.findByTestId(`jarvis-improvement-execute-success-${sampleRec.id}`),
    ).toHaveTextContent(/Queued dry-run task abcd1234/i);
    const approveLink = await screen.findByTestId(
      `jarvis-improvement-open-approve-${sampleRec.id}`,
    );
    expect(approveLink).toHaveAttribute(
      'href',
      '/?tab=jarvis&task=abcd1234-ffff-eeee-dddd-cccccccccccc',
    );
    expect(approveLink).toHaveTextContent('Open Jarvis to Approve');
  });

  it('shows an error when Execute fails', async () => {
    mockExecute.mockRejectedValue(new Error('Jarvis is disabled'));
    const user = userEvent.setup();
    render(<JarvisImprovementTab />);

    await user.click(await screen.findByTestId(`jarvis-improvement-execute-${sampleRec.id}`));
    expect(
      await screen.findByTestId(`jarvis-improvement-execute-error-${sampleRec.id}`),
    ).toHaveTextContent('Jarvis is disabled');
  });

  it('shows failed status and error when queued task fails', async () => {
    mockExecute.mockResolvedValue({
      recommendation_id: sampleRec.id,
      task_id: '72f0f556-fc9b-41c8-8db2-0c2270706fb0',
      status: 'failed',
      objective: 'Jarvis improvement recommendation',
      approval_required: false,
      approval_status: 'not_required',
      dry_run: true,
      error: 'Objective or plan classified as FORBIDDEN',
      message: 'Dry-run task queued but failed immediately',
    });

    const user = userEvent.setup();
    render(<JarvisImprovementTab />);
    await user.click(await screen.findByTestId(`jarvis-improvement-execute-${sampleRec.id}`));

    expect(
      await screen.findByTestId(`jarvis-improvement-execute-failed-${sampleRec.id}`),
    ).toHaveTextContent(/status: failed.*FORBIDDEN/i);
    expect(screen.queryByTestId(`jarvis-improvement-execute-success-${sampleRec.id}`)).toBeNull();
  });
});
