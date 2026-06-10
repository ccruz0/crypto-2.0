/** Session-scoped Bearer for governance / Jarvis control APIs (client-only). */

export const GOVERNANCE_TASK_VIEW_TOKEN_KEY = 'atp_governance_task_view_bearer';

export function readStoredGovernanceBearer(): string {
  if (typeof window === 'undefined') return '';
  try {
    return (sessionStorage.getItem(GOVERNANCE_TASK_VIEW_TOKEN_KEY) || '').trim();
  } catch {
    return '';
  }
}
