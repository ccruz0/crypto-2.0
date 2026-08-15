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
    // Explicit false must stay false (optimistic OFF). Do not delete the key.
    return Boolean(overlay[symbolKey]);
  }
  return Boolean(dbValue);
}

/** Exchange allows SHORT / SELL alerts. Missing field (old API) keeps the button enabled. */
export function exchangeAllowsShortAlert(
  marginSellEnabled: boolean | null | undefined,
): boolean {
  return marginSellEnabled !== false;
}

/** S button is ON only if the DB/overlay flag is on AND the exchange allows SHORT.
 *  ON means "open a new independent short" — never close a long. */
export function sellAlertButtonOn(
  overlay: Record<string, boolean> | undefined,
  symbolKey: string,
  dbSellAlert: boolean | null | undefined,
  marginSellEnabled: boolean | null | undefined,
): boolean {
  if (!exchangeAllowsShortAlert(marginSellEnabled)) {
    return false;
  }
  return watchlistButtonOn(overlay, symbolKey, dbSellAlert);
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

/**
 * Amount USD overlay vs watchlist_items.trade_amount_usd.
 * Missing overlay must not keep a stale localStorage $10 when DB is null (DGB_USD).
 */
export function watchlistAmountText(
  overlay: Record<string, string> | undefined,
  symbolKey: string,
  dbValue: number | string | null | undefined,
): string | null {
  if (symbolKey && overlay && Object.prototype.hasOwnProperty.call(overlay, symbolKey)) {
    const raw = overlay[symbolKey];
    if (raw === '' || raw == null) return null;
    return String(raw);
  }
  if (dbValue === undefined || dbValue === null || dbValue === '') return null;
  return String(dbValue);
}

/** Build a replace-map of Amount USD from API rows. Null DB amounts are omitted. */
export function watchlistAmountsFromItems(
  items: Array<{
    instrument_name?: string;
    symbol?: string;
    trade_amount_usd?: number | string | null;
  }>,
): Record<string, string> {
  const amounts: Record<string, string> = {};
  for (const item of items) {
    const key = (item.instrument_name || item.symbol || '').toUpperCase();
    if (!key) continue;
    if (item.trade_amount_usd === undefined || item.trade_amount_usd === null || item.trade_amount_usd === '') {
      continue;
    }
    amounts[key] = String(item.trade_amount_usd);
  }
  return amounts;
}
