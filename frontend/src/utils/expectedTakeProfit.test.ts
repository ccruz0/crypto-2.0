import { describe, expect, it } from 'vitest';
import type { ExpectedTPSummaryItem } from '@/app/api';
import {
  NAKED_SHORT_MIN_POSITION_USD,
  expectedTpNotionalUsd,
  isDustNakedShort,
  isNakedShort,
} from './expectedTakeProfit';

function item(partial: Partial<ExpectedTPSummaryItem>): ExpectedTPSummaryItem {
  return {
    symbol: 'TEST_USD',
    net_qty: 1,
    position_value: 0,
    covered_qty: 0,
    uncovered_qty: 1,
    total_expected_profit: 0,
    ...partial,
  };
}

describe('expectedTakeProfit naked-short materiality', () => {
  it('uses absolute position_value as notional when present', () => {
    expect(expectedTpNotionalUsd(item({ position_value: -0.8 }))).toBeCloseTo(0.8);
    expect(expectedTpNotionalUsd(item({ position_value: 12 }))).toBe(12);
  });

  it('falls back to wallet × mark when position_value is zero', () => {
    expect(
      expectedTpNotionalUsd(
        item({
          position_value: 0,
          wallet_balance: -11.9,
          current_price: 0.067,
        })
      )
    ).toBeCloseTo(11.9 * 0.067);
  });

  it('flags material naked shorts for the banner (≥ $5)', () => {
    const material = item({
      symbol: 'APT_USD',
      position_side: 'SHORT',
      wallet_balance: -20,
      net_qty: 20,
      covered_qty: 0,
      position_value: NAKED_SHORT_MIN_POSITION_USD,
    });
    expect(isNakedShort(material)).toBe(true);
    expect(isDustNakedShort(material)).toBe(false);
  });

  it('treats HBAR/AAVE-style residue as dust, not banner-worthy', () => {
    const dustRows = [
      item({
        symbol: 'HBAR_USD',
        position_side: 'SHORT',
        wallet_balance: -11.9,
        net_qty: 11.9,
        covered_qty: 0,
        position_value: 0.8,
      }),
      item({
        symbol: 'AAVE_USD',
        position_side: 'SHORT',
        wallet_balance: -0.0067,
        net_qty: 0.0067,
        covered_qty: 0,
        position_value: 0.59,
      }),
      item({
        symbol: 'DOT_USD',
        position_side: 'SHORT',
        wallet_balance: -0.32,
        net_qty: 0.32,
        covered_qty: 0,
        position_value: 0.26,
      }),
      item({
        symbol: 'SOL_USD',
        position_side: 'SHORT',
        wallet_balance: -0.0018,
        net_qty: 0.0018,
        covered_qty: 0,
        position_value: 0.14,
      }),
    ];

    for (const row of dustRows) {
      expect(isNakedShort(row)).toBe(false);
      expect(isDustNakedShort(row)).toBe(true);
    }
  });

  it('does not flag covered shorts or longs', () => {
    expect(
      isNakedShort(
        item({
          position_side: 'SHORT',
          covered_qty: 10,
          net_qty: 10,
          position_value: 20,
        })
      )
    ).toBe(false);
    expect(
      isDustNakedShort(
        item({
          position_side: 'SHORT',
          covered_qty: 10,
          net_qty: 10,
          position_value: 0.5,
        })
      )
    ).toBe(false);
    expect(
      isNakedShort(
        item({
          position_side: 'LONG',
          wallet_balance: 5,
          covered_qty: 0,
          position_value: 50,
        })
      )
    ).toBe(false);
  });

  it('treats wallet_balance < 0 as short even when side is MIXED', () => {
    const mixedDust = item({
      position_side: 'MIXED',
      wallet_balance: -0.5,
      net_qty: 0.5,
      covered_qty: 0,
      position_value: 0.4,
    });
    expect(isNakedShort(mixedDust)).toBe(false);
    expect(isDustNakedShort(mixedDust)).toBe(true);
  });
});
