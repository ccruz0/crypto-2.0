export type PositionSide = 'LONG' | 'SHORT' | 'MIXED';
export type TradeSide = 'BUY' | 'SELL';

export function normalizeTradeSide(side: string | null | undefined): TradeSide {
  return (side || '').toUpperCase() === 'SELL' ? 'SELL' : 'BUY';
}

export function normalizePositionSide(
  positionSide: string | null | undefined
): PositionSide {
  const value = (positionSide || '').toUpperCase();
  if (value === 'SHORT') return 'SHORT';
  if (value === 'MIXED') return 'MIXED';
  return 'LONG';
}

/** Spanish label for a single order side (BUY → Compra, SELL → Venta). */
export function sideLabelEs(side: string | null | undefined): string {
  return normalizeTradeSide(side) === 'SELL' ? 'Venta' : 'Compra';
}

/** Spanish label for position direction (Long/Short/Mixto). */
export function positionDirectionEs(positionSide: string | null | undefined): string {
  const side = normalizePositionSide(positionSide);
  if (side === 'SHORT') return 'Short (Venta)';
  if (side === 'MIXED') return 'Mixto (Long + Short)';
  return 'Long (Compra)';
}

export function sideBadgeClass(side: string | null | undefined): string {
  return normalizeTradeSide(side) === 'SELL'
    ? 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-200'
    : 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200';
}

export function positionBadgeClass(positionSide: string | null | undefined): string {
  const side = normalizePositionSide(positionSide);
  if (side === 'SHORT') {
    return 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-200';
  }
  if (side === 'MIXED') {
    return 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200';
  }
  return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200';
}
