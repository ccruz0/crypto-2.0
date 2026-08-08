import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import JarvisApprovalPage from '@/app/jarvis/approval/page';

vi.mock('@/lib/jarvisApproval', () => ({
  fetchApprovalQueue: vi.fn(),
  fetchSafetyStatus: vi.fn(),
  fetchChangeTask: vi.fn(),
  fetchPhase5Status: vi.fn(),
  approvePatchApply: vi.fn(),
  approvePrCreation: vi.fn(),
  rejectChangeTask: vi.fn(),
  gateLabel: (status: string) => status,
  riskBadgeClass: () => 'bg-slate-700',
}));

import {
  fetchApprovalQueue,
  fetchChangeTask,
  fetchPhase5Status,
  fetchSafetyStatus,
} from '@/lib/jarvisApproval';

const mockQueue = vi.mocked(fetchApprovalQueue);
const mockSafety = vi.mocked(fetchSafetyStatus);
const mockChange = vi.mocked(fetchChangeTask);
const mockPhase5 = vi.mocked(fetchPhase5Status);

afterEach(() => {
  cleanup();
});

beforeEach(() => {
  vi.clearAllMocks();
  mockQueue.mockResolvedValue([
    {
      task_id: 'change-aaaa-bbbb-cccc-dddddddddddd',
      objective: 'Example change task',
      status: 'waiting_for_approval',
      patch_summary: 'stub',
      files_affected: [],
      risk_score: 10,
      test_results: {},
      review_findings: [],
      approval_status: 'pending',
      created_at: null,
      workflow_type: 'change',
    },
  ]);
  mockSafety.mockResolvedValue({
    phase5: {
      patch_apply_enabled: false,
      pr_creation_enabled: false,
      github_write_enabled: false,
      double_approval_required: true,
    },
  });
  mockChange.mockResolvedValue({
    task_id: 'change-aaaa-bbbb-cccc-dddddddddddd',
    objective: 'Example change task',
    status: 'waiting_for_approval',
    artifacts: [],
    review: {},
    execution_log: [],
    approvals: [],
    workflow_type: 'change',
  });
  mockPhase5.mockResolvedValue({
    task_id: 'change-aaaa-bbbb-cccc-dddddddddddd',
    status: 'waiting_for_approval',
    workflow_type: 'change',
    safety_flags: {
      patch_apply_enabled: false,
      pr_creation_enabled: false,
      github_write_enabled: false,
      double_approval_required: true,
    },
    gate1_approved: false,
    gate2_approved: false,
    can_approve_apply: false,
    can_approve_pr: false,
    tests_passed: false,
    sandbox_applied: false,
    pr_url: null,
    branch_name: null,
    changed_files: [],
    test_results: {},
    forbidden_check: {},
  });
});

describe('JarvisApprovalPage Phase A copy', () => {
  it('soft-redirects investigation approvals to Ops → Jarvis and hides gates as Advanced', async () => {
    const user = userEvent.setup();
    render(<JarvisApprovalPage />);

    expect(await screen.findByTestId('jarvis-approval-soft-redirect')).toHaveTextContent(
      /Ops → Jarvis/i,
    );
    expect(screen.getByTestId('jarvis-approval-soft-redirect')).toHaveTextContent(
      /Send to LAB/i,
    );
    expect(screen.getByTestId('jarvis-approval-soft-redirect')).toHaveTextContent(
      /Ops → Jarvis/i,
    );
    expect(screen.getAllByRole('link', { name: /Ops → Jarvis/i }).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByRole('link', { name: /Ops → Jarvis/i })[0]).toHaveAttribute(
      'href',
      '/?tab=jarvis',
    );

    await waitFor(() => {
      expect(mockQueue).toHaveBeenCalled();
    });

    await user.click(await screen.findByText('Example change task'));

    expect(await screen.findByTestId('jarvis-approval-reject')).toHaveTextContent('Reject');
    expect(screen.getByTestId('jarvis-approval-advanced')).toBeInTheDocument();
    expect(screen.getByText(/Advanced — Phase-5 gate buttons/i)).toBeInTheDocument();
    // Collapsed by default when write gates are off — expandable (not locked closed)
    const advanced = screen.getByTestId('jarvis-approval-advanced');
    expect(advanced).not.toHaveAttribute('open');
    await user.click(screen.getByText(/Advanced — Phase-5 gate buttons/i));
    expect(advanced).toHaveAttribute('open');
    expect(screen.getByText(/Write flags are off/i)).toBeInTheDocument();
    // Buttons exist under Advanced but stay disabled as primary CTA remains Reject
    expect(screen.getByRole('button', { name: /Approve sandbox apply/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /Approve PR creation/i })).toBeDisabled();
  });
});
