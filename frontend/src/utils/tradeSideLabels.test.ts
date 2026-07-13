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

  it('maps position side to Long/Short labels', () => {
    expect(positionDirectionEs('LONG')).toBe('Long (Compra)');
    expect(positionDirectionEs('SHORT')).toBe('Short (Venta)');
  });

  it('uses green badge for buy/long and rose for sell/short', () => {
    expect(sideBadgeClass('BUY')).toContain('emerald');
    expect(sideBadgeClass('SELL')).toContain('rose');
  });
});
