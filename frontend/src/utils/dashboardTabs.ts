import type { DashboardTab } from '@/app/components/DashboardTabNav';

/** All dashboard tab ids that may appear in `?tab=` (incl. Version History). */
export const DASHBOARD_TAB_IDS: readonly DashboardTab[] = [
  'portfolio',
  'watchlist',
  'signals',
  'orders',
  'expected-take-profit',
  'executed-orders',
  'version-history',
  'monitoring',
  'jarvis',
  'production-diagnostics',
  'scheduled-investigations',
  'jarvis-alerts',
  'jarvis-daily-reports',
  'jarvis-analytics',
  'jarvis-improvement',
] as const;

const VALID_TABS = new Set<string>(DASHBOARD_TAB_IDS);

export function isDashboardTab(value: string | null | undefined): value is DashboardTab {
  return typeof value === 'string' && VALID_TABS.has(value);
}

/** Parse `?tab=` query value; unknown/missing → null (caller defaults to portfolio). */
export function parseDashboardTabParam(value: string | null | undefined): DashboardTab | null {
  return isDashboardTab(value) ? value : null;
}
