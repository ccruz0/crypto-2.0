/**
 * Watchlist row identity. USD and USDT pairs are different instruments
 * (separate watchlist_items rows, flags, and sizes) and must both render.
 */
export function dedupeWatchlistCoins<T extends { instrument_name?: string }>(
  coins: T[],
): T[] {
  const seen = new Set<string>();
  const kept: T[] = [];
  for (const coin of coins) {
    const key = (coin.instrument_name || '').toUpperCase();
    if (!key) continue;
    if (seen.has(key)) continue;
    seen.add(key);
    kept.push(coin);
  }
  return kept;
}
