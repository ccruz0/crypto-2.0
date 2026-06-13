import type { JarvisProposalEligibility } from '@/app/api';

export function isPhase4bProposalsDisabled(reasons: string[]): boolean {
  return reasons.includes('phase4b_proposals_disabled');
}

export function canGeneratePatchProposal(
  eligibility: JarvisProposalEligibility | null | undefined,
): boolean {
  if (!eligibility) return false;
  if (isPhase4bProposalsDisabled(eligibility.reasons)) return false;
  return eligibility.eligible;
}

export function formatEligibilityReason(reason: string): string {
  return reason.replace(/_/g, ' ');
}

export function getMatchingFixTemplate(
  eligibility: JarvisProposalEligibility | null | undefined,
) {
  return eligibility?.fix_template_candidates?.[0] ?? null;
}
