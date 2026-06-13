import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ProposalEligibilityPanel from '@/app/components/tabs/ProposalEligibilityPanel';
import type { JarvisInvestigationDetail, JarvisProposalEligibility } from '@/app/api';

vi.mock('@/app/api', () => ({
  getProposalEligibility: vi.fn(),
  proposePatchFromInvestigation: vi.fn(),
  getJarvisExecutionTask: vi.fn(),
}));

import {
  getJarvisExecutionTask,
  getProposalEligibility,
  proposePatchFromInvestigation,
} from '@/app/api';

const mockGetProposalEligibility = vi.mocked(getProposalEligibility);
const mockProposePatch = vi.mocked(proposePatchFromInvestigation);
const mockGetTask = vi.mocked(getJarvisExecutionTask);

const baseDetail: JarvisInvestigationDetail = {
  investigation_id: 'inv-test-1',
  objective: 'Why are open orders empty?',
  category: 'orders',
  template_id: 'generic',
  status: 'completed',
  summary: 'Summary',
  evidence: [],
  evidence_count: 0,
  root_cause: 'Trigger order API failure blocks cache updates',
  confidence: 75,
  ranked_causes: [],
  impact: 'Impact',
  recommended_fix: 'Fix cache refresh',
  verification_steps: [],
  next_action: 'Propose patch',
};

const eligibleResponse: JarvisProposalEligibility = {
  eligible: true,
  reasons: [],
  confidence: 75,
  fix_template_candidates: [
    {
      fix_template_id: 'orders.trigger_50001_cache_independent',
      match: 'Trigger order API failure blocks cache updates',
    },
  ],
  existing_proposal_task_id: null,
};

const disabledResponse: JarvisProposalEligibility = {
  eligible: false,
  reasons: ['phase4b_proposals_disabled'],
  confidence: 75,
  fix_template_candidates: [
    {
      fix_template_id: 'orders.trigger_50001_cache_independent',
      match: 'Trigger order API failure blocks cache updates',
    },
  ],
  existing_proposal_task_id: null,
};

describe('ProposalEligibilityPanel', () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    mockGetTask.mockRejectedValue(new Error('not loaded'));
  });

  it('renders disabled reason and phase4b notice', async () => {
    mockGetProposalEligibility.mockResolvedValue(disabledResponse);

    render(<ProposalEligibilityPanel investigationId="inv-test-1" detail={baseDetail} />);

    expect(await screen.findByTestId('phase4b-disabled-notice')).toHaveTextContent(
      'Phase 4B is deployed but disabled in production.',
    );
    expect(screen.getByTestId('eligibility-reasons')).toHaveTextContent('phase4b proposals disabled');
    expect(screen.getByTestId('generate-patch-proposal-button')).toBeDisabled();
  });

  it('disables Generate Patch Proposal when phase4b disabled', async () => {
    mockGetProposalEligibility.mockResolvedValue(disabledResponse);

    render(<ProposalEligibilityPanel investigationId="inv-test-1" detail={baseDetail} />);

    const button = await screen.findByTestId('generate-patch-proposal-button');
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute(
      'title',
      'Phase 4B is deployed but disabled in production.',
    );
  });

  it('displays matching fix template', async () => {
    mockGetProposalEligibility.mockResolvedValue(disabledResponse);

    render(<ProposalEligibilityPanel investigationId="inv-test-1" detail={baseDetail} />);

    const template = await screen.findByTestId('matching-fix-template');
    expect(template).toHaveTextContent('orders.trigger_50001_cache_independent');
    expect(template).toHaveTextContent('Trigger order API failure blocks cache updates');
  });

  it('displays existing proposal status and artifacts', async () => {
    mockGetProposalEligibility.mockResolvedValue({
      ...disabledResponse,
      existing_proposal_task_id: 'task-existing-1',
    });
    mockGetTask.mockResolvedValue({
      task_id: 'task-existing-1',
      objective: 'Patch',
      task: 'patch',
      status: 'waiting_for_approval',
      artifacts: [{ name: 'proposal.patch' }, { name: 'proposal_summary.md' }],
    } as never);

    render(
      <ProposalEligibilityPanel
        investigationId="inv-test-1"
        detail={{
          ...baseDetail,
          proposal_task_id: 'task-existing-1',
          proposal_status: 'waiting_for_approval',
        }}
      />,
    );

    expect(await screen.findByTestId('proposal-status-badge')).toHaveTextContent(
      'waiting_for_approval',
    );
    expect(await screen.findByTestId('proposal-artifact-names')).toHaveTextContent('proposal.patch');
    expect(screen.getByTestId('proposal-artifact-names')).toHaveTextContent('proposal_summary.md');
  });

  it('calls POST only when eligible and enabled', async () => {
    mockGetProposalEligibility.mockResolvedValue(eligibleResponse);
    mockProposePatch.mockResolvedValue({
      task_id: 'task-new-1',
      objective: 'Patch',
      task: 'patch',
      status: 'waiting_for_approval',
      artifacts: [{ name: 'new.patch' }],
    } as never);

    render(<ProposalEligibilityPanel investigationId="inv-test-1" detail={baseDetail} />);

    const button = await screen.findByTestId('generate-patch-proposal-button');
    expect(button).toBeEnabled();

    await userEvent.click(button);

    await waitFor(() => {
      expect(mockProposePatch).toHaveBeenCalledWith('inv-test-1');
    });
    expect(mockProposePatch).toHaveBeenCalledTimes(1);
  });

  it('does not call POST when phase4b disabled', async () => {
    mockGetProposalEligibility.mockResolvedValue(disabledResponse);

    render(<ProposalEligibilityPanel investigationId="inv-test-1" detail={baseDetail} />);

    const button = await screen.findByTestId('generate-patch-proposal-button');
    expect(button).toBeDisabled();
    await userEvent.click(button);
    expect(mockProposePatch).not.toHaveBeenCalled();
  });
});
