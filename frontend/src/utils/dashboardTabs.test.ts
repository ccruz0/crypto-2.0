import { describe, expect, it } from 'vitest';
import { isDashboardTab, parseDashboardTabParam } from './dashboardTabs';

describe('dashboardTabs', () => {
  it('accepts known tab ids', () => {
    expect(isDashboardTab('watchlist')).toBe(true);
    expect(isDashboardTab('monitoring')).toBe(true);
    expect(isDashboardTab('version-history')).toBe(true);
  });

  it('rejects unknown or empty values', () => {
    expect(isDashboardTab(null)).toBe(false);
    expect(isDashboardTab(undefined)).toBe(false);
    expect(isDashboardTab('')).toBe(false);
    expect(isDashboardTab('Watchlist')).toBe(false);
    expect(isDashboardTab('not-a-tab')).toBe(false);
  });

  it('parseDashboardTabParam returns null for invalid', () => {
    expect(parseDashboardTabParam('watchlist')).toBe('watchlist');
    expect(parseDashboardTabParam('portfolio')).toBe('portfolio');
    expect(parseDashboardTabParam('nope')).toBeNull();
    expect(parseDashboardTabParam(null)).toBeNull();
  });
});
