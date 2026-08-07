import { describe, expect, it } from 'vitest';
import {
  positionDirectionEn,
  positionDirectionEs,
  sideBadgeClass,
  sideLabelEn,
  sideLabelEs,
} from './tradeSideLabels';

describe('tradeSideLabels', () => {
  it('maps BUY/SELL to Compra/Venta', () => {
    expect(sideLabelEs('BUY')).toBe('Compra');
    expect(sideLabelEs('SELL')).toBe('Venta');
  });

  it('maps BUY/SELL to Buy/Sell (EN)', () => {
    expect(sideLabelEn('BUY')).toBe('Buy');
    expect(sideLabelEn('SELL')).toBe('Sell');
  });

  it('maps position side to Long/Short/Mixto labels', () => {
    expect(positionDirectionEs('LONG')).toBe('Long (Compra)');
    expect(positionDirectionEs('SHORT')).toBe('Short (Venta)');
    expect(positionDirectionEs('MIXED')).toBe('Mixto (Long + Short)');
  });

  it('maps position side to English labels', () => {
    expect(positionDirectionEn('LONG')).toBe('Long (Buy)');
    expect(positionDirectionEn('SHORT')).toBe('Short (Sell)');
    expect(positionDirectionEn('MIXED')).toBe('Mixed (Long + Short)');
  });

  it('uses green badge for buy/long and rose for sell/short', () => {
    expect(sideBadgeClass('BUY')).toContain('emerald');
    expect(sideBadgeClass('SELL')).toContain('rose');
  });
});
