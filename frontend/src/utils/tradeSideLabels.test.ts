import { describe, expect, it } from 'vitest';
import {
  positionDirectionEs,
  sideBadgeClass,
  sideLabelEs,
} from './tradeSideLabels';

describe('tradeSideLabels', () => {
  it('maps BUY/SELL to Compra/Venta', () => {
    expect(sideLabelEs('BUY')).toBe('Compra');
    expect(sideLabelEs('SELL')).toBe('Venta');
  });

  it('maps position side to Long/Short/Mixto labels', () => {
    expect(positionDirectionEs('LONG')).toBe('Long (Compra)');
    expect(positionDirectionEs('SHORT')).toBe('Short (Venta)');
    expect(positionDirectionEs('MIXED')).toBe('Mixto (Long + Short)');
  });

  it('uses green badge for buy/long and rose for sell/short', () => {
    expect(sideBadgeClass('BUY')).toContain('emerald');
    expect(sideBadgeClass('SELL')).toContain('rose');
  });
});
