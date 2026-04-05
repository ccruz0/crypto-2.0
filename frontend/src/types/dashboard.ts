/**
 * Dashboard-specific type definitions
 */

import { OpenOrder } from '@/app/api';

export type Tab = 'portfolio' | 'watchlist' | 'signals' | 'orders' | 'expected-take-profit' | 'executed-orders' | 'version-history' | 'monitoring';

export type Preset = 'Swing' | 'Intraday' | 'Scalp';
export type RiskMode = 'Conservative' | 'Aggressive';

export interface StrategyRules {
  rsi: { buyBelow?: number; sellAbove?: number };
  maChecks: { ema10: boolean; ma50: boolean; ma200: boolean };
  sl: { pct?: number; atrMult?: number; fallbackPct?: number };     // si hay ATR, usar atrMult; si no, pct. fallbackPct for ATR fallback
  tp: { pct?: number; rr?: number };          // rr = risk:reward basado en SL
  volumeMinRatio?: number;                    // Minimum volume ratio (e.g., 0.5, 1, 1.5, 2)
  minPriceChangePct?: number;                 // Minimum price change % required for order creation/alerts (default: 1.0)
  alertCooldownMinutes?: number;              // Cooldown in minutes between same-side alerts (default: 5.0)
  maxOrdersPerSymbolPerDay?: number;          // Daily order limit per symbol (leave undefined to use env default)
  trendFilters?: {
    require_price_above_ma200?: boolean;
    require_ema10_above_ma50?: boolean;
  };
  rsiConfirmation?: {
    require_rsi_cross_up?: boolean;
    rsi_cross_level?: number;
  };
  candleConfirmation?: {
    require_close_above_ema10?: boolean;
    require_rsi_rising_n_candles?: number;
  };
  atr?: {
    period?: number;
    multiplier_sl?: number;
    multiplier_tp?: number | null;
  };
  notes?: string[];
}

export type PresetConfig = Record<Preset, {
  notificationProfile: 'swing' | 'intraday' | 'scalp';
  rules: Record<RiskMode, StrategyRules>;
}>;

export interface ApiError extends Error {
  status?: number;
  retryAfterMs?: number;
}

export interface Loan {
  borrowed_usd_value?: number;
  [key: string]: unknown;
}

/**
 * Extended OpenOrder type for additional properties
 * Note: Uses intersection to allow number types for cumulative_quantity, cumulative_value, and avg_price
 */
export type ExtendedOpenOrder = OpenOrder & {
  symbol?: string;
  cumulative_value?: number | string | null;
  order_value?: number | string;
  cumulative_quantity?: number | string | null;
  avg_price?: number | string | null;
  // UnifiedOpenOrder/metadata fields that may exist depending on endpoint/source
  trigger_type?: string | null;
  is_trigger?: boolean;
  raw?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  order_role?: string;  // Order role (STOP_LOSS, TAKE_PROFIT, etc.) - inherited from OpenOrder but explicitly declared for clarity
}

/**
 * Type guard to check if an order has trigger_type property
 */
export function hasTriggerType(order: OpenOrder | ExtendedOpenOrder): order is ExtendedOpenOrder {
  return 'trigger_type' in order || 'is_trigger' in order || 'raw' in order || 'metadata' in order;
}

/**
 * Safely get trigger type from order
 */
export function getTriggerType(order: OpenOrder | ExtendedOpenOrder): string {
  if (hasTriggerType(order)) {
    return (order.trigger_type ?? '').toUpperCase().trim();
  }
  return '';
}

/**
 * Safely get raw order data
 */
export function getRawOrder(order: OpenOrder | ExtendedOpenOrder): Record<string, unknown> {
  if (hasTriggerType(order)) {
    return order.raw || order.metadata || {};
  }
  return {};
}

/**
 * Safely check if order is trigger
 */
export function isTriggerOrder(order: OpenOrder | ExtendedOpenOrder): boolean {
  if (hasTriggerType(order)) {
    return Boolean(order.is_trigger ?? false);
  }
  return false;
}

/**
 * Strategy Decision Value type
 */
export type StrategyDecisionValue = 'BUY' | 'SELL' | 'WAIT';

/**
 * Get reason prefix based on decision
 */
export function getReasonPrefix(decision: StrategyDecisionValue): 'buy_' | 'sell_' {
  return decision === 'SELL' ? 'sell_' : 'buy_';
}



