/**
 * Watchlist Trade / Margin / Alert buttons must follow the database.
 *
 * Overlay maps (React state) are only for in-flight optimistic clicks.
 * The TopCoin / dashboard row is the last value read from watchlist_items.
 * localStorage must not decide YES/NO — that is what made Margin look green
 * while the bot read a different flag.
 */
export function watchlistButtonOn(
  overlay: Record<string, boolean> | undefined,
  symbolKey: string,
  dbValue: boolean | null | undefined,
): boolean {
  if (symbolKey && overlay && Object.prototype.hasOwnProperty.call(overlay, symbolKey)) {
    return Boolean(overlay[symbolKey]);
  }
  return Boolean(dbValue);
}

/** Collect boolean watchlist flags from API rows using uppercase keys. */
export function watchlistFlagsFromCoins(
  coins: Array<{
    instrument_name?: string;
    symbol?: string;
    trade_enabled?: boolean | null;
    trade_on_margin?: boolean | null;
    alert_enabled?: boolean | null;
    buy_alert_enabled?: boolean | null;
    sell_alert_enabled?: boolean | null;
  }>,
): {
  trade: Record<string, boolean>;
  margin: Record<string, boolean>;
  alert: Record<string, boolean>;
  buyAlert: Record<string, boolean>;
  sellAlert: Record<string, boolean>;
} {
  const trade: Record<string, boolean> = {};
  const margin: Record<string, boolean> = {};
  const alert: Record<string, boolean> = {};
  const buyAlert: Record<string, boolean> = {};
  const sellAlert: Record<string, boolean> = {};

  for (const coin of coins) {
    const key = (coin.instrument_name || coin.symbol || '').toUpperCase();
    if (!key) continue;
    if (coin.trade_enabled !== undefined && coin.trade_enabled !== null) {
      trade[key] = Boolean(coin.trade_enabled);
    }
    if (coin.trade_on_margin !== undefined && coin.trade_on_margin !== null) {
      margin[key] = Boolean(coin.trade_on_margin);
    }
    if (coin.alert_enabled !== undefined && coin.alert_enabled !== null) {
      alert[key] = Boolean(coin.alert_enabled);
    }
    if (coin.buy_alert_enabled !== undefined && coin.buy_alert_enabled !== null) {
      buyAlert[key] = Boolean(coin.buy_alert_enabled);
    }
    if (coin.sell_alert_enabled !== undefined && coin.sell_alert_enabled !== null) {
      sellAlert[key] = Boolean(coin.sell_alert_enabled);
    }
  }

  return { trade, margin, alert, buyAlert, sellAlert };
}
