import { describe, expect, it } from 'vitest';
import { formatFixed, isFiniteNumber } from '@/utils/formatting';

describe('isFiniteNumber', () => {
  it('accepts finite numbers including 0', () => {
    expect(isFiniteNumber(0)).toBe(true);
    expect(isFiniteNumber(42.5)).toBe(true);
  });

  it('rejects null/undefined/NaN (the Watchlist tooltip crash case)', () => {
    // `null !== undefined` is true — that old guard still called .toFixed on null
    expect(null !== undefined).toBe(true);
    expect(isFiniteNumber(null)).toBe(false);
    expect(isFiniteNumber(undefined)).toBe(false);
    expect(isFiniteNumber(Number.NaN)).toBe(false);
  });
});

describe('formatFixed', () => {
  it('formats finite numbers', () => {
    expect(formatFixed(12.3456)).toBe('12.35');
    expect(formatFixed(1, 0)).toBe('1');
  });

  it('never throws on null/undefined and returns empty placeholder', () => {
    expect(() => formatFixed(null)).not.toThrow();
    expect(() => formatFixed(undefined)).not.toThrow();
    expect(formatFixed(null)).toBe('N/A');
    expect(formatFixed(undefined, 2, '-')).toBe('-');
  });

  it('matches the previous unsafe tooltip pattern safely', () => {
    const signal = { rsi: null as number | null, volume_ratio: null as number | null };
    // Old: signal.rsi !== undefined && signal.rsi.toFixed(2)  → throws
    expect(() => {
      if (signal.rsi !== undefined) signal.rsi!.toFixed(2);
    }).toThrow();
    // New:
    expect(isFiniteNumber(signal.rsi) ? formatFixed(signal.rsi) : null).toBeNull();
    expect(formatFixed(signal.volume_ratio)).toBe('N/A');
  });
});
