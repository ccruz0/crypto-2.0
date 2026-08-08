/**
 * Portfolio P&L summary helpers.
 * Realized = closes in selected period (via buildRealizedPnlByOrderId).
 * Unrealized = open lots at mark now (not period-filtered).
 */
import type { OpenOrder, PortfolioAsset, TopCoin } from '@/app/api';
import {
  buildRealizedPnlByOrderId,
  calculateOpenLotsAggregateProfitLoss,
  dedupeProtectionCloseTwins,
  getAssetBaseSymbol,
  getExecutedProtectionRole,
  getOpenPositionLotsForAsset,
  getOrderExecutionTime,
  isFilledCloseOrder,
  resolveCurrentPrice,
  type OrderProfitLoss,
} from '@/utils/orderProfitLoss';

export type PnLPeriodPreset = 'today' | '7d' | '30d' | 'month' | 'year' | 'custom';

export interface PnLPeriodRange {
  startMs: number;
  endMs: number;
  label: string;
}

export interface PnLSymbolBreakdown {
  symbol: string;
  pnl: number;
  closes: number;
}

export interface PnLSummaryResult {
  realizedPL: number;
  unrealizedPL: number;
  totalPL: number;
  closeCount: number;
  winCount: number;
  winRate: number | null;
  /** FILLED TAKE_PROFIT fills in the selected period (after twin dedupe). */
  tpExecutedCount: number;
  /** FILLED STOP_LOSS fills in the selected period (after twin dedupe). */
  slExecutedCount: number;
  topSymbols: PnLSymbolBreakdown[];
  period: PnLPeriodRange;
}

export interface CustomDateRange {
  from: string; // YYYY-MM-DD
  to: string; // YYYY-MM-DD
}

function startOfLocalDay(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate(), 0, 0, 0, 0);
}

function endOfLocalDay(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate(), 23, 59, 59, 999);
}

function parseLocalDateInput(value: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec((value || '').trim());
  if (!m) return null;
  const y = Number(m[1]);
  const mo = Number(m[2]) - 1;
  const day = Number(m[3]);
  const d = new Date(y, mo, day);
  if (d.getFullYear() !== y || d.getMonth() !== mo || d.getDate() !== day) return null;
  return d;
}

export function getPnLPeriodRange(
  preset: PnLPeriodPreset,
  now: Date = new Date(),
  custom?: CustomDateRange | null
): PnLPeriodRange {
  const endNow = now.getTime();

  if (preset === 'custom' && custom?.from && custom?.to) {
    const from = parseLocalDateInput(custom.from);
    const to = parseLocalDateInput(custom.to);
    if (from && to) {
      const start = startOfLocalDay(from).getTime();
      const end = endOfLocalDay(to).getTime();
      const lo = Math.min(start, end);
      const hi = Math.max(start, end);
      return {
        startMs: lo,
        endMs: hi,
        label: `${custom.from} → ${custom.to}`,
      };
    }
  }

  if (preset === 'today') {
    const start = startOfLocalDay(now).getTime();
    return { startMs: start, endMs: endNow, label: 'Today' };
  }

  if (preset === '7d') {
    const start = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000).getTime();
    return { startMs: start, endMs: endNow, label: 'Last 7 days' };
  }

  if (preset === '30d') {
    const start = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000).getTime();
    return { startMs: start, endMs: endNow, label: 'Last 30 days' };
  }

  if (preset === 'month') {
    const start = new Date(now.getFullYear(), now.getMonth(), 1, 0, 0, 0, 0).getTime();
    return {
      startMs: start,
      endMs: endNow,
      label: now.toLocaleString(undefined, { month: 'long', year: 'numeric' }),
    };
  }

  // year (default fallback)
  const start = new Date(now.getFullYear(), 0, 1, 0, 0, 0, 0).getTime();
  return {
    startMs: start,
    endMs: endNow,
    label: String(now.getFullYear()),
  };
}

function instrumentKey(order: OpenOrder): string {
  return (order.instrument_name || '').toUpperCase() || 'UNKNOWN';
}

/**
 * Compute P&L summary for Portfolio panel.
 * - Realized: matched closes whose execution time falls in the period
 * - Unrealized: aggregate open-lot mark-to-market (ignores period)
 */
export function computePnLSummary(args: {
  executedOrders: OpenOrder[];
  portfolioAssets?: PortfolioAsset[] | null;
  topCoins?: TopCoin[] | null;
  preset: PnLPeriodPreset;
  customRange?: CustomDateRange | null;
  now?: Date;
  topN?: number;
}): PnLSummaryResult {
  const period = getPnLPeriodRange(args.preset, args.now ?? new Date(), args.customRange);
  const topN = args.topN ?? 5;
  const orders = dedupeProtectionCloseTwins(
    Array.isArray(args.executedOrders) ? args.executedOrders : []
  );

  // Realized map attributes P&L to both entry and close ids — only sum close fills
  // so period totals are not double-counted.
  const realizedMap = buildRealizedPnlByOrderId(orders);
  const orderById = new Map<string, OpenOrder>();
  for (const o of orders) {
    if (o?.order_id) orderById.set(o.order_id, o);
  }

  let realizedPL = 0;
  let closeCount = 0;
  let winCount = 0;
  let tpExecutedCount = 0;
  let slExecutedCount = 0;
  const bySymbol = new Map<string, { pnl: number; closes: number }>();

  for (const [orderId, pnlData] of realizedMap.entries()) {
    if (!pnlData?.available || !pnlData.isRealized) continue;
    const order = orderById.get(orderId);
    if (!order || !isFilledCloseOrder(order)) continue;
    const t = getOrderExecutionTime(order);
    if (!t || t < period.startMs || t > period.endMs) continue;

    const pnl = Number(pnlData.pnl) || 0;
    realizedPL += pnl;
    closeCount += 1;
    if (pnl > 0) winCount += 1;

    const sym = instrumentKey(order);
    const prev = bySymbol.get(sym) || { pnl: 0, closes: 0 };
    prev.pnl += pnl;
    prev.closes += 1;
    bySymbol.set(sym, prev);
  }

  // Count executed TP/SL fills in the same period window (order_role / FILL data).
  for (const order of orders) {
    const protectionRole = getExecutedProtectionRole(order);
    if (!protectionRole) continue;
    const t = getOrderExecutionTime(order);
    if (!t || t < period.startMs || t > period.endMs) continue;
    if (protectionRole === 'TAKE_PROFIT') tpExecutedCount += 1;
    else slExecutedCount += 1;
  }

  let unrealizedPL = 0;
  const assets = args.portfolioAssets || [];
  const topCoins = args.topCoins || [];

  for (const asset of assets) {
    if (!asset?.coin) continue;
    const balance = Number(asset.balance);
    if (!Number.isFinite(balance) || Math.abs(balance) < 1e-12) continue;

    const lots = getOpenPositionLotsForAsset(orders, asset.coin, balance);
    if (!lots.length) continue;

    const sampleInstrument =
      lots[0]?.order?.instrument_name ||
      `${getAssetBaseSymbol(asset.coin)}_USD`;
    const mark = resolveCurrentPrice(sampleInstrument, topCoins);
    const agg: OrderProfitLoss = calculateOpenLotsAggregateProfitLoss(lots, mark);
    if (agg.available) {
      unrealizedPL += agg.pnl;
    }
  }

  const topSymbols: PnLSymbolBreakdown[] = Array.from(bySymbol.entries())
    .map(([symbol, v]) => ({ symbol, pnl: v.pnl, closes: v.closes }))
    .sort((a, b) => Math.abs(b.pnl) - Math.abs(a.pnl))
    .slice(0, topN);

  return {
    realizedPL,
    unrealizedPL,
    totalPL: realizedPL + unrealizedPL,
    closeCount,
    winCount,
    winRate: closeCount > 0 ? winCount / closeCount : null,
    tpExecutedCount,
    slExecutedCount,
    topSymbols,
    period,
  };
}
