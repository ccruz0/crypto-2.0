import { describe, expect, it } from 'vitest';
import {
  formatTpFillProximityPct,
  maxTpFillProximityPct,
  tpFillProximityPct,
  tpFillProximityToneClass,
} from './tpFillProximity';

describe('tpFillProximityPct', () => {
  it('LONG: 0% at entry, 50% halfway, 100% at/past TP', () => {
    expect(tpFillProximityPct({ mark: 100, entry: 100, tp: 200 })).toBe(0);
    expect(tpFillProximityPct({ mark: 150, entry: 100, tp: 200 })).toBe(50);
    expect(tpFillProximityPct({ mark: 200, entry: 100, tp: 200 })).toBe(100);
    expect(tpFillProximityPct({ mark: 220, entry: 100, tp: 200 })).toBe(100);
  });

  it('LONG: underwater (mark below entry) clamps to 0%', () => {
    // BTC-style: mark 64321, entry ~71100, TP 78000 → still below entry → 0%
    expect(
      tpFillProximityPct({ mark: 64321, entry: 71100, tp: 78000 })
    ).toBe(0);
  });

  it('LONG: near TP approaches 100%', () => {
    expect(
      tpFillProximityPct({ mark: 77500, entry: 71100, tp: 78000 })
    ).toBeCloseTo(100 * (1 - Math.abs(78000 - 77500) / Math.abs(78000 - 71100)), 5);
    expect(tpFillProximityPct({ mark: 77900, entry: 71100, tp: 78000 })).toBeGreaterThan(95);
  });

  it('SHORT: 0% at entry, 50% halfway, 100% at/past TP', () => {
    expect(tpFillProximityPct({ mark: 200, entry: 200, tp: 100 })).toBe(0);
    expect(tpFillProximityPct({ mark: 150, entry: 200, tp: 100 })).toBe(50);
    expect(tpFillProximityPct({ mark: 100, entry: 200, tp: 100 })).toBe(100);
    expect(tpFillProximityPct({ mark: 90, entry: 200, tp: 100 })).toBe(100);
  });

  it('SHORT: mark above entry (away from TP) clamps to 0%', () => {
    expect(tpFillProximityPct({ mark: 250, entry: 200, tp: 100 })).toBe(0);
  });

  it('returns null for missing or non-positive inputs', () => {
    expect(tpFillProximityPct({ mark: null, entry: 100, tp: 200 })).toBeNull();
    expect(tpFillProximityPct({ mark: 150, entry: 0, tp: 200 })).toBeNull();
    expect(tpFillProximityPct({ mark: 150, entry: 100, tp: undefined })).toBeNull();
  });
});

describe('maxTpFillProximityPct', () => {
  it('returns the highest proximity among active TPs', () => {
    expect(maxTpFillProximityPct([10, 82, 40, null])).toBe(82);
    expect(maxTpFillProximityPct([null, undefined])).toBeNull();
  });
});

describe('format / tone helpers', () => {
  it('formats Spanish-friendly percent', () => {
    expect(formatTpFillProximityPct(82.4)).toBe('82%');
    expect(formatTpFillProximityPct(null)).toBe('—');
  });

  it('uses amber/red near fill thresholds', () => {
    expect(tpFillProximityToneClass(96)).toContain('red');
    expect(tpFillProximityToneClass(91)).toContain('amber');
    expect(tpFillProximityToneClass(50)).not.toContain('red');
  });
});
