export type PositionSide = 'LONG' | 'SHORT';
export type TradeSide = 'BUY' | 'SELL';

export function normalizeTradeSide(side: string | null | undefined): TradeSide {
  return (side || '').toUpperCase() === 'SELL' ? 'SELL' : 'BUY';
}

/** Spanish label for a single order side (BUY → Compra, SELL → Venta). */
export function sideLabelEs(side: string | null | undefined): string {
  return normalizeTradeSide(side) === 'SELL' ? 'Venta' : 'Compra';
}

/** Spanish label for position direction (Long/Short + Compra/Venta). */
export function positionDirectionEs(positionSide: string | null | undefined): string {
  return (positionSide || '').toUpperCase() === 'SHORT' ? 'Short (Venta)' : 'Long (Compra)';
}

export function sideBadgeClass(side: string | null | undefined): string {
  return normalizeTradeSide(side) === 'SELL'
    ? 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-200'
    : 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200';
}

export function positionBadgeClass(positionSide: string | null | undefined): string {
  return (positionSide || '').toUpperCase() === 'SHORT'
    ? 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-200'
    : 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200';
}
