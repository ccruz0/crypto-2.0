import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import JarvisControlTab from '@/app/components/tabs/JarvisControlTab';

const mockSearchParams = new URLSearchParams();

vi.mock('next/navigation', () => ({
  useSearchParams: () => mockSearchParams,
}));

vi.mock('@/app/api', () => ({
  listJarvisExecutionTasks: vi.fn(),
  getJarvisExecutionTask: vi.fn(),
  submitJarvisExecutionTask: vi.fn(),
  approveJarvisTask: vi.fn(),
  rejectJarvisTask: vi.fn(),
}));

vi.mock('@/lib/jarvisApproval', () => ({
  fetchApprovalQueue: vi.fn(),
  fetchChangeTask: vi.fn(),
  fetchLabTrialStatus: vi.fn(),
  sendChangeTaskToLab: vi.fn(),
  rejectChangeTask: vi.fn(),
}));

vi.mock('@/app/components/jarvis/JarvisAgentPanel', () => ({
  default: () => <div data-testid="jarvis-agent-panel-stub" />,
}));

vi.mock('@/app/components/jarvis/JarvisOperationalStatus', () => ({
  default: () => <div data-testid="jarvis-operational-status" />,
}));

import {
  getJarvisExecutionTask,
  listJarvisExecutionTasks,
} from '@/app/api';
import {
  fetchApprovalQueue,
  fetchChangeTask,
  fetchLabTrialStatus,
} from '@/lib/jarvisApproval';

const mockList = vi.mocked(listJarvisExecutionTasks);
const mockGet = vi.mocked(getJarvisExecutionTask);
const mockQueue = vi.mocked(fetchApprovalQueue);
const mockChange = vi.mocked(fetchChangeTask);
const mockLab = vi.mocked(fetchLabTrialStatus);

afterEach(() => {
  cleanup();
});

beforeEach(() => {
  vi.clearAllMocks();
  mockList.mockResolvedValue({
    tasks: [
      {
        task_id: 'wait-1111-aaaa-bbbb-cccccccccccc',
        objective: 'Inspect dry-run approval wording',
        status: 'waiting_for_approval',
        approval_status: 'pending',
        priority: 'normal',
        created_at: null,
        updated_at: null,
        estimated_cost_usd: 0,
        actual_cost_usd: 0,
      },
    ],
  } as never);
  mockQueue.mockResolvedValue([
    {
      task_id: 'wait-1111-aaaa-bbbb-cccccccccccc',
      objective: 'Inspect dry-run approval wording',
      status: 'waiting_for_approval',
      patch_summary: '',
      files_affected: [],
      risk_score: null,
      test_results: {},
      review_findings: [],
      approval_status: 'pending',
      created_at: null,
      workflow_type: 'phase3_investigation',
      can_send_to_lab: false,
      lab_ineligible_reason: 'No patch.diff artifact on this task — nothing to try in LAB.',
      lab_trial_status: 'not_started',
      lab_trial_summary: 'Not sent to LAB yet.',
    },
  ]);
  mockGet.mockResolvedValue({
    task_id: 'wait-1111-aaaa-bbbb-cccccccccccc',
    objective: 'Inspect dry-run approval wording',
    status: 'waiting_for_approval',
    approval_status: 'pending',
    priority: 'normal',
    plan: {},
    artifacts: [],
    execution_log: [],
    estimated_cost_usd: 0,
    actual_cost_usd: 0,
    review: null,
    current_step: null,
    error: null,
    final_answer: null,
  } as never);
  mockChange.mockRejectedValue(new Error('not a change task'));
  mockLab.mockRejectedValue(new Error('no lab'));
});

describe('JarvisControlTab Phase A/B copy', () => {
  it('shows Waiting on you and Approve investigation for dry-run tasks', async () => {
    render(<JarvisControlTab />);

    expect(await screen.findByTestId('jarvis-waiting-on-you')).toHaveTextContent(
      /Waiting on you/i,
    );
    expect(screen.getByTestId('jarvis-waiting-on-you')).toHaveTextContent(
      /not Send to LAB/i,
    );

    await waitFor(() => {
      expect(screen.getByTestId('jarvis-approve-investigation')).toBeInTheDocument();
    });
    expect(screen.getByTestId('jarvis-approve-investigation')).toHaveTextContent(
      'Approve investigation',
    );
    expect(screen.queryByRole('button', { name: /^Approve$/ })).toBeNull();
    expect(screen.queryByTestId('jarvis-send-to-lab')).toBeNull();
  });

  it('shows Send to LAB for eligible patch trials and disabled Promote', async () => {
    mockQueue.mockResolvedValue([
      {
        task_id: 'change-2222-aaaa-bbbb-cccccccccccc',
        objective: 'Real 4B patch proposal',
        status: 'waiting_for_approval',
        patch_summary: 'diff',
        files_affected: ['docs/README.md'],
        risk_score: 20,
        test_results: {},
        review_findings: [],
        approval_status: 'pending',
        created_at: null,
        workflow_type: 'phase4b_patch_proposal',
        can_send_to_lab: true,
        lab_ineligible_reason: '',
        lab_trial_status: 'not_started',
        lab_trial_summary: 'Not sent to LAB yet.',
      },
    ]);
    mockList.mockResolvedValue({
      tasks: [
        {
          task_id: 'change-2222-aaaa-bbbb-cccccccccccc',
          objective: 'Real 4B patch proposal',
          status: 'waiting_for_approval',
          approval_status: 'pending',
          priority: 'normal',
          created_at: null,
          updated_at: null,
          estimated_cost_usd: 0,
          actual_cost_usd: 0,
        },
      ],
    } as never);
    mockChange.mockResolvedValue({
      task_id: 'change-2222-aaaa-bbbb-cccccccccccc',
      objective: 'Real 4B patch proposal',
      status: 'waiting_for_approval',
      artifacts: [{ name: 'patch.diff', format: 'text', artifact_id: 'a1' }],
      review: {},
      execution_log: [],
      approvals: [],
      workflow_type: 'phase4b_patch_proposal',
      plan: { workflow_type: 'phase4b_patch_proposal' },
      lab_trial: {
        task_id: 'change-2222-aaaa-bbbb-cccccccccccc',
        status: 'not_started',
        summary: 'Not sent to LAB yet.',
        mechanism: 'isolated_sandbox',
        mechanism_label: 'LAB trial via isolated sandbox',
        can_send_to_lab: true,
        ineligible_reason: '',
        tests_passed: false,
        sandbox_applied: false,
        changed_files: [],
        branch_name: null,
        test_results: {},
        error: null,
        can_promote: false,
        promote_available: false,
        promote_hint: 'Send to LAB first',
        safety_flags: {
          patch_apply_enabled: false,
          pr_creation_enabled: false,
          github_write_enabled: false,
          double_approval_required: true,
          lab_trial_enabled: true,
        },
      },
    });
    mockLab.mockResolvedValue({
      task_id: 'change-2222-aaaa-bbbb-cccccccccccc',
      status: 'not_started',
      summary: 'Not sent to LAB yet.',
      mechanism: 'isolated_sandbox',
      mechanism_label: 'LAB trial via isolated sandbox',
      can_send_to_lab: true,
      ineligible_reason: '',
      tests_passed: false,
      sandbox_applied: false,
      changed_files: [],
      branch_name: null,
      test_results: {},
      error: null,
      can_promote: false,
      promote_available: false,
      promote_hint: 'Send to LAB first',
      safety_flags: {
        patch_apply_enabled: false,
        pr_creation_enabled: false,
        github_write_enabled: false,
        double_approval_required: true,
      },
    });

    render(<JarvisControlTab />);

    expect(await screen.findByTestId('jarvis-ready-for-lab')).toHaveTextContent(/Ready for LAB/i);
    expect(await screen.findByTestId('jarvis-send-to-lab')).toBeEnabled();
    expect(screen.getByTestId('jarvis-send-to-lab')).toHaveTextContent('Send to LAB');
    expect(screen.getByTestId('jarvis-promote-disabled')).toBeDisabled();
    expect(screen.queryByTestId('jarvis-approve-investigation')).toBeNull();
    expect(screen.getByTestId('jarvis-lab-status')).toHaveTextContent(/LAB trial/i);
  });

  it('disables Send to LAB with stub reason when ineligible', async () => {
    mockQueue.mockResolvedValue([
      {
        task_id: 'stub-3333-aaaa-bbbb-cccccccccccc',
        objective: 'Stub patch task',
        status: 'waiting_for_approval',
        patch_summary: 'TODO',
        files_affected: [],
        risk_score: 10,
        test_results: {},
        review_findings: [],
        approval_status: 'pending',
        created_at: null,
        workflow_type: 'phase4_change',
        can_send_to_lab: false,
        lab_ineligible_reason: 'No real patch yet — stub',
        lab_trial_status: 'not_started',
        lab_trial_summary: 'Not sent to LAB yet.',
      },
    ]);
    mockList.mockResolvedValue({
      tasks: [
        {
          task_id: 'stub-3333-aaaa-bbbb-cccccccccccc',
          objective: 'Stub patch task',
          status: 'waiting_for_approval',
          approval_status: 'pending',
          priority: 'normal',
          created_at: null,
          updated_at: null,
          estimated_cost_usd: 0,
          actual_cost_usd: 0,
        },
      ],
    } as never);
    mockChange.mockResolvedValue({
      task_id: 'stub-3333-aaaa-bbbb-cccccccccccc',
      objective: 'Stub patch task',
      status: 'waiting_for_approval',
      artifacts: [{ name: 'patch.diff', format: 'text', artifact_id: 'a2' }],
      review: {},
      execution_log: [],
      approvals: [],
      workflow_type: 'phase4_change',
      plan: { workflow_type: 'phase4_change' },
      lab_trial: {
        task_id: 'stub-3333-aaaa-bbbb-cccccccccccc',
        status: 'not_started',
        summary: 'Not sent to LAB yet.',
        mechanism: 'isolated_sandbox',
        mechanism_label: 'LAB trial via isolated sandbox',
        can_send_to_lab: false,
        ineligible_reason: 'No real patch yet — this artifact is a stub/TODO placeholder',
        tests_passed: false,
        sandbox_applied: false,
        changed_files: [],
        branch_name: null,
        test_results: {},
        error: null,
        can_promote: false,
        promote_available: false,
        promote_hint: 'Send to LAB first',
        safety_flags: {
          patch_apply_enabled: false,
          pr_creation_enabled: false,
          github_write_enabled: false,
          double_approval_required: true,
        },
      },
    });

    render(<JarvisControlTab />);

    expect(await screen.findByTestId('jarvis-send-to-lab')).toBeDisabled();
    expect(screen.getByTestId('jarvis-lab-ineligible')).toHaveTextContent(/stub/i);
  });
});
