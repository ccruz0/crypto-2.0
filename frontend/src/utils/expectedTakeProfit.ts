/**
 * Expected Take Profit helpers shared by the Expected TP tab.
 *
 * Naked-short materiality matches the SL/TP checker dust floor
 * (`SL_TP_MIN_POSITION_USD` / `SYSTEM_CORE_MIN_POSITION_USD`, default $5)
 * so the amber banner only deep-links symbols the checker will actually scan.
 */

import type { ExpectedTPSummaryItem } from '@/app/api';

/** USD notional below which unprotected shorts are dust residue, not actionable. */
export const NAKED_SHORT_MIN_POSITION_USD = 5;

export function expectedTpNotionalUsd(item: ExpectedTPSummaryItem): number {
  const positionValue = Number(item.position_value);
  if (Number.isFinite(positionValue) && Math.abs(positionValue) > 0) {
    return Math.abs(positionValue);
  }

  const price = Number(item.current_price);
  const wallet = Math.abs(Number(item.wallet_balance) || 0);
  if (Number.isFinite(price) && price > 0 && wallet > 0) {
    return wallet * price;
  }

  const net = Math.abs(Number(item.net_qty) || 0);
  if (Number.isFinite(price) && price > 0 && net > 0) {
    return net * price;
  }

  return 0;
}

function isShortExposure(item: ExpectedTPSummaryItem): boolean {
  const side = (item.position_side || '').toUpperCase();
  const walletShort =
    typeof item.wallet_balance === 'number' && item.wallet_balance < -1e-12;
  return side === 'SHORT' || walletShort;
}

function hasZeroTpCoverage(item: ExpectedTPSummaryItem): boolean {
  const net = Math.abs(Number(item.net_qty) || 0);
  if (net <= 0) return false;
  return (Number(item.covered_qty) || 0) <= 0;
}

/** Short with 0 TP coverage and notional at/above the ops dust floor. */
export function isNakedShort(item: ExpectedTPSummaryItem): boolean {
  if (!isShortExposure(item) || !hasZeroTpCoverage(item)) return false;
  return expectedTpNotionalUsd(item) >= NAKED_SHORT_MIN_POSITION_USD;
}

/** Short with 0 TP coverage but below the dust floor (table hint only). */
export function isDustNakedShort(item: ExpectedTPSummaryItem): boolean {
  if (!isShortExposure(item) || !hasZeroTpCoverage(item)) return false;
  return expectedTpNotionalUsd(item) < NAKED_SHORT_MIN_POSITION_USD;
}
