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
  listJarvisExecutionTasks: vi.fn(),
}));

vi.mock('@/lib/jarvisApproval', () => ({
  fetchApprovalQueue: vi.fn(),
}));

import {
  executeJarvisImprovementRecommendation,
  getJarvisImprovementQuality,
  getJarvisImprovementRecommendations,
  getJarvisImprovementTemplates,
  getJarvisImprovementTools,
  getJarvisImprovementTrends,
  listJarvisExecutionTasks,
} from '@/app/api';
import { fetchApprovalQueue } from '@/lib/jarvisApproval';

const mockGetRecs = vi.mocked(getJarvisImprovementRecommendations);
const mockGetTemplates = vi.mocked(getJarvisImprovementTemplates);
const mockGetTools = vi.mocked(getJarvisImprovementTools);
const mockGetTrends = vi.mocked(getJarvisImprovementTrends);
const mockGetQuality = vi.mocked(getJarvisImprovementQuality);
const mockExecute = vi.mocked(executeJarvisImprovementRecommendation);
const mockListExecution = vi.mocked(listJarvisExecutionTasks);
const mockFetchQueue = vi.mocked(fetchApprovalQueue);

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
  mockListExecution.mockResolvedValue({ tasks: [] });
  mockFetchQueue.mockResolvedValue([]);
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
    const openLink = await screen.findByTestId(`jarvis-improvement-open-jarvis-${sampleRec.id}`);
    expect(openLink).toHaveAttribute(
      'href',
      '/?tab=jarvis&task=abcd1234-ffff-eeee-dddd-cccccccccccc',
    );
    expect(openLink).toHaveTextContent('Open in Jarvis');
  });

  it('does not point dry-run operators at Approval Center', async () => {
    render(<JarvisImprovementTab />);
    const tab = await screen.findByTestId('jarvis-improvement-tab');
    expect(tab).toHaveTextContent(/Ops → Jarvis/i);
    expect(tab).toHaveTextContent(/Approve investigation/i);
    expect(tab.querySelector('a[href="/jarvis/approval"]')).toBeNull();
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

describe('JarvisImprovementTab trial status badge', () => {
  it('shows Executed badge + Open in Jarvis when a matching task exists', async () => {
    const taskId = 'task-matching-rec-001';
    mockListExecution.mockResolvedValue({
      tasks: [
        {
          task_id: taskId,
          objective: `Jarvis improvement recommendation [${sampleRec.id}]: Improve evidence collectors`,
          status: 'waiting_for_approval',
          created_at: '2026-08-08T12:00:00Z',
        },
      ],
    });
    mockFetchQueue.mockResolvedValue([
      {
        task_id: taskId,
        objective: `Jarvis improvement recommendation [${sampleRec.id}]: Improve evidence collectors`,
        status: 'waiting_for_approval',
        patch_summary: '',
        files_affected: [],
        risk_score: null,
        test_results: {},
        review_findings: [],
        approval_status: 'pending',
        created_at: '2026-08-08T12:00:00Z',
        workflow_type: 'phase3_investigation',
        can_send_to_lab: false,
        lab_trial_status: 'not_started',
      },
    ]);

    render(<JarvisImprovementTab />);

    expect(await screen.findByTestId(`jarvis-improvement-trial-badge-${taskId}`)).toHaveTextContent(
      /Executed · Waiting approval/i,
    );
    const open = await screen.findByTestId(`jarvis-improvement-open-jarvis-${sampleRec.id}`);
    expect(open).toHaveAttribute('href', `/?tab=jarvis&task=${taskId}`);
    // Card remains visible in the recommendations feed
    expect(screen.getByTestId(`jarvis-improvement-rec-${sampleRec.id}`)).toBeTruthy();
    expect(screen.getByTestId(`jarvis-improvement-execute-${sampleRec.id}`)).toHaveTextContent(
      'Execute again',
    );
  });

  it('shows LAB passed from real lab_trial_status, not from dry-run waiting alone', async () => {
    const taskId = 'task-lab-passed';
    mockListExecution.mockResolvedValue({
      tasks: [
        {
          task_id: taskId,
          objective: `Jarvis improvement recommendation [${sampleRec.id}]: Improve evidence collectors`,
          status: 'waiting_for_pr_approval',
          created_at: '2026-08-08T12:00:00Z',
        },
      ],
    });
    mockFetchQueue.mockResolvedValue([
      {
        task_id: taskId,
        objective: `Jarvis improvement recommendation [${sampleRec.id}]: Improve evidence collectors`,
        status: 'waiting_for_pr_approval',
        patch_summary: 'diff',
        files_affected: [],
        risk_score: 10,
        test_results: {},
        review_findings: [],
        approval_status: 'pending',
        created_at: '2026-08-08T12:00:00Z',
        workflow_type: 'phase4b_patch_proposal',
        can_send_to_lab: false,
        lab_trial_status: 'passed',
      },
    ]);

    render(<JarvisImprovementTab />);
    expect(await screen.findByTestId(`jarvis-improvement-trial-badge-${taskId}`)).toHaveTextContent(
      /Executed · LAB passed/i,
    );
  });

  it('does not show Testing in LAB when lab trial was never started', async () => {
    const taskId = 'task-dry-only';
    mockListExecution.mockResolvedValue({
      tasks: [
        {
          task_id: taskId,
          objective: `Jarvis improvement recommendation [${sampleRec.id}]: Improve evidence collectors`,
          status: 'waiting_for_approval',
          created_at: '2026-08-08T12:00:00Z',
        },
      ],
    });
    mockFetchQueue.mockResolvedValue([
      {
        task_id: taskId,
        objective: `Jarvis improvement recommendation [${sampleRec.id}]: Improve evidence collectors`,
        status: 'waiting_for_approval',
        patch_summary: '',
        files_affected: [],
        risk_score: null,
        test_results: {},
        review_findings: [],
        approval_status: 'pending',
        created_at: '2026-08-08T12:00:00Z',
        workflow_type: 'phase3_investigation',
        can_send_to_lab: false,
        lab_trial_status: 'not_started',
      },
    ]);

    render(<JarvisImprovementTab />);
    const badge = await screen.findByTestId(`jarvis-improvement-trial-badge-${taskId}`);
    expect(badge).toHaveTextContent(/Waiting approval/i);
    expect(badge).not.toHaveTextContent(/LAB/i);
  });
});
