/**
 * Portfolio lot action helpers: material Create SL/TP vs dust flatten.
 * Dust floor matches SL/TP checker / Expected TP naked banner ($5).
 */

import type { OpenOrder } from '@/app/api';
import type { OpenPositionLot } from '@/utils/orderProfitLoss';
import { getOrderPrice } from '@/utils/orderProfitLoss';
import { NAKED_SHORT_MIN_POSITION_USD } from '@/utils/expectedTakeProfit';

export { NAKED_SHORT_MIN_POSITION_USD as PORTFOLIO_DUST_MIN_USD };

const STABLE_OR_FIAT = new Set([
  'USDT',
  'USD',
  'USDC',
  'BUSD',
  'DAI',
  'TUSD',
  'EUR',
  'GBP',
  'JPY',
]);

export function isStableOrFiatAsset(coin: string): boolean {
  const upper = (coin || '').toUpperCase();
  const base = upper.includes('_') ? upper.split('_')[0] : upper;
  return STABLE_OR_FIAT.has(base);
}

export function lotNotionalUsd(
  lot: OpenPositionLot,
  markPrice: number | null | undefined
): number {
  const qty = Math.abs(Number(lot.remainingQty) || 0);
  if (qty <= 0) return 0;
  const mark = Number(markPrice);
  if (Number.isFinite(mark) && mark > 0) return qty * mark;
  const entry = getOrderPrice(lot.order);
  if (Number.isFinite(entry) && entry > 0) return qty * entry;
  return 0;
}

export function lotNeedsProtection(lot: OpenPositionLot): {
  needSl: boolean;
  needTp: boolean;
} {
  const order = lot.order;
  return {
    needSl: order.has_linked_sl !== true,
    needTp: order.has_linked_tp !== true,
  };
}

export type PortfolioLotActionKind = 'create_protection' | 'clean_dust' | 'none';

export function portfolioLotActionKind(
  lot: OpenPositionLot,
  opts: { assetCoin: string; markPrice: number | null | undefined }
): PortfolioLotActionKind {
  if (isStableOrFiatAsset(opts.assetCoin)) return 'none';
  if (!lot.order?.order_id) return 'none';
  const notional = lotNotionalUsd(lot, opts.markPrice);
  if (notional <= 0) return 'none';
  // Wallet-trim extras are not live wallet inventory — never market-flatten them.
  if (lot.walletTrimHidden) {
    if (notional < NAKED_SHORT_MIN_POSITION_USD) return 'none';
    const { needSl, needTp } = lotNeedsProtection(lot);
    if (needSl || needTp) return 'create_protection';
    return 'none';
  }
  if (notional < NAKED_SHORT_MIN_POSITION_USD) return 'clean_dust';
  const { needSl, needTp } = lotNeedsProtection(lot);
  if (needSl || needTp) return 'create_protection';
  return 'none';
}

export function dustCloseSide(lot: OpenPositionLot): 'BUY' | 'SELL' {
  return lot.side === 'SELL' ? 'BUY' : 'SELL';
}

export function resolveLotInstrument(
  lot: OpenPositionLot,
  fallbackInstrument: string | null
): string | null {
  const fromOrder = (lot.order.instrument_name || '').toUpperCase();
  if (fromOrder.includes('_')) return fromOrder;
  if (fallbackInstrument) return fallbackInstrument.toUpperCase();
  return null;
}

export function protectionCreateLabel(needSl: boolean, needTp: boolean): string {
  if (needSl && needTp) return 'Crear SL/TP';
  if (needSl) return 'Crear SL';
  return 'Crear TP';
}

/** Expose order fields used by action gating (for tests). */
export function orderProtectionFlags(order: OpenOrder): {
  hasSl: boolean;
  hasTp: boolean;
} {
  return {
    hasSl: order.has_linked_sl === true,
    hasTp: order.has_linked_tp === true,
  };
}
