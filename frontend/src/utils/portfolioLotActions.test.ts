import { describe, expect, it } from 'vitest';
import type { OpenOrder } from '@/app/api';
import type { OpenPositionLot } from '@/utils/orderProfitLoss';
import {
  dustCloseSide,
  isStableOrFiatAsset,
  lotNeedsProtection,
  lotNotionalUsd,
  portfolioLotActionKind,
  protectionCreateLabel,
} from './portfolioLotActions';

function makeLot(
  partial: Partial<OpenOrder> & { remainingQty: number; side: 'BUY' | 'SELL' }
): OpenPositionLot {
  const { remainingQty, side, ...orderFields } = partial;
  return {
    remainingQty,
    side,
    order: {
      order_id: 'oid-1',
      instrument_name: 'HBAR_USD',
      side,
      status: 'FILLED',
      quantity: String(remainingQty),
      price: '0.07',
      create_time: 1,
      update_time: 1,
      order_type: 'LIMIT',
      ...orderFields,
    } as OpenOrder,
  };
}

describe('portfolioLotActions', () => {
  it('treats USDT/USD as non-actionable stables', () => {
    expect(isStableOrFiatAsset('USDT')).toBe(true);
    expect(isStableOrFiatAsset('USD')).toBe(true);
    expect(isStableOrFiatAsset('ETH')).toBe(false);
  });

  it('routes sub-$5 lots to clean_dust', () => {
    const lot = makeLot({
      remainingQty: 11.9,
      side: 'SELL',
      has_linked_tp: false,
      has_linked_sl: false,
    });
    expect(lotNotionalUsd(lot, 0.067)).toBeCloseTo(11.9 * 0.067);
    expect(
      portfolioLotActionKind(lot, { assetCoin: 'HBAR', markPrice: 0.067 })
    ).toBe('clean_dust');
    expect(dustCloseSide(lot)).toBe('BUY');
  });

  it('routes material unprotected lots to create_protection', () => {
    const lot = makeLot({
      remainingQty: 0.03,
      side: 'SELL',
      instrument_name: 'ETH_USDT',
      has_linked_tp: false,
      has_linked_sl: true,
      price: '1900',
    });
    expect(
      portfolioLotActionKind(lot, { assetCoin: 'ETH', markPrice: 1875 })
    ).toBe('create_protection');
    expect(lotNeedsProtection(lot)).toEqual({ needSl: false, needTp: true });
    expect(protectionCreateLabel(false, true)).toBe('Crear TP');
  });

  it('does not flatten wallet-trim-hidden dust leftovers', () => {
    const lot = makeLot({
      remainingQty: 11.9,
      side: 'SELL',
      has_linked_tp: false,
      has_linked_sl: false,
    });
    lot.walletTrimHidden = true;
    expect(
      portfolioLotActionKind(lot, { assetCoin: 'HBAR', markPrice: 0.067 })
    ).toBe('none');
  });

  it('still offers Create SL/TP on material wallet-trim-hidden lots', () => {
    const lot = makeLot({
      remainingQty: 0.03,
      side: 'SELL',
      instrument_name: 'ETH_USDT',
      has_linked_tp: false,
      has_linked_sl: false,
      price: '1900',
    });
    lot.walletTrimHidden = true;
    expect(
      portfolioLotActionKind(lot, { assetCoin: 'ETH', markPrice: 1875 })
    ).toBe('create_protection');
  });

  it('returns none when fully protected or stable', () => {
    const protectedLot = makeLot({
      remainingQty: 1,
      side: 'SELL',
      has_linked_tp: true,
      has_linked_sl: true,
    });
    expect(
      portfolioLotActionKind(protectedLot, { assetCoin: 'ALGO', markPrice: 20 })
    ).toBe('none');
    expect(
      portfolioLotActionKind(protectedLot, { assetCoin: 'USDT', markPrice: 1 })
    ).toBe('none');
  });
});
