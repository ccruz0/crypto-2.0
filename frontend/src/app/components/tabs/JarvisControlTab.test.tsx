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

const mockList = vi.mocked(listJarvisExecutionTasks);
const mockGet = vi.mocked(getJarvisExecutionTask);

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
});

describe('JarvisControlTab Phase A copy', () => {
  it('shows Waiting on you and Approve investigation (not bare Approve / Send to LAB)', async () => {
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
    expect(screen.getByTestId('jarvis-reject-task')).toHaveTextContent('Reject');
    expect(screen.queryByRole('button', { name: /^Approve$/ })).toBeNull();
    expect(screen.getByRole('link', { name: /Advanced change gates/i })).toHaveAttribute(
      'href',
      '/jarvis/approval',
    );
  });
});
