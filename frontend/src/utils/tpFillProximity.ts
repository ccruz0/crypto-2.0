/**
 * Fill proximity for an active take-profit order.
 *
 * Path progress from entry → TP. 100% means mark is at or through the TP price
 * (ready / about to fill). 0% means mark is at or on the wrong side of entry.
 *
 * Formula (LONG and SHORT):
 *   span = |tp - entry|
 *   if mark is at/past TP in the fill direction → 100
 *   else proximity = clamp(0, 100, 100 * (1 - |tp - mark| / span))
 *
 * Equivalent when mark is between entry and TP:
 *   LONG  (tp > entry): (mark - entry) / (tp - entry) * 100
 *   SHORT (tp < entry): (entry - mark) / (entry - tp) * 100
 *
 * This is NOT coverage ratio (qty protected / position qty).
 */

const EPS = 1e-12;

export type TpFillProximityInput = {
  mark: number | null | undefined;
  entry: number | null | undefined;
  tp: number | null | undefined;
};

/**
 * Returns fill proximity in [0, 100], or null when inputs are missing/invalid.
 */
export function tpFillProximityPct({
  mark,
  entry,
  tp,
}: TpFillProximityInput): number | null {
  if (
    mark == null ||
    entry == null ||
    tp == null ||
    !Number.isFinite(mark) ||
    !Number.isFinite(entry) ||
    !Number.isFinite(tp)
  ) {
    return null;
  }
  if (mark <= 0 || entry <= 0 || tp <= 0) {
    return null;
  }

  const span = Math.abs(tp - entry);
  if (span < EPS) {
    return Math.abs(mark - tp) < EPS ? 100 : null;
  }

  // Past TP in the fill direction → fully proximate
  if (tp >= entry) {
    // Long-style: TP above entry; fills when mark rises to/through TP
    if (mark >= tp) return 100;
  } else {
    // Short-style: TP below entry; fills when mark falls to/through TP
    if (mark <= tp) return 100;
  }

  const raw = 100 * (1 - Math.abs(tp - mark) / span);
  if (!Number.isFinite(raw)) return null;
  return Math.min(100, Math.max(0, raw));
}

/** Highest proximity among a list of TP proximities (ignores nulls). */
export function maxTpFillProximityPct(
  values: Array<number | null | undefined>
): number | null {
  let max: number | null = null;
  for (const v of values) {
    if (v == null || !Number.isFinite(v)) continue;
    if (max == null || v > max) max = v;
  }
  return max;
}

/** Spanish UI: format proximity for display (e.g. "82%"). */
export function formatTpFillProximityPct(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return `${Math.round(value)}%`;
}

/**
 * Highlight class for summary "TP cerca %" when near fill.
 * >= 95 → red (imminent), >= 90 → amber (close), else muted.
 */
export function tpFillProximityToneClass(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) {
    return 'text-gray-400 dark:text-gray-500';
  }
  if (value >= 95) {
    return 'text-red-600 dark:text-red-400 font-semibold';
  }
  if (value >= 90) {
    return 'text-amber-600 dark:text-amber-400 font-semibold';
  }
  return 'text-gray-700 dark:text-gray-300';
}
