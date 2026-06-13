import { describe, expect, it } from 'vitest';
import {
  canGeneratePatchProposal,
  formatEligibilityReason,
  getMatchingFixTemplate,
  isPhase4bProposalsDisabled,
} from '@/app/components/tabs/proposalEligibilityUtils';
import type { JarvisProposalEligibility } from '@/app/api';

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
  reasons: ['phase4b_proposals_disabled', 'investigation_not_completed'],
  confidence: 75,
  fix_template_candidates: [
    {
      fix_template_id: 'orders.trigger_50001_cache_independent',
      match: 'Trigger order API failure blocks cache updates',
    },
  ],
  existing_proposal_task_id: null,
};

describe('proposalEligibilityUtils', () => {
  it('detects phase4b_proposals_disabled', () => {
    expect(isPhase4bProposalsDisabled(['phase4b_proposals_disabled'])).toBe(true);
    expect(isPhase4bProposalsDisabled([])).toBe(false);
  });

  it('blocks proposal when phase4b is disabled even if eligible flag is true', () => {
    expect(canGeneratePatchProposal({ ...eligibleResponse, reasons: ['phase4b_proposals_disabled'] })).toBe(
      false,
    );
  });

  it('allows proposal when eligible and phase4b enabled', () => {
    expect(canGeneratePatchProposal(eligibleResponse)).toBe(true);
    expect(canGeneratePatchProposal(disabledResponse)).toBe(false);
    expect(canGeneratePatchProposal(null)).toBe(false);
  });

  it('returns matching fix template candidate', () => {
    expect(getMatchingFixTemplate(eligibleResponse)?.fix_template_id).toBe(
      'orders.trigger_50001_cache_independent',
    );
  });

  it('formats eligibility reasons for display', () => {
    expect(formatEligibilityReason('phase4b_proposals_disabled')).toBe('phase4b proposals disabled');
  });
});
