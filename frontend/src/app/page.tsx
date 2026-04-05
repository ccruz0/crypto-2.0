'use client';

import '@/lib/polyfill';
import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { getDashboard, getOpenOrders, getOrderHistory, getTopCoins, saveCoinSettings, getTradingSignals, getDataSourcesStatus, getTradingConfig, saveTradingConfig, updateCoinConfig, addCustomTopCoin, removeCustomTopCoin, getDashboardState, getDashboardSnapshot, quickOrder, updateWatchlistAlert, updateBuyAlert, updateSellAlert, simulateAlert, deleteDashboardItemBySymbol, toggleLiveTrading, getTPSLOrderValues, getOpenOrdersSummary, dashboardBalancesToPortfolioAssets, getExpectedTakeProfitSummary, getExpectedTakeProfitDetails, getTelegramMessages, fixBackendHealth, DashboardState, DashboardBalance, WatchlistItem, OpenOrder, PortfolioAsset, TradingSignals, TopCoin, DataSourceStatus, TradingConfig, CoinSettings, TPSLOrderValues, UnifiedOpenOrder, OpenPosition, ExpectedTPSummary, ExpectedTPSummaryItem, ExpectedTPDetails, ExpectedTPMatchedLot, SimulateAlertResponse, TelegramMessage, StrategyDecision } from '@/app/api';
import { getApiUrl } from '@/lib/environment';
import { usePriceWebSocket } from '@/hooks/usePriceWebSocket';
import { MonitoringNotificationsProvider, useMonitoringNotifications } from '@/app/context/MonitoringNotificationsContext';
import MonitoringPanel from '@/app/components/MonitoringPanel';
import ErrorBoundary from '@/app/components/ErrorBoundary';
import StrategyConfigModal from '@/app/components/StrategyConfigModal';
import PortfolioTab from '@/app/components/tabs/PortfolioTab';
import WatchlistTab from '@/app/components/tabs/WatchlistTab';
import OrdersTab from '@/app/components/tabs/OrdersTab';
import ExpectedTakeProfitTab from '@/app/components/tabs/ExpectedTakeProfitTab';
import ExecutedOrdersTab from '@/app/components/tabs/ExecutedOrdersTab';
import SystemHealthPanel from '@/components/SystemHealth';
import MissingSecretsBanner from '@/components/MissingSecretsBanner';
import { palette } from '@/theme/palette';
import { logger } from '@/utils/logger';

const TELEGRAM_REFRESH_INTERVAL_MS = 20000;

// Cleaned duplicate error handlers in alert toggle logic (handleMasterAlertToggle, updateBuyAlert, updateSellAlert)
// All try-catch blocks for alert toggles now have single, clean error handling paths

// Extended OpenOrder type for additional properties
type ExtendedOpenOrder = OpenOrder & {
  symbol?: string;
  cumulative_value?: number | string;
  order_value?: number | string;
  cumulative_quantity?: number | string;
  avg_price?: number | string;
  // UnifiedOpenOrder/metadata fields that may exist depending on endpoint/source
  trigger_type?: string | null;
  is_trigger?: boolean;
  raw?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  order_role?: string;  // Order role (STOP_LOSS, TAKE_PROFIT, etc.) - inherited from OpenOrder but explicitly declared for clarity
};

// Transform UnifiedOpenOrder[] to OpenPosition[]
function transformOrdersToPositions(orders: UnifiedOpenOrder[], portfolioAssets?: PortfolioAsset[]): OpenPosition[] {
  // Group orders by symbol and client_oid to find related orders
  const positionsMap = new Map<string, OpenPosition>();
  
  if (!orders || orders.length === 0) {
    // Silently return empty array if no orders (normal condition)
    return [];
  }
  
  // First pass: group SELL orders by symbol and client_oid (to find related TP/SL orders)
  const sellOrdersByClientOid = new Map<string, UnifiedOpenOrder[]>();
  
  orders.forEach(order => {
    if (order.side === 'SELL') {
      const clientOid = order.client_oid || `standalone-${order.order_id}`;
      if (!sellOrdersByClientOid.has(clientOid)) {
        sellOrdersByClientOid.set(clientOid, []);
      }
      sellOrdersByClientOid.get(clientOid)!.push(order);
    }
  });
  
    // Debug: transformOrdersToPositions (silenced to reduce console noise)
  
  // Second pass: create positions from grouped SELL orders
  sellOrdersByClientOid.forEach((sellOrders, clientOid) => {
    if (sellOrders.length === 0) return;
    
    // All orders should have the same symbol (they're related)
    const symbol = sellOrders[0].symbol;
    
    // Calculate totals for SELL orders (TP/SL)
    const totalQuantity = sellOrders.reduce((sum, o) => sum + (o.quantity || 0), 0);
    const totalValue = sellOrders.reduce((sum, o) => sum + ((o.quantity || 0) * (o.price || 0)), 0);
    const avgPrice = totalQuantity > 0 ? totalValue / totalQuantity : null;
    
    // Count TP and SL orders and find limit prices
    const tpOrders = sellOrders.filter(o => 
      o.order_type === 'TAKE_PROFIT_LIMIT' || 
      o.order_type === 'TAKE_PROFIT' ||
      (o.is_trigger && o.trigger_type === 'TAKE_PROFIT')
    );
    const slOrders = sellOrders.filter(o => 
      o.order_type === 'STOP_LOSS_LIMIT' || 
      o.order_type === 'STOP_LOSS' ||
      (o.is_trigger && o.trigger_type === 'STOP_LOSS')
    );
    
    // Find TP price (highest limit price from TP orders)
    const tpPrices = tpOrders
      .map(o => o.price)
      .filter((p): p is number => p !== null && p !== undefined && p > 0);
    const tpPrice = tpPrices.length > 0 ? Math.max(...tpPrices) : null;
    
    // Find SL price (lowest limit price from SL orders)
    const slPrices = slOrders
      .map(o => o.price)
      .filter((p): p is number => p !== null && p !== undefined && p > 0);
    const slPrice = slPrices.length > 0 ? Math.min(...slPrices) : null;
    
    // Get entry price from portfolio if available, otherwise use avgPrice from orders
    let entryPrice: number | null = null;
    let entryQuantity: number = totalQuantity;
    
    if (portfolioAssets && portfolioAssets.length > 0 && symbol) {
      // Try to find matching asset in portfolio
      const portfolioAsset = portfolioAssets.find(asset => 
        asset.coin === symbol || asset.coin === symbol.split('_')[0]
      );
      
      if (portfolioAsset && portfolioAsset.balance > 0 && portfolioAsset.value_usd > 0) {
        // Calculate entry price from portfolio: value_usd / balance
        entryPrice = portfolioAsset.value_usd / portfolioAsset.balance;
        entryQuantity = portfolioAsset.balance;
      }
    }
    
    // Fallback to avgPrice if portfolio data not available
    if (entryPrice === null) {
      entryPrice = avgPrice;
    }
    
    // Calculate TP/SL profits
    let tpProfit: number | null = null;
    let slProfit: number | null = null;
    
    if (entryPrice !== null && entryQuantity > 0) {
      if (tpPrice !== null) {
        // Profit = (TP price * quantity) - (entry price * quantity)
        tpProfit = (tpPrice * entryQuantity) - (entryPrice * entryQuantity);
      }
      if (slPrice !== null) {
        // Loss = (SL price * quantity) - (entry price * quantity) (should be negative)
        slProfit = (slPrice * entryQuantity) - (entryPrice * entryQuantity);
      }
    }
    
    // Use entry price from portfolio for basePrice if available
    const basePrice = entryPrice || avgPrice;
    
    // Use the first order's client_oid as baseOrderId (or generate one)
    const baseOrderId = clientOid.startsWith('standalone-') 
      ? sellOrders[0].order_id 
      : clientOid;
    
    // Find the earliest created_at
    const createdAts = sellOrders.map(o => o.created_at).filter(Boolean) as string[];
    const baseCreatedAt = createdAts.length > 0 
      ? new Date(Math.min(...createdAts.map(d => new Date(d).getTime()))).toISOString()
      : new Date().toISOString();
    
    // Transform child orders
    const childOrders = sellOrders.map(order => ({
      orderId: order.order_id,
      side: 'SELL' as const,
      type: (order.order_type === 'TAKE_PROFIT_LIMIT' || order.order_type === 'TAKE_PROFIT' || (order.is_trigger && order.trigger_type === 'TAKE_PROFIT'))
        ? 'TAKE_PROFIT' as const
        : (order.order_type === 'STOP_LOSS_LIMIT' || order.order_type === 'STOP_LOSS' || (order.is_trigger && order.trigger_type === 'STOP_LOSS'))
        ? 'STOP_LOSS' as const
        : 'SELL' as const,
      quantity: order.quantity || 0,
      price: order.price,
      createdAt: order.created_at || new Date().toISOString()
    }));
    
    const positionKey = `${symbol}_${baseOrderId}`;
    
    // Create or update position
    positionsMap.set(positionKey, {
      symbol,
      baseOrderId,
      baseSide: 'BUY' as const, // We assume there was a BUY order that created this position
      baseQuantity: entryQuantity,
      basePrice: basePrice,
      baseTotal: basePrice !== null && entryQuantity > 0 ? basePrice * entryQuantity : null,
      baseCreatedAt,
      netOpenQuantity: entryQuantity, // Use entry quantity from portfolio
      positionQuantity: entryQuantity,
      tpCount: tpOrders.length,
      slCount: slOrders.length,
      tpPrice,
      slPrice,
      tpProfit,
      slProfit,
      childOrders
    });
  });
  
  const result = Array.from(positionsMap.values());
  // Debug: transformOrdersToPositions result (silenced to reduce console noise)
  return result;
}

export default function DashboardPage() {
  return (
    <MonitoringNotificationsProvider>
      <DashboardPageContent />
    </MonitoringNotificationsProvider>
  );
}

const REFRESH_FAST_MS = 15000; // 15 seconds for coins with Trade YES
const REFRESH_SLOW_MS = 60000; // 60 seconds (1 minute) for coins with Trade NO
const FAST_STAGGER_MS = 1000; // Increased from 500ms to 1000ms
const MAX_FAST_BACKOFF_MS = REFRESH_SLOW_MS * 4;
const RATE_LIMIT_STATUS = 429;
const FAST_BATCH_SIZE = 1; // Reduced from 2 to 1
const SLOW_BATCH_SIZE = 1; // Reduced from 2 to 1
const PORTFOLIO_UNAVAILABLE_MESSAGE = 'Portfolio data unavailable from backend. Please check API /dashboard/state, then retry.';

type ApiError = Error & {
  status?: number;
  retryAfterMs?: number;
};

type Loan = {
  borrowed_usd_value?: number;
  [key: string]: unknown;
};

const wait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

// WATCHLIST_PAGE_SIZE removed - not used (showing all coins in watchlist)

// Inline components for better compatibility
const Badge = ({ variant, children, className = '', title }: { variant: 'success' | 'danger' | 'warning' | 'neutral'; children: React.ReactNode; className?: string; title?: string }) => {
  const baseClasses = 'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs border';
  const variantClasses = {
    success: palette.badge.success,
    danger: palette.badge.danger,
    warning: palette.badge.warning,
    neutral: palette.badge.neutral,
  };
  return <span className={`${baseClasses} ${variantClasses[variant]} ${className}`} title={title}>{children}</span>;
};

// Helper function to format timestamps - uses browser's local timezone automatically
const formatTimestamp = (ts?: number | string | Date): string => {
  if (!ts) return 'N/A';
  let date: Date;
  
  if (ts instanceof Date) {
    date = ts;
  } else if (typeof ts === 'number') {
    // Timestamp in milliseconds - JavaScript Date interprets this as UTC
    date = new Date(ts);
  } else {
    // String - could be ISO format or custom format
    const str = String(ts);
    // If it's an ISO string (contains 'T' or ends with 'Z' or '+'), parse directly
    if (str.includes('T') || str.endsWith('Z') || str.includes('+') || str.includes('-', 10)) {
      date = new Date(str);
    } else {
      // Custom format like "2024-11-11 14:30:00 UTC" - treat as UTC
      // Remove "UTC" suffix and parse, then manually set as UTC
      const cleaned = str.replace(/\s+UTC$/, '').trim();
      if (cleaned.match(/^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}/)) {
        // Format: YYYY-MM-DD HH:MM:SS - treat as UTC
        date = new Date(cleaned + 'Z'); // Add Z to indicate UTC
      } else {
        date = new Date(str);
      }
    }
  }
  
  if (isNaN(date.getTime())) return 'N/A';
  // Always use browser's local timezone with timezone name visible
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
    timeZoneName: 'short',
  });
};

// Helper function to format dates with time - always uses browser's local timezone
const formatDateTime = (date: Date): string => {
  if (!date || isNaN(date.getTime())) return 'N/A';
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
    timeZoneName: 'short',
  });
};

// Helper function to format time only - uses browser's local timezone
const formatTime = (date: Date): string => {
  if (!date || isNaN(date.getTime())) return 'Never';
  return date.toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZoneName: 'short',
  });
};

const Table = ({ children, className = '' }: { children: React.ReactNode; className?: string }) => {
  const baseClasses = 'table-wrap rounded-2xl border shadow-sm bg-white dark:bg-slate-900 dark:border-slate-700';
  const combinedClasses = className ? baseClasses + ' ' + className : baseClasses;
  return (
    <div className={combinedClasses}>
      <table className="min-w-full text-sm text-gray-800 dark:text-slate-200 border-collapse">
        {children}
      </table>
    </div>
  );
};

const SkeletonBlock = ({ className = '' }: { className?: string }) => (
  <div className={`animate-pulse bg-gray-200 dark:bg-slate-700 rounded ${className}`} />
);

type Tab = 'portfolio' | 'watchlist' | 'signals' | 'orders' | 'expected-take-profit' | 'executed-orders' | 'version-history' | 'monitoring';

// Helper function to add thousand separators
function addThousandSeparators(numStr: string): string {
  const parts = numStr.split('.');
  parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return parts.join('.');
}

// Helper function to format numbers with correct decimals
function formatNumber(num: number | null | undefined, symbol?: string): string {
  if (num === null || num === undefined) return '-';
  
  // If number is 0, return "0.00"
  if (num === 0) return '0.00';
  
  let formatted: string;
  
  // Adaptive rounding based on price magnitude (matching backend logic)
  // For low-value coins like VET, show more decimal places for better precision
  // Backend uses: price_precision = 2 if current_price >= 100 else 4
  // We'll use similar logic but with more granular precision for better display
  
  if (num >= 100) {
    // High-value coins >= $100 - use 2 decimal places
    formatted = num.toFixed(2);
  } else if (num >= 1) {
    // Medium-value coins $1-$99 - use 2 decimal places
    formatted = num.toFixed(2);
  } else if (num >= 0.01) {
    // Low-value coins $0.01-$0.99 - use 6 decimal places
    formatted = num.toFixed(6);
  } else {
    // Very low-value coins < $0.01 - use 10 decimal places
    formatted = num.toFixed(10);
  }
  
  // For values < 0.01, preserve all decimal places (don't remove trailing zeros)
  // This ensures precision for low-value coins like VET, XLM, etc.
  if (num < 0.01) {
    // Don't remove trailing zeros for very small values - they're significant
    return addThousandSeparators(formatted);
  }
  
  // For values < 0.01, preserve all decimal places (don't remove trailing zeros)
  // This ensures precision for very low-value coins like VET, XLM, etc.
  if (num < 0.01) {
    // Don't remove trailing zeros for very small values - they're significant
    return addThousandSeparators(formatted);
  }
  
  // For values >= 0.01, remove trailing zeros but preserve minimum decimals based on value range
  const parts = formatted.split('.');
  if (parts.length === 2) {
    // Determine minimum decimals to keep based on value magnitude
    let minDecimals = 2;
    if (num >= 100) {
      minDecimals = 2; // Values >= $100: keep at least 2 decimals
    } else if (num >= 1) {
      minDecimals = 2; // Values $1-$99: keep at least 2 decimals
    } else if (num >= 0.01) {
      minDecimals = 6; // Values $0.01-$0.99: keep at least 6 decimals
    }
    
    // Remove trailing zeros but keep at least minDecimals
    const decimals = parts[1].replace(/0+$/, '');
    if (decimals.length === 0) {
      // If all decimals were zeros, keep at least minDecimals
      formatted = parts[0] + '.' + parts[1].substring(0, Math.min(minDecimals, parts[1].length)).padEnd(Math.min(minDecimals, parts[1].length), '0');
    } else {
      // Keep meaningful decimals, but ensure at least minDecimals
      if (decimals.length < minDecimals) {
        formatted = parts[0] + '.' + decimals.padEnd(minDecimals, '0');
      } else {
        formatted = parts[0] + '.' + decimals;
      }
    }
  }
  
  // Add thousand separators
  return addThousandSeparators(formatted);
}

// Fixed-decimal formatter for P/L summary cards
function formatPLSummaryNumber(num: number | null | undefined): string {
  if (num === null || num === undefined) return '-';
  return addThousandSeparators((num ?? 0).toFixed(1));
}

const HANDLED_ERROR_SUPPRESSION_MS = 30000;
const handledErrorTimestamps = new Map<string, number>();

function logHandledError(
  key: string,
  message: string,
  error: unknown,
  level: 'warn' | 'error' = 'warn'
): void {
  const now = Date.now();
  const lastLoggedAt = handledErrorTimestamps.get(key) ?? 0;
  if (now - lastLoggedAt < HANDLED_ERROR_SUPPRESSION_MS) {
    return;
  }
  handledErrorTimestamps.set(key, now);

  // Use centralized logger instead of direct console calls
  if (error instanceof Error) {
    if (level === 'warn') {
      logger.warn(message, { name: error.name, message: error.message, stack: error.stack });
    } else {
      logger.error(message, { name: error.name, message: error.message, stack: error.stack });
    }
  } else {
    if (level === 'warn') {
      logger.warn(message, error);
    } else {
      logger.error(message, error);
    }
  }
}

// CRITICAL: Helper to normalize symbol keys to uppercase for consistent state access
// All state keys are stored in UPPERCASE (from backend loading and mount effect normalization)
// This ensures UI access via coin.instrument_name (which may be mixed case) always finds the correct state value
function normalizeSymbolKey(symbol: string | undefined | null): string {
  return symbol ? symbol.toUpperCase() : '';
}

// Helper function to get Trade button color based on trade status
// Returns: 'bg-green-500 text-white' for YES (true), 'bg-red-500 text-white' for NO (false), 'bg-yellow-500 text-white' for unknown
function getTradeButtonColor(tradeStatus: boolean | undefined | null): string {
  if (tradeStatus === true) return 'bg-green-500 text-white';
  if (tradeStatus === false) return 'bg-red-500 text-white';
  return 'bg-yellow-500 text-white'; // Default/unknown
}

// Strategy configuration types and constants (moved outside component)
type Preset = 'Swing' | 'Intraday' | 'Scalp';
type RiskMode = 'Conservative' | 'Aggressive';

type StrategyRules = {
  rsi: { buyBelow?: number; sellAbove?: number };
  maChecks: { ema10: boolean; ma50: boolean; ma200: boolean };
  sl: { pct?: number; atrMult?: number; fallbackPct?: number };     // si hay ATR, usar atrMult; si no, pct. fallbackPct for ATR fallback
  tp: { pct?: number; rr?: number };          // rr = risk:reward basado en SL
  volumeMinRatio?: number;                    // Minimum volume ratio (e.g., 0.5, 1, 1.5, 2)
  minPriceChangePct?: number;                 // Minimum price change % required for order creation/alerts (default: 1.0)
  alertCooldownMinutes?: number;              // Cooldown in minutes between same-side alerts (default: 5.0)
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
};

type PresetConfig = Record<Preset, {
  notificationProfile: 'swing' | 'intraday' | 'scalp';
  rules: Record<RiskMode, StrategyRules>;
}>;

const PRESET_CONFIG: PresetConfig = {
  Swing: {
    notificationProfile: 'swing',
    rules: {
      Conservative: {
        rsi: { buyBelow: 30, sellAbove: 70 },
        maChecks: { ema10: true, ma50: true, ma200: true },
        sl: { atrMult: 1.5, fallbackPct: 3.0 },
        tp: { rr: 1.5 },
        volumeMinRatio: 1.0,
        minPriceChangePct: 3.0,
        alertCooldownMinutes: 5.0,
        trendFilters: {
          require_price_above_ma200: true,
          require_ema10_above_ma50: true
        },
        rsiConfirmation: {
          require_rsi_cross_up: true,
          rsi_cross_level: 30
        },
        candleConfirmation: {
          require_close_above_ema10: true,
          require_rsi_rising_n_candles: 2
        },
        atr: {
          period: 14,
          multiplier_sl: 1.5,
          multiplier_tp: null
        },
        notes: ['Operaciones multi-día', 'Confirmación MA50/MA200', 'Filtros estrictos de reversión de tendencia']
      },
      Aggressive: {
        rsi: { buyBelow: 45, sellAbove: 68 },
        maChecks: { ema10: true, ma50: true, ma200: true },
        sl: { atrMult: 1.0 },
        tp: { rr: 1.2 },
        volumeMinRatio: 0.5,
        minPriceChangePct: 1.0,
        alertCooldownMinutes: 5.0,
        notes: ['Entrada más temprana', 'SL más estrecho']
      }
    }
  },
  Intraday: {
    notificationProfile: 'intraday',
    rules: {
      Conservative: {
        rsi: { buyBelow: 45, sellAbove: 70 },
        maChecks: { ema10: true, ma50: true, ma200: false },
        sl: { atrMult: 1.0 },
        tp: { rr: 1.2 },
        volumeMinRatio: 0.5,
        minPriceChangePct: 1.0,
        notes: ['Cierra en el día', 'Evita overnight']
      },
      Aggressive: {
        rsi: { buyBelow: 50, sellAbove: 65 },
        maChecks: { ema10: true, ma50: true, ma200: false },
        sl: { atrMult: 0.8 },
        tp: { rr: 1.0 },
        volumeMinRatio: 0.5,
        minPriceChangePct: 1.0,
        alertCooldownMinutes: 5.0,
        notes: ['Más señales', 'Más ruido']
      }
    }
  },
  Scalp: {
    notificationProfile: 'scalp',
    rules: {
      Conservative: {
        rsi: { buyBelow: 50, sellAbove: 70 },
        maChecks: { ema10: true, ma50: false, ma200: false },
        sl: { pct: 0.5 },
        tp: { pct: 0.8 },
        volumeMinRatio: 0.5,
        minPriceChangePct: 1.0,
        alertCooldownMinutes: 5.0,
        notes: ['Movimientos muy cortos', 'Slippage importa']
      },
      Aggressive: {
        rsi: { buyBelow: 55, sellAbove: 65 },
        maChecks: { ema10: true, ma50: false, ma200: false },
        sl: { pct: 0.35 },
        tp: { pct: 0.5 },
        volumeMinRatio: 0.5,
        minPriceChangePct: 1.0,
        alertCooldownMinutes: 5.0,
        notes: ['Entradas anticipadas', 'Muchas micro-salidas']
      }
    }
  }
};

// Version history entries - each change gets a new version number (shared constant)
const VERSION_HISTORY = [
  {
    version: '0.1',
    date: '2024-11-04',
    change: 'Initial version history system implementation',
    details: 'Created version history tab with expandable sections to document all changes and improvements systematically.'
  },
  {
    version: '0.2',
    date: '2024-11-04',
    change: 'Fixed port conflict between gluetun and backend',
    details: 'Removed port 8002 from gluetun container port mappings. Backend now uses bridge network on port 8002 without conflicts.'
  },
  {
    version: '0.3',
    date: '2024-11-04',
    change: 'Updated frontend API URL configuration',
    details: 'Changed frontend environment.ts and .env.local to use port 8002 instead of 8000 for backend API calls.'
  },
  {
    version: '0.4',
    date: '2024-11-04',
    change: 'Fixed frontend port mapping conflict',
    details: 'Changed frontend port from 3000:3000 to 3001:3000 in docker-compose.yml to avoid conflict with gluetun.'
  },
  {
    version: '0.5',
    date: '2024-11-04',
    change: 'Optimized backend startup event',
    details: 'Refactored startup event to run database initialization in thread pool executor to avoid blocking the event loop.'
  },
  {
    version: '0.6',
    date: '2024-11-04',
    change: 'Made service startup non-blocking',
    details: 'Changed exchange_sync_service and signal_monitor_service to start in background tasks using asyncio.create_task() instead of await.'
  },
  {
    version: '0.7',
    date: '2024-11-04',
    change: 'Simplified health endpoint',
    details: 'Removed VPN status checks from health endpoint to prevent blocking. Health endpoint now returns immediately.'
  },
  {
    version: '0.8',
    date: '2024-11-04',
    change: 'Adjusted Docker health check configuration',
    details: 'Increased health check interval from 10s to 30s, timeout from 3s to 10s, and start_period from 20s to 60s to prevent restart loops.'
  },
  {
    version: '0.9',
    date: '2024-11-04',
    change: 'Removed blocking VPN gate check from startup',
    details: 'Moved VPN gate monitor to background task to prevent blocking startup event.'
  },
  {
    version: '0.10',
    date: '2024-11-04',
    change: 'Fixed watchlist settings persistence on refresh',
    details: 'Added useEffect hook to load all watchlist settings from localStorage on initial component mount to persist settings across page refreshes.'
  },
  {
    version: '0.11',
    date: '2024-11-04',
    change: 'Fixed margin status not saving',
    details: 'Added localStorage.setItem() to margin toggle onClick handler to persist trade_on_margin status across refreshes.'
  },
  {
    version: '0.12',
    date: '2024-11-04',
    change: 'Fixed Telegram bot connectivity',
    details: 'Removed backend from VPN network to allow Telegram API access. Added Telegram IP ranges to firewall outbound subnets.'
  },
  {
    version: '0.13',
    date: '2024-11-04',
    change: 'Fixed Telegram /start command',
    details: 'Fixed message formatting (Markdown to HTML) and ensured scheduler starts correctly as async task.'
  },
  {
    version: '0.14',
    date: '2024-11-04',
    change: 'Updated Telegram /status command',
    details: 'Updated /status command to show accurate data: active positions and tracked coins based on trade_enabled=True, individual trade amounts per coin, removed Paper Trading line.'
  },
  {
    version: '0.15',
    date: '2024-11-04',
    change: 'Fixed frontend network configuration',
    details: 'Removed frontend from VPN network and changed port to 3001:3000 to allow direct access to backend on bridge network.'
  },
  {
    version: '0.16',
    date: '2024-11-04',
    change: 'Implemented /analyze command with coin selection menu',
    details: 'Modified /analyze command to show a menu with all available coins for selection instead of requiring symbol as argument.'
  },
  {
    version: '0.17',
    date: '2024-11-04',
    change: 'Fixed backend startup blocking',
    details: 'Made all background services start in fire-and-forget tasks to prevent blocking HTTP requests during startup.'
  },
  {
    version: '0.18',
    date: '2024-11-04',
    change: 'Fixed CORS preflight requests',
    details: 'Explicitly enabled CORS middleware and configured it to allow all HTTP methods including OPTIONS requests.'
  },
  {
    version: '0.19',
    date: '2024-11-04',
    change: 'Fixed backend startup blocking issue',
    details: 'Completely refactored startup event to be fully non-blocking. All background services now start in fire-and-forget tasks, allowing the server to respond to requests immediately after startup completes.'
  },
  {
    version: '0.20',
    date: '2024-11-04',
    change: 'Fixed watchlist, portfolio, and orders not loading',
    details: 'Resolved backend API timeout issues that were preventing watchlist, portfolio, and order history from loading. Backend now responds immediately to all API requests after non-blocking startup completes.'
  },
  {
    version: '0.21',
    date: '2024-11-04',
    change: 'Fixed watchlist, portfolio, and orders not loading',
    details: 'Resolved backend API timeout issues by making database dependencies non-blocking. Watchlist now loads 21 coins, portfolio shows 19 balances, and orders display 8 open orders correctly.'
  },
  {
    version: '0.22',
    date: '2024-11-04',
    change: 'Simplified root and health endpoints to avoid blocking',
    details: 'Removed async/await and environment checks from root endpoint. Simplified health endpoint to return immediately without VPN status checks.'
  },
  {
    version: '0.23',
    date: '2024-11-04',
    change: 'Fixed indicators not loading in watchlist table',
    details: 'Modified updateTopCoins function to extract technical indicators (RSI, ATR, MA50, MA200, EMA10) from coin objects returned by backend and populate the signals object. The table was reading indicators from signals but they were only present in the coin object, causing all indicators to show as empty.'
  },
  {
    version: '0.24',
    date: '2024-11-04',
    change: 'Fixed SL/TP calculation and resistance levels extraction',
    details: 'Added res_up and res_down resistance levels to backend /market/top-coins-data endpoint and frontend TopCoin interface. Modified updateTopCoins to extract resistance levels from coin data. Fixed SL/TP calculation to work even when resistance levels are missing (uses fallback percentages). Ensured all coins are processed, not just those with complete indicator data.'
  },
  {
    version: '0.25',
    date: '2024-11-04',
    change: 'Fixed volume calculation in watchlist table',
    details: 'Added avg_volume and volume_ratio to backend /market/top-coins-data endpoint from MarketData model. Modified frontend to use pre-calculated volume_ratio from backend when available, instead of incorrectly calculating from volume_24h. This ensures accurate volume ratio display in the watchlist table.'
  },
  {
    version: '0.26',
    date: '2024-11-04',
    change: 'Fixed alert status update timeout issue',
    details: 'Added specific 10-second timeout for watchlist alert updates. Implemented optimistic UI updates with immediate localStorage persistence. Added fallback to saveCoinSettings if updateWatchlistAlert endpoint times out or fails. This ensures alert status updates are responsive and reliable even if the dedicated endpoint has issues.'
  },
  {
    version: '0.27',
    date: '2024-11-04',
    change: 'Increased timeout for top-coins-data endpoint',
    details: 'Increased timeout for /market/top-coins-data endpoint from 30s to 60s to allow backend to return all coins. Added better logging for deleted coins filtering to help debug why only 2 coins are showing. This should allow all 21 coins from the backend to load properly.'
  },
  {
    version: '0.28',
    date: '2024-11-04',
    change: 'Optimized initial page load for faster startup',
    details: 'Changed initial data loading from sequential to parallel. All endpoints (top coins, portfolio, orders, config) now load simultaneously instead of waiting for each other. Signal hydration now loads first batch immediately in parallel, then continues in background. This significantly reduces initial load time and ensures fresh data from backend tables is loaded immediately.'
  },
  {
    version: '0.29',
    date: '2024-11-04',
    change: 'Optimized backend database queries for faster response',
    details: 'Optimized /market/top-coins-data endpoint to only query MarketData for symbols that have MarketPrice records, instead of querying all MarketData. This reduces database query time significantly. Improved logging to show query performance and warn if queries take longer than 0.5 seconds. This ensures backend responds faster to initial page load requests.'
  },
  {
    version: '0.30',
    date: '2024-11-04',
    change: 'Optimized portfolio and open orders endpoints for faster response',
    details: 'Optimized get_portfolio_summary to use SQL aggregation (func.sum) for total_usd calculation instead of Python sum, reducing query time. Optimized open orders endpoint to limit results and add composite database index (status, create_time) for faster queries. Added performance logging to both endpoints to track query times and warn if they exceed 0.3 seconds. This significantly improves portfolio and open orders loading speed.'
  },
  {
    version: '0.31',
    date: '2024-11-04',
    change: 'Fixed /watchlist command in Telegram not showing coins with Trade=YES',
    details: 'Fixed POST /dashboard endpoint to update existing watchlist items instead of raising error when item already exists. This ensures that when frontend saves trade_enabled=True, it updates the existing item in database instead of failing. Added debug logging to /watchlist command to help diagnose issues. Now when user changes Trade=YES in frontend, it correctly saves to database and Telegram /watchlist command will show the coins.'
  },
  {
    version: '0.32',
    date: '2024-11-04',
    change: 'Added detailed logging to debug trade_enabled save issue',
    details: 'Added comprehensive logging to PUT /dashboard/{item_id} endpoint to log all received data, check if trade_enabled is present in request, and log the update process. This will help identify why trade_enabled is not being saved to database when user changes Trade=YES in frontend. Frontend now also logs the save process with try/catch to show any errors.'
  },
  {
    version: '0.4',
    date: '2025-11-13',
    change: 'Major Release: Advanced Portfolio Management & Profit/Loss Tracking',
    details: `🎉 VERSIÓN 0.4 - RELEASE PRINCIPAL

📊 **Sistema Completo de Profit/Loss (P/L)**
• Cálculo automático de P/L para todas las órdenes ejecutadas
• Algoritmo inteligente de emparejamiento de órdenes BUY/SELL:
  - Prioriza órdenes creadas simultáneamente (ventana de 5 minutos)
  - Fallback a emparejamiento por volumen similar (tolerancia 20%)
  - Soporte para órdenes parciales y múltiples ejecuciones
• Visualización de P/L realizado (órdenes vendidas) y potencial (no vendidas)
• Cálculo de porcentaje de ganancia/pérdida por orden
• Columna P/L en tabla de órdenes ejecutadas con colores (verde/rojo)

💰 **Resumen de P/L por Períodos**
• Resumen diario, semanal, mensual y anual de P/L
• Selectores interactivos para mes y año
• Desglose en tres métricas:
  - Realized P/L: Ganancias/pérdidas de órdenes ya ejecutadas (vendidas)
  - Potential P/L: Ganancias/pérdidas potenciales de posiciones abiertas (precio actual)
  - Total P/L: Suma de realized + potential
• Visualización con tarjetas de colores y formato monetario

📈 **Mejoras en Portfolio**
• Separación automática de pares USD y USDT (ej: DOGE_USD, DOGE_USDT)
• Cálculo independiente de balances y valores USD por par
• Expansión automática de monedas base a pares específicos cuando hay órdenes abiertas
• Exclusión de monedas fiat (USD, USDT) de la expansión
• Cálculo preciso de valores USD usando precios de mercado actuales

🔄 **Sistema de Actualización de Precios Mejorado**
• Reducción de cache de precios de 5 minutos a 1 minuto para actualizaciones más frecuentes
• Actualización automática de todos los coins cada 3 minutos (cada 3er slow tick)
• Corrección del market_updater para funcionar correctamente
• Fix de errores de sintaxis en market_updater.py y market_cache_storage.py
• Mejor manejo de errores en actualización de precios

🎯 **Mejoras en Open Orders**
• Visualización de TP (Take Profit) y SL (Stop Loss) en columnas separadas
• Cálculo preciso de valores TP/SL usando cumulative_value u order_value cuando disponible
• Conteo de órdenes abiertas por moneda
• Suma total de valores TP/SL por moneda

⚙️ **Mejoras en LIVE/DRY RUN Toggle**
• Mejor manejo de errores con mensajes descriptivos
• Validación de conexión a base de datos
• Verificación de existencia de tabla TradingSettings
• Mensajes de error mejorados para debugging

🐛 **Correcciones de Bugs**
• Fix de error de sintaxis en bloques catch del frontend
• Corrección de errores de indentación en market_updater.py
• Fix de problemas de actualización de precios para BTC_USD y otras monedas
• Mejora en la estabilidad del dashboard con mejor manejo de errores

🔧 **Mejoras Técnicas**
• Optimización de useMemo hooks para mejor rendimiento
• Mejor manejo de estados null/undefined
• Logging mejorado para debugging
• Código más robusto con try-catch en funciones críticas

📱 **Mejoras de UX**
• Interfaz más clara y organizada
• Mejor feedback visual para estados de carga
• Mensajes de error más informativos
• Navegación mejorada entre tabs`
  },
  {
    version: '0.45',
    date: '2025-11-23',
    change: 'AWS-First Development Migration & Telegram Routing',
    details: `🚀 VERSIÓN 0.45 - MIGRACIÓN AWS-FIRST

📋 **Migración Completa a AWS**
• Local Docker runtime completamente deshabilitado
• Todos los contenedores corren exclusivamente en AWS
• Scripts de auto-start locales bloqueados para prevenir ejecución accidental
• Desarrollo local ahora solo edita código, nunca ejecuta Docker

🔧 **Configuración de Ambiente**
• Añadido soporte para variable ENVIRONMENT (aws/local)
• Añadido soporte para variable RUN_TELEGRAM (true/false)
• Configuración AWS requiere ENVIRONMENT=aws y RUN_TELEGRAM=true
• Configuración local requiere ENVIRONMENT=local o ausente, RUN_TELEGRAM=false o ausente

📱 **Telegram Routing - AWS Only**
• Todos los mensajes de Telegram SOLO se envían desde AWS
• Desarrollo local NUNCA envía mensajes de Telegram (código compila pero calls son neutralizadas)
• TelegramNotifier verifica automáticamente:
  - Si está en AWS (ENVIRONMENT=aws o APP_ENV=aws)
  - Si RUN_TELEGRAM=true
  - Solo habilita Telegram si ambas condiciones se cumplen
• Local development: todas las llamadas a Telegram retornan False silenciosamente
• AWS: todas las alertas, confirmaciones, y notificaciones se envían normalmente

🔐 **Seguridad y Prevención de Errores**
• Protección múltiple contra envío accidental de Telegram desde local:
  - Verificación de ambiente al inicializar TelegramNotifier
  - Verificación en cada método send_* (aunque todos usan send_message internamente)
  - Logging claro cuando Telegram está deshabilitado
• Código local compila y ejecuta sin errores, pero Telegram nunca se envía

🔄 **Workflow de Desarrollo**
• Local: Editar código → Commit → Push
• AWS: Pull → Rebuild → Test → Deploy
• Todos los comandos Docker ahora se ejecutan via SSH en AWS
• Documentación REMOTE_DEV.md creada con workflow completo

📝 **Mejoras de Código**
• Corregido bug en main.py: watchlist initialization ahora rastrea correctamente símbolos procesados
• Todos los métodos de TelegramNotifier respetan self.enabled
• Mejor logging para debugging de estado de Telegram

🎯 **Preparación AWS**
• Verificado SSH connectivity a AWS
• Validado existencia de proyecto en AWS
• Preparado para pull de cambios y rebuild

📚 **Documentación**
• REMOTE_DEV.md creado con:
  - Local workflow (sin Docker)
  - Remote workflow (AWS)
  - Production workflow
  - Comandos canónicos para todas las operaciones
  - Sección explícita sobre prohibición de Telegram local`
  },
  {
    version: '0.46',
    date: '2025-12-15',
    change: 'Monitoring hooks fix & cache bust',
    details: `🚀 VERSIÓN 0.46 - FIX MONITORING HOOKS

📋 **Cambios**
• Reconstrucción forzada del frontend para tomar el fix de hooks
• Evita React error #310 en el tab Monitoring
• Limpieza de caché y despliegue completo

🔧 **Notas Técnicas**
• useMemo movido antes de cualquier return condicional
• Hooks alineados para cumplir las reglas de React
• Nueva versión para bust de caché en build

---
`
  }
];

// Helper function to get current version (must be defined before component)
function getCurrentVersion(): string {
  return VERSION_HISTORY[VERSION_HISTORY.length - 1].version;
}

function DashboardPageContent() {
  usePriceWebSocket();
  const { unreadCount: unreadMonitoringCount, handleNewMessages, markAllAsRead } = useMonitoringNotifications();
  const [activeTab, setActiveTab] = useState<Tab>('portfolio');
  const [loading, setLoading] = useState(false);
  const [showAddForm, setShowAddForm] = useState(false);
  const [portfolio, setPortfolio] = useState<{ assets: PortfolioAsset[], total_value_usd: number; total_assets_usd?: number; total_collateral_usd?: number; total_borrowed_usd?: number; portfolio_value_source?: string } | null>(null);
  const [totalBorrowed, setTotalBorrowed] = useState<number>(0);
  const [realBalances, setRealBalances] = useState<DashboardBalance[]>([]);
  const [topCoins, setTopCoins] = useState<TopCoin[]>([]);
  const [topCoinsLoading, setTopCoinsLoading] = useState(true);
  const [topCoinsError, setTopCoinsError] = useState<string | null>(null);
  const [lastTopCoinsFetchAt, setLastTopCoinsFetchAt] = useState<Date | null>(null);
  const [portfolioLoading, setPortfolioLoading] = useState(true);
  // const [portfolioLastUpdate, setPortfolioLastUpdate] = useState<Date | null>(null); // Not currently used
  const [openOrdersLoading, setOpenOrdersLoading] = useState(true);
  const [openOrdersLastUpdate, setOpenOrdersLastUpdate] = useState<Date | null>(null);
  const [openOrdersError, setOpenOrdersError] = useState<string | null>(null);
  const [executedOrdersLoading, setExecutedOrdersLoading] = useState(true); // Start as true to show loading on initial page load
  const [executedOrdersLastUpdate, setExecutedOrdersLastUpdate] = useState<Date | null>(null);
  const [executedOrdersError, setExecutedOrdersError] = useState<string | null>(null);
  const [portfolioError, setPortfolioError] = useState<string | null>(null);
  const [botStatus, setBotStatus] = useState<{ is_running: boolean; status: 'running' | 'stopped'; reason: string | null; live_trading_enabled?: boolean; mode?: 'LIVE' | 'DRY_RUN'; kill_switch_on?: boolean } | null>(null);
  const [togglingLiveTrading, setTogglingLiveTrading] = useState(false);
  const [openOrders, setOpenOrders] = useState<OpenOrder[]>([]);
  const [executedOrders, setExecutedOrders] = useState<OpenOrder[]>([]);
  const [_openOrdersSummary, setOpenOrdersSummary] = useState<UnifiedOpenOrder[]>([]);
  const [openOrdersPositions, setOpenOrdersPositions] = useState<OpenPosition[]>([]);
  const [_openOrdersSummaryLoading, setOpenOrdersSummaryLoading] = useState(true);
  const [_openOrdersSummaryLastUpdate, setOpenOrdersSummaryLastUpdate] = useState<Date | null>(null);
  const [expectedTPSummary, setExpectedTPSummary] = useState<ExpectedTPSummaryItem[]>([]);
  const [expectedTPDetails, setExpectedTPDetails] = useState<ExpectedTPDetails | null>(null);
  const [expectedTPLoading, setExpectedTPLoading] = useState<boolean>(false);
  const [expectedTPDetailsLoading, setExpectedTPDetailsLoading] = useState<boolean>(false);
  const [expectedTPLastUpdate, setExpectedTPLastUpdate] = useState<Date | null>(null);
  const [expectedTPDetailsSymbol, setExpectedTPDetailsSymbol] = useState<string | null>(null);
  const [showExpectedTPDetailsDialog, setShowExpectedTPDetailsDialog] = useState<boolean>(false);
  const [telegramMessages, setTelegramMessages] = useState<TelegramMessage[]>([]);
  const [telegramMessagesLoading, setTelegramMessagesLoading] = useState<boolean>(false);
  const [snapshotStale, setSnapshotStale] = useState<boolean>(false);
  const [snapshotStaleSeconds, setSnapshotStaleSeconds] = useState<number | null>(null);
  const [snapshotLastUpdated, setSnapshotLastUpdated] = useState<Date | null>(null);
  // const [expandedPositions, setExpandedPositions] = useState<Set<string>>(new Set()); // Not currently used
  const [orderFilter, setOrderFilter] = useState({ symbol: '', status: '', side: '', startDate: '', endDate: '' });
  const [hideCancelled, setHideCancelled] = useState<boolean>(() => {
    if (typeof window === 'undefined') return true;
    const stored = window.localStorage.getItem('executedOrdersHideCancelled');
    return stored === null ? true : stored === 'true';
  });
  const [hideCancelledOpenOrders, setHideCancelledOpenOrders] = useState<boolean>(() => {
    if (typeof window === 'undefined') return true;
    const stored = window.localStorage.getItem('openOrdersHideCancelled');
    return stored === null ? true : stored === 'true';
  });
  const [plPeriod, setPlPeriod] = useState<'daily' | 'weekly' | 'monthly' | 'yearly'>('daily');
  const [selectedMonth, setSelectedMonth] = useState<number>(new Date().getMonth());
  const [selectedYear, setSelectedYear] = useState<number>(new Date().getFullYear());
  const [coinTradeStatus, setCoinTradeStatus] = useState<Record<string, boolean>>({});
  const [coinAlertStatus, setCoinAlertStatus] = useState<Record<string, boolean>>({});  // Legacy - kept for backward compatibility
  const [coinBuyAlertStatus, setCoinBuyAlertStatus] = useState<Record<string, boolean>>({});
  const [coinSellAlertStatus, setCoinSellAlertStatus] = useState<Record<string, boolean>>({});
  const [coinMarginStatus, setCoinMarginStatus] = useState<Record<string, boolean>>({});
  // Subtle "Saved" confirmation messages: { [symbol_type]: { type: 'success' | 'error', timestamp: number } }
  const [alertSavedMessages, setAlertSavedMessages] = useState<Record<string, { type: 'success' | 'error', timestamp: number }>>({});
  const savedMessageTimersRef = useRef<Record<string, NodeJS.Timeout>>({});
  const isInitialLoadRef = useRef<boolean>(true); // Track if we're in initial load phase
  const [coinAmounts, setCoinAmounts] = useState<Record<string, string>>({});
  const [coinSLPercent, setCoinSLPercent] = useState<Record<string, string>>({});
  const [coinTPPercent, setCoinTPPercent] = useState<Record<string, string>>({});
  // Track recently saved amounts to prevent overwriting with stale backend data
  const recentlySavedAmounts = useRef<Record<string, number>>({});
  const [calculatedSL, setCalculatedSL] = useState<Record<string, number>>({});
  const [calculatedTP, setCalculatedTP] = useState<Record<string, number>>({});
  const [showOverrideValues, setShowOverrideValues] = useState<Record<string, {sl: boolean, tp: boolean}>>({});
  const [editingFields, setEditingFields] = useState<Record<string, {sl: boolean, tp: boolean}>>({});
  const [newSymbol, setNewSymbol] = useState('');
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [signals, setSignals] = useState<Record<string, TradingSignals | null>>({});
  const [showSignalConfig, setShowSignalConfig] = useState(false);
  const [isUpdating, setIsUpdating] = useState(false);
  const [dataSourceStatus, setDataSourceStatus] = useState<DataSourceStatus | null>(null);
  const [tradingConfig, setTradingConfig] = useState<TradingConfig | null>(null);
  const [lastUpdateTimes, setLastUpdateTimes] = useState<{[key: string]: {price: Date, signals: Date}}>({});
  const lastUpdateTimesRef = useRef(lastUpdateTimes);
  const [_selectedPreset, setSelectedPreset] = useState('swing'); // Only setSelectedPreset is used
  const [coinPresets, setCoinPresets] = useState<Record<string, string>>({});
  const [showPresetTooltip, setShowPresetTooltip] = useState<string | null>(null);
  const [watchlistOrder, setWatchlistOrder] = useState<Record<string, number>>({});
  const [watchlistItems, setWatchlistItems] = useState<WatchlistItem[]>([]);
  const [tpSlOrderValues, setTpSlOrderValues] = useState<TPSLOrderValues>({});
  const [watchlistFilter, setWatchlistFilter] = useState<string>('');

  // Sorting state for each tab
  const [portfolioSort, setPortfolioSort] = useState<{ field: string | null; direction: 'asc' | 'desc' }>({ field: null, direction: 'asc' });
  const [watchlistSort, setWatchlistSort] = useState<{ field: string | null; direction: 'asc' | 'desc' }>({ field: null, direction: 'asc' });
  const [openOrdersSort, setOpenOrdersSort] = useState<{ field: string | null; direction: 'asc' | 'desc' }>({ field: null, direction: 'asc' });
  const [expectedTPSort, setExpectedTPSort] = useState<{ field: string | null; direction: 'asc' | 'desc' }>({ field: null, direction: 'asc' });
  const [executedOrdersSort, setExecutedOrdersSort] = useState<{ field: string | null; direction: 'asc' | 'desc' }>({ field: null, direction: 'asc' });

  // Sorting utility function
  const handleSort = useCallback((
    field: string,
    sortState: { field: string | null; direction: 'asc' | 'desc' },
    setSortState: React.Dispatch<React.SetStateAction<{ field: string | null; direction: 'asc' | 'desc' }>>
  ) => {
    if (sortState.field === field) {
      // Toggle direction if same field
      setSortState({ field, direction: sortState.direction === 'asc' ? 'desc' : 'asc' });
    } else {
      // New field, start with ascending
      setSortState({ field, direction: 'asc' });
    }
  }, []);

  // Generic sorting function
  const sortData = useCallback(<T,>(
    data: T[],
    field: string | null,
    direction: 'asc' | 'desc',
    getValue: (item: T, field: string) => unknown
  ): T[] => {
    if (!field) return data;
    
    return [...data].sort((a, b) => {
      const aVal = getValue(a, field);
      const bVal = getValue(b, field);
      
      // Handle null/undefined values
      if (aVal == null && bVal == null) return 0;
      if (aVal == null) return 1;
      if (bVal == null) return -1;
      
      // Handle numbers
      if (typeof aVal === 'number' && typeof bVal === 'number') {
        return direction === 'asc' ? aVal - bVal : bVal - aVal;
      }
      
      // Handle strings
      const aStr = String(aVal).toLowerCase();
      const bStr = String(bVal).toLowerCase();
      if (direction === 'asc') {
        return aStr < bStr ? -1 : aStr > bStr ? 1 : 0;
      } else {
        return aStr > bStr ? -1 : aStr < bStr ? 1 : 0;
      }
    });
  }, []);

  // Sortable header component
  const SortableHeader = ({ 
    field, 
    children, 
    sortState, 
    setSortState, 
    className = '' 
  }: { 
    field: string; 
    children: React.ReactNode; 
    sortState: { field: string | null; direction: 'asc' | 'desc' };
    setSortState: React.Dispatch<React.SetStateAction<{ field: string | null; direction: 'asc' | 'desc' }>>;
    className?: string;
  }) => {
    const isActive = sortState.field === field;
    const direction = isActive ? sortState.direction : null;
    
    return (
      <th 
        className={`${className} cursor-pointer select-none hover:bg-gray-600 transition-colors`}
        onClick={() => handleSort(field, sortState, setSortState)}
        title={`Click to sort by ${field}`}
      >
        <div className="flex items-center gap-1">
          <span>{children}</span>
          {direction === 'asc' && <span className="text-xs">▲</span>}
          {direction === 'desc' && <span className="text-xs">▼</span>}
          {!isActive && <span className="text-xs text-gray-400">⇅</span>}
        </div>
      </th>
    );
  };

  const persistAlertFlag = useCallback(
    (
      setter: React.Dispatch<React.SetStateAction<Record<string, boolean>>>,
      storageKey: string,
      symbolKey: string,
      value: boolean
    ) => {
      setter(prev => {
        const updated = { ...prev };
        if (value) {
          updated[symbolKey] = value;
        } else {
          delete updated[symbolKey];
        }
        try {
          localStorage.setItem(storageKey, JSON.stringify(updated));
        } catch (err) {
          logger.warn(`Failed to persist ${storageKey}:`, err);
        }
        return updated;
      });
    },
    []
  );

  const handleMasterAlertToggle = useCallback(
    async (symbol: string) => {
      const normalizedSymbol = symbol.toUpperCase();
      const previousBuy = coinBuyAlertStatus[normalizedSymbol] ?? false;
      const previousSell = coinSellAlertStatus[normalizedSymbol] ?? false;
      const storedMaster = coinAlertStatus[normalizedSymbol];
      const previousMaster =
        storedMaster !== undefined ? storedMaster : previousBuy || previousSell;
      const newStatus = !previousMaster;

      const applyState = (masterValue: boolean, buyValue: boolean, sellValue: boolean) => {
        persistAlertFlag(setCoinAlertStatus, 'watchlist_alert_status', normalizedSymbol, masterValue);
        persistAlertFlag(setCoinBuyAlertStatus, 'watchlist_buy_alert_status', normalizedSymbol, buyValue);
        persistAlertFlag(setCoinSellAlertStatus, 'watchlist_sell_alert_status', normalizedSymbol, sellValue);
      };

      applyState(newStatus, newStatus, newStatus);

      const messageKey = `${normalizedSymbol}_alerts`;

      try {
        const baseResponse = await updateWatchlistAlert(normalizedSymbol, newStatus);
        const [buyResponse, sellResponse] = await Promise.all([
          updateBuyAlert(normalizedSymbol, newStatus),
          updateSellAlert(normalizedSymbol, newStatus)
        ]);

        const resolvedMaster =
          baseResponse?.alert_enabled !== undefined ? baseResponse.alert_enabled : newStatus;
        const resolvedBuy =
          buyResponse?.buy_alert_enabled !== undefined ? buyResponse.buy_alert_enabled : newStatus;
        const resolvedSell =
          sellResponse?.sell_alert_enabled !== undefined ? sellResponse.sell_alert_enabled : newStatus;

        applyState(!!resolvedMaster, !!resolvedBuy, !!resolvedSell);

        setAlertSavedMessages(prev => ({
          ...prev,
          [messageKey]: { type: 'success', timestamp: Date.now() }
        }));
        if (savedMessageTimersRef.current[messageKey]) {
          clearTimeout(savedMessageTimersRef.current[messageKey]);
        }
        savedMessageTimersRef.current[messageKey] = setTimeout(() => {
          setAlertSavedMessages(prev => {
            const updated = { ...prev };
            delete updated[messageKey];
            return updated;
          });
          delete savedMessageTimersRef.current[messageKey];
        }, 2500);
      } catch (error) {
        const errorObj = error as { detail?: string; message?: string };
        logger.error(`❌ Failed to toggle alerts for ${normalizedSymbol}:`, error);
        applyState(previousMaster, previousBuy, previousSell);
        const errorMsg = errorObj.detail || errorObj.message || 'Error desconocido';
        alert(`Error updating alerts for ${normalizedSymbol}: ${errorMsg}`);
      }
    },
    [coinAlertStatus, coinBuyAlertStatus, coinSellAlertStatus, persistAlertFlag]
  );

  const fetchTelegramMessages = useCallback(
    async (options?: { silent?: boolean }) => {
      const silent = options?.silent ?? false;
      if (!silent) {
        setTelegramMessagesLoading(true);
      }
      try {
        const response = await getTelegramMessages();
        const messages = response.messages || [];
        setTelegramMessages(messages);
        handleNewMessages(messages);
      } catch (err) {
        logger.error('Failed to fetch Telegram messages:', err);
      } finally {
        if (!silent) {
          setTelegramMessagesLoading(false);
        }
      }
    },
    [handleNewMessages]
  );
  
  // Strategy presets configuration state (editable)
  const [presetsConfig, setPresetsConfig] = useState<PresetConfig>(() => PRESET_CONFIG);
  const [selectedConfigPreset, setSelectedConfigPreset] = useState<Preset>('Swing');
  const [selectedConfigRisk, setSelectedConfigRisk] = useState<RiskMode>('Conservative');
  const topCoinsRef = useRef<TopCoin[]>([]); // Keep ref to latest topCoins
  const schedulerRef = useRef<{
    fastTimer: ReturnType<typeof setTimeout> | null;
    slowTimer: ReturnType<typeof setTimeout> | null;
    fastBackoffMs: number;
    fastPausedUntil: number;
    fastErrorCount: number;
    slowErrorCount: number;
    slowBackoffMs: number;
    slowTickCount: number;
  }>({
    fastTimer: null,
    slowTimer: null,
    fastBackoffMs: REFRESH_FAST_MS,
    fastPausedUntil: 0,
    fastErrorCount: 0,
    slowErrorCount: 0,
    slowBackoffMs: REFRESH_SLOW_MS,
    slowTickCount: 0,
  });
  const fastQueueRef = useRef<string[]>([]);
  const slowQueueRef = useRef<string[]>([]);
  const lastFastErrorRef = useRef<ApiError | null>(null);
  const [fastQueueRateLimited, setFastQueueRateLimited] = useState(false);
  const activeJobsRef = useRef(0);
  const markJobStart = useCallback(() => {
    activeJobsRef.current += 1;
    setIsUpdating(true);
  }, []);
  const markJobEnd = useCallback(() => {
    activeJobsRef.current = Math.max(0, activeJobsRef.current - 1);
    if (activeJobsRef.current === 0) {
      setIsUpdating(false);
    }
  }, []);
  // Helper function to check if an order status is cancelled, rejected, or expired
  // NOTE: FILLED orders are NOT considered cancelled - they are valid executed orders
  // Must be defined before useMemo hooks that use it to avoid TDZ (Temporal Dead Zone) errors
  // Wrapped in useCallback to ensure stable reference for dependency arrays
  const isCancelledStatus = useCallback((status: string | null | undefined): boolean => {
    if (!status) return false;
    const normalized = status.toUpperCase();
    // Include only statuses that should be hidden when "Ocultar Canceladas" is ON:
    // - CANCELLED/CANCELED: explicitly cancelled orders
    // - REJECTED: orders that were rejected by the exchange
    // - EXPIRED: orders that expired
    // DO NOT include FILLED - those are valid executed orders that should be shown
    return normalized === 'CANCELLED' || 
           normalized === 'CANCELED' || 
           normalized === 'REJECTED' || 
           normalized === 'EXPIRED';
  }, []);

  const coinMembershipSignature = useMemo(
    () => {
      // Defensive check: ensure topCoins is an array and not undefined/null
      if (!topCoins || !Array.isArray(topCoins) || topCoins.length === 0) return '';
      try {
        return topCoins
          .map((coin) => coin?.instrument_name)
          .filter((name): name is string => Boolean(name))
          .sort()
          .join('|');
      } catch (err) {
        logger.error('Error in coinMembershipSignature:', err);
        return '';
      }
    },
    [topCoins]
  );
  const filteredOpenOrders = useMemo(() => {
    // Defensive check: ensure openOrders is an array
    if (!Array.isArray(openOrders)) return [];
    // Sort orders by creation date (newest first)
    const sortedOrders = [...openOrders].sort((a, b) => {
      const aTime = a.create_time || 0;
      const bTime = b.create_time || 0;
      // Convert to numbers if they're strings
      const aNum = typeof aTime === 'number' ? aTime : (typeof aTime === 'string' ? new Date(aTime).getTime() : 0);
      const bNum = typeof bTime === 'number' ? bTime : (typeof bTime === 'string' ? new Date(bTime).getTime() : 0);
      return bNum - aNum; // Descending order (newest first)
    });
    
    return sortedOrders.filter(order => {
      // Filter out cancelled orders if hideCancelledOpenOrders is true
      if (hideCancelledOpenOrders && isCancelledStatus(order.status)) {
        return false;
      }
      
      const matchesSymbol =
        !orderFilter.symbol ||
        (order.instrument_name &&
          order.instrument_name.toLowerCase().includes(orderFilter.symbol.toLowerCase()));
      const matchesStatus = !orderFilter.status || order.status === orderFilter.status;
      const matchesSide = !orderFilter.side || order.side === orderFilter.side;
      
      // Date filtering
      let matchesDate = true;
      if (orderFilter.startDate || orderFilter.endDate) {
        // Get order date from create_time (timestamp in milliseconds)
        const orderDate = order.create_time 
          ? (typeof order.create_time === 'number' ? new Date(order.create_time) : new Date(order.create_time))
          : null;
        
        if (orderDate && !isNaN(orderDate.getTime())) {
          // Set time to start of day for comparison
          const orderDateOnly = new Date(orderDate.getFullYear(), orderDate.getMonth(), orderDate.getDate());
          
          if (orderFilter.startDate) {
            const startDate = new Date(orderFilter.startDate);
            startDate.setHours(0, 0, 0, 0);
            if (orderDateOnly < startDate) {
              matchesDate = false;
            }
          }
          
          if (orderFilter.endDate && matchesDate) {
            const endDate = new Date(orderFilter.endDate);
            endDate.setHours(23, 59, 59, 999);
            if (orderDateOnly > endDate) {
              matchesDate = false;
            }
          }
        } else {
          // If order has no valid date and date filter is set, exclude it
          matchesDate = false;
        }
      }
      
      return matchesSymbol && matchesStatus && matchesSide && matchesDate;
    });
  }, [openOrders, orderFilter, hideCancelledOpenOrders, isCancelledStatus]);
  // Helper function to calculate profit/loss for an executed order
  const calculateProfitLoss = useCallback((order: OpenOrder, allOrders: OpenOrder[]): { pnl: number; pnlPercent: number; isRealized: boolean } => {
    const orderSymbol = order.instrument_name;
    const orderSide = order.side?.toUpperCase();
    const orderPrice = parseFloat(order.price || order.avg_price || order.filled_price || '0');
    const orderQuantity = parseFloat(order.quantity || order.filled_quantity || order.cumulative_quantity || '0');
    const orderTime = order.update_time || order.create_time || 0;
    
    if (orderSide === 'SELL' && orderPrice > 0 && orderQuantity > 0) {
      // Strategy: 
      // 1. First, try to find a BUY order CREATED at the same time (paired orders like TP/SL)
      // 2. If no paired order, find an old BUY order with similar volume (within 20% difference)
      
      const TIME_WINDOW_MS = 5 * 60 * 1000; // 5 minutes tolerance for creation time matching
      const VOLUME_TOLERANCE = 0.20; // 20% tolerance for volume matching
      
      const orderCreateTime = order.create_time || orderTime;
      
      // Get all BUY orders for this symbol
      const allBuyOrders = allOrders
        .filter(o => 
          o.instrument_name === orderSymbol &&
          o.side?.toUpperCase() === 'BUY' &&
          o.status === 'FILLED'
        );
      
      if (allBuyOrders.length > 0) {
        let matchedBuyOrder: OpenOrder | null = null;
        let matchType: 'paired' | 'similar_volume' | null = null;
        
        // Step 1: Look for BUY order CREATED at the same time (paired orders)
        const pairedBuyOrders = allBuyOrders.filter(buyOrder => {
          const buyCreateTime = buyOrder.create_time || buyOrder.update_time || 0;
          const timeDiff = Math.abs(orderCreateTime - buyCreateTime);
          return timeDiff <= TIME_WINDOW_MS;
        });
        
        if (pairedBuyOrders.length > 0) {
          // If multiple paired orders, prefer the one with most similar volume
          matchedBuyOrder = pairedBuyOrders.reduce((best, current) => {
            const bestQty = parseFloat(best.quantity || best.filled_quantity || best.cumulative_quantity || '0');
            const currentQty = parseFloat(current.quantity || current.filled_quantity || current.cumulative_quantity || '0');
            const bestDiff = Math.abs(bestQty - orderQuantity);
            const currentDiff = Math.abs(currentQty - orderQuantity);
            return currentDiff < bestDiff ? current : best;
          });
          matchType = 'paired';
        } else {
          // Step 2: Look for old BUY order with similar volume (within 20% tolerance)
          const similarVolumeBuyOrders = allBuyOrders
            .filter(buyOrder => {
              const buyQty = parseFloat(buyOrder.quantity || buyOrder.filled_quantity || buyOrder.cumulative_quantity || '0');
              if (buyQty <= 0) return false;
              const volumeDiff = Math.abs(buyQty - orderQuantity) / orderQuantity;
              return volumeDiff <= VOLUME_TOLERANCE;
            })
            .sort((a, b) => {
              // Prefer older orders (executed before this SELL)
              const aTime = a.update_time || a.create_time || 0;
              const bTime = b.update_time || b.create_time || 0;
              // Prefer orders executed before the SELL
              if (aTime < orderTime && bTime >= orderTime) return -1;
              if (bTime < orderTime && aTime >= orderTime) return 1;
              // Among orders before SELL, prefer the most recent
              if (aTime < orderTime && bTime < orderTime) return bTime - aTime;
              // Among orders after SELL, prefer the oldest
              return aTime - bTime;
            });
          
          if (similarVolumeBuyOrders.length > 0) {
            matchedBuyOrder = similarVolumeBuyOrders[0];
            matchType = 'similar_volume';
          }
        }
        
        if (matchedBuyOrder) {
          const buyPrice = parseFloat(matchedBuyOrder.price || matchedBuyOrder.avg_price || matchedBuyOrder.filled_price || '0');
          const buyQty = parseFloat(matchedBuyOrder.quantity || matchedBuyOrder.filled_quantity || matchedBuyOrder.cumulative_quantity || '0');
          
          if (buyPrice > 0 && buyQty > 0) {
            const sellValue = orderPrice * orderQuantity;
            const buyValue = buyPrice * orderQuantity;
            const pnl = sellValue - buyValue;
            const pnlPercent = buyPrice > 0 ? ((orderPrice - buyPrice) / buyPrice) * 100 : 0;
            
            // Debug logging
            if (orderSymbol === 'ETH_USD' && orderPrice === 3649.25) {
              const buyCreateTime = matchedBuyOrder.create_time || matchedBuyOrder.update_time || 0;
              const sellCreateTime = order.create_time || orderTime;
              logger.info(`📊 P/L Calculation for ETH_USD SELL:`, {
                sellOrder_id: order.order_id,
                sellQty: orderQuantity,
                sellPrice: orderPrice,
                sellValue: sellValue,
                sellCreateTime: sellCreateTime,
                matchType: matchType,
                matchedBuyOrder: {
                  order_id: matchedBuyOrder.order_id,
                  buyPrice: buyPrice,
                  buyQty: buyQty,
                  buyCreateTime: buyCreateTime,
                  createTimeDiff: Math.abs(sellCreateTime - buyCreateTime)
                },
                buyValue: buyValue,
                pnl: pnl,
                pnlPercent: pnlPercent,
                calculation: `(${orderPrice} - ${buyPrice.toFixed(2)}) × ${orderQuantity} = ${pnl.toFixed(2)}`
              });
            }
            
            // General logging for all SELL orders
            const buyCreateTime = matchedBuyOrder.create_time || matchedBuyOrder.update_time || 0;
            const sellCreateTime = order.create_time || orderTime;
            logger.info(`💰 P/L for ${orderSymbol} SELL (${orderQuantity} @ ${orderPrice}):`, {
              matchType: matchType,
              matchedBuyOrder_id: matchedBuyOrder.order_id,
              buyPrice: buyPrice.toFixed(2),
              buyQty: buyQty,
              createTimeDiff: Math.abs(sellCreateTime - buyCreateTime),
              pnl: pnl.toFixed(2),
              pnlPercent: pnlPercent.toFixed(2) + '%'
            });
            
            return { pnl, pnlPercent, isRealized: true };
          }
        }
      }
    } else if (orderSide === 'BUY' && orderPrice > 0 && orderQuantity > 0) {
      // BUY orders only show theoretical P/L (not counted in realized P/L)
      // Calculate theoretical P/L using current market price
      const coin = topCoins.find(c => c.instrument_name === orderSymbol);
      if (coin && coin.current_price > 0) {
        const currentValue = coin.current_price * orderQuantity;
        const buyValue = orderPrice * orderQuantity;
        const pnl = currentValue - buyValue;
        const pnlPercent = orderPrice > 0 ? ((coin.current_price - orderPrice) / orderPrice) * 100 : 0;
        
        // Always return isRealized: false for BUY orders (theoretical P/L only)
        return { pnl, pnlPercent, isRealized: false };
      }
    }
    
    return { pnl: 0, pnlPercent: 0, isRealized: false };
  }, [topCoins]);

  const filteredExecutedOrders = useMemo(() => {
    // Defensive check: ensure executedOrders is an array
    if (!Array.isArray(executedOrders)) return [];
    
    const filtered = executedOrders.filter(order => {
      // CRITICAL: Filter out cancelled/rejected/expired orders if hideCancelled is true
      // BUT NEVER filter out FILLED orders - those are the main executed orders we want to show
      if (hideCancelled && order.status) {
        const normalized = order.status.toUpperCase();
        // Only hide CANCELLED, REJECTED, EXPIRED - NEVER FILLED
        // IMPORTANT: FILLED orders should ALWAYS pass through this filter
        if (normalized === 'CANCELLED' || 
            normalized === 'CANCELED' || 
            normalized === 'REJECTED' || 
            normalized === 'EXPIRED') {
          return false; // Filter out cancelled/rejected/expired
        }
        // For FILLED and all other statuses, continue to other filters
      }
      
      // Apply other filters (symbol, status, side, date)
      // These filters apply to ALL orders including FILLED
      const matchesSymbol = !orderFilter.symbol || (order.instrument_name && order.instrument_name.toLowerCase().includes(orderFilter.symbol.toLowerCase()));
      const matchesStatus = !orderFilter.status || order.status === orderFilter.status;
      const matchesSide = !orderFilter.side || order.side === orderFilter.side;
      
      // Date filtering
      let matchesDate = true;
      if (orderFilter.startDate || orderFilter.endDate) {
        // Get order date from update_time or create_time (timestamp in milliseconds)
        const orderDate = order.update_time 
          ? (typeof order.update_time === 'number' ? new Date(order.update_time) : new Date(order.update_time))
          : (order.create_time 
            ? (typeof order.create_time === 'number' ? new Date(order.create_time) : new Date(order.create_time))
            : null);
        
        if (orderDate && !isNaN(orderDate.getTime())) {
          // Set time to start of day for comparison
          const orderDateOnly = new Date(orderDate.getFullYear(), orderDate.getMonth(), orderDate.getDate());
          
          if (orderFilter.startDate) {
            const startDate = new Date(orderFilter.startDate);
            startDate.setHours(0, 0, 0, 0);
            if (orderDateOnly < startDate) {
              matchesDate = false;
            }
          }
          
          if (orderFilter.endDate && matchesDate) {
            const endDate = new Date(orderFilter.endDate);
            endDate.setHours(23, 59, 59, 999);
            if (orderDateOnly > endDate) {
              matchesDate = false;
            }
          }
        } else {
          // If order has no valid date and date filter is set, exclude it
          matchesDate = false;
        }
      }
      
      return matchesSymbol && matchesStatus && matchesSide && matchesDate;
    });
    
    // Debug: Log filtered orders to help diagnose filtering issues
    if (filtered.length === 0 && executedOrders.length > 0) {
      const statusBreakdown = executedOrders.reduce((acc, o) => {
        const status = (o.status || 'UNKNOWN').toUpperCase();
        acc[status] = (acc[status] || 0) + 1;
        return acc;
      }, {} as Record<string, number>);
      logger.warn(`⚠️ All ${executedOrders.length} executed orders were filtered out. Status breakdown:`, statusBreakdown);
      logger.warn(`⚠️ Filter settings: hideCancelled=${hideCancelled}, orderFilter:`, orderFilter);
      logger.warn(`⚠️ Sample orders:`, executedOrders.slice(0, 3).map(o => ({
        order_id: o.order_id,
        status: o.status,
        instrument_name: o.instrument_name
      })));
    }
    return filtered;
  }, [executedOrders, orderFilter, hideCancelled]);
  
  // Calculate total P&L for filtered orders (only SELL orders count as realized P/L)
  const filteredTotalPL = useMemo(() => {
    // Defensive checks: ensure dependencies are initialized
    if (!Array.isArray(filteredExecutedOrders) || !Array.isArray(executedOrders) || typeof calculateProfitLoss !== 'function') {
      return 0;
    }
    let totalPL = 0;
    filteredExecutedOrders.forEach(order => {
      if (order.side?.toUpperCase() === 'SELL') {
        const pnlData = calculateProfitLoss(order, executedOrders);
        if (pnlData.isRealized) {
          totalPL += pnlData.pnl;
        }
      }
    });
    return totalPL;
  }, [filteredExecutedOrders, executedOrders, calculateProfitLoss]);
  
  // Calculate P/L Summary
  const plSummary = useMemo(() => {
    try {
      const now = new Date();
      let startDate: Date;
      let endDate: Date = new Date();
      
      if (plPeriod === 'daily') {
        startDate = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      } else if (plPeriod === 'weekly') {
        const dayOfWeek = now.getDay();
        const diff = now.getDate() - dayOfWeek + (dayOfWeek === 0 ? -6 : 1);
        startDate = new Date(now.getFullYear(), now.getMonth(), diff);
      } else if (plPeriod === 'monthly') {
        startDate = new Date(selectedYear, selectedMonth, 1);
        endDate = new Date(selectedYear, selectedMonth + 1, 0, 23, 59, 59);
      } else {
        startDate = new Date(selectedYear, 0, 1);
        endDate = new Date(selectedYear, 11, 31, 23, 59, 59);
      }
      
      const startTime = startDate.getTime();
      const endTime = endDate.getTime();
      
      logger.info(`📊 P/L Summary calculation: period=${plPeriod}, startTime=${new Date(startTime).toISOString()}, endTime=${new Date(endTime).toISOString()}`);
      logger.info(`📊 executedOrders count: ${executedOrders?.length || 0}, portfolio assets: ${portfolio?.assets?.length || 0}, topCoins: ${topCoins?.length || 0}`);
      
      let realizedPL = 0;
      // Additional defensive check
      if (Array.isArray(executedOrders) && executedOrders.length > 0 && typeof calculateProfitLoss === 'function') {
        const realizedOrders = executedOrders.filter(order => {
          if (!order || order.side?.toUpperCase() !== 'SELL' || order.status !== 'FILLED') return false;
          const orderTime = order.update_time || order.create_time || 0;
          return orderTime >= startTime && orderTime <= endTime;
        });
        
        logger.info(`📊 Found ${realizedOrders.length} SELL orders in period`);
        
        realizedOrders.forEach(order => {
          try {
            const pnlData = calculateProfitLoss(order, executedOrders);
            if (pnlData && pnlData.isRealized) {
              realizedPL += pnlData.pnl || 0;
              logger.info(`💰 Realized P/L for ${order.instrument_name}: $${pnlData.pnl?.toFixed(2)}`);
            }
          } catch (err) {
            logger.warn(`⚠️ Error calculating P/L for ${order.instrument_name}:`, err);
          }
        });
      }
      
      logger.info(`📊 Total realizedPL: $${realizedPL.toFixed(2)}`);
      
      // Potential P/L: Theoretical gains from ALL open positions (unrealized P/L)
      // Calculate based on current portfolio positions vs their entry prices
      // IMPORTANT: Don't filter by period - calculate P/L for ALL open positions regardless of when they were bought
      let potentialPL = 0;
      if (portfolio?.assets && portfolio.assets.length > 0 && topCoins && topCoins.length > 0 && executedOrders && executedOrders.length > 0) {
        logger.info(`📊 Calculating potential P/L for ${portfolio.assets.length} portfolio assets (all open positions, not filtered by period)`);
        // Calculate potential P/L for each portfolio asset
        portfolio.assets.forEach(asset => {
          try {
            if (!asset.coin || asset.balance <= 0) return;
            
            const assetSymbol = asset.coin.toUpperCase();
            const assetBase = assetSymbol.split('_')[0];
            
            // Find current price from topCoins
            const coin = topCoins.find(c => {
              const coinSymbol = (c?.instrument_name || '').toUpperCase();
              return coinSymbol === assetSymbol || coinSymbol.startsWith(assetBase + '_');
            });
            
            if (!coin || !coin.current_price || coin.current_price <= 0) {
              logger.debug(`⚠️ No current price found for ${assetSymbol}`);
              return;
            }
            
            // Find ALL BUY orders for this asset to get entry price (not filtered by period)
            // Look for BUY orders that match this asset (by symbol or base currency)
            const buyOrders = executedOrders.filter(order => {
              if (!order || order.side?.toUpperCase() !== 'BUY' || order.status !== 'FILLED') return false;
              const orderSymbol = (order.instrument_name || '').toUpperCase();
              const orderBase = orderSymbol.split('_')[0];
              return orderSymbol === assetSymbol || orderBase === assetBase;
            });
            
            if (buyOrders.length === 0) {
              logger.debug(`⚠️ No BUY orders found for ${assetSymbol} (total executedOrders: ${executedOrders.length})`);
              return;
            }
            
            logger.debug(`📊 Found ${buyOrders.length} BUY orders for ${assetSymbol}`);
            
            // Calculate average entry price from all BUY orders
            // Weight by quantity to get true average entry price
            let totalCost = 0;
            let totalQuantity = 0;
            buyOrders.forEach(buyOrder => {
              const buyPrice = parseFloat(buyOrder.price || buyOrder.avg_price || buyOrder.filled_price || '0');
              const buyQty = parseFloat(buyOrder.quantity || buyOrder.filled_quantity || buyOrder.cumulative_quantity || '0');
              if (buyPrice > 0 && buyQty > 0) {
                totalCost += buyPrice * buyQty;
                totalQuantity += buyQty;
              }
            });
            
            if (totalQuantity <= 0) {
              logger.debug(`⚠️ Invalid totalQuantity for ${assetSymbol} (totalCost: ${totalCost}, totalQuantity: ${totalQuantity})`);
              return;
            }
            
            const avgEntryPrice = totalCost / totalQuantity;
            
            // Check if position was fully sold (all SELL orders match or exceed BUY quantity)
            // IMPORTANT: Don't filter by period - check ALL SELL orders
            const sellOrders = executedOrders.filter(order => {
              if (!order || order.side?.toUpperCase() !== 'SELL' || order.status !== 'FILLED') return false;
              const orderSymbol = (order.instrument_name || '').toUpperCase();
              const orderBase = orderSymbol.split('_')[0];
              return orderSymbol === assetSymbol || orderBase === assetBase;
            });
            
            const totalSoldQty = sellOrders.reduce((sum, sellOrder) => {
              const qty = parseFloat(sellOrder.quantity || sellOrder.filled_quantity || sellOrder.cumulative_quantity || '0');
              return sum + qty;
            }, 0);
            
            // Only calculate if position is still open (not fully sold)
            if (totalSoldQty < totalQuantity) {
              // Calculate P/L based on current balance (remaining position)
              // Use the smaller of: current balance, or remaining quantity after sales
              const remainingQty = Math.min(asset.balance, totalQuantity - totalSoldQty);
              const currentValue = coin.current_price * remainingQty;
              const entryValue = avgEntryPrice * remainingQty;
              const assetPL = currentValue - entryValue;
              potentialPL += assetPL;
              logger.info(`💰 Potential P/L for ${assetSymbol}: $${assetPL.toFixed(2)} (balance: ${asset.balance.toFixed(8)}, remaining: ${remainingQty.toFixed(8)}, entry: $${avgEntryPrice.toFixed(2)}, current: $${coin.current_price.toFixed(2)}, bought: ${totalQuantity.toFixed(8)}, sold: ${totalSoldQty.toFixed(8)})`);
            } else {
              logger.debug(`⚠️ Position ${assetSymbol} fully sold (sold: ${totalSoldQty}, bought: ${totalQuantity})`);
            }
          } catch (err) {
            logger.warn(`⚠️ Error calculating potential P/L for ${asset.coin}:`, err);
          }
        });
      } else {
        logger.warn(`⚠️ Missing data for potential P/L: portfolio.assets=${portfolio?.assets?.length || 0}, topCoins=${topCoins?.length || 0}, executedOrders=${executedOrders?.length || 0}`);
      }
      
      logger.info(`📊 Total potentialPL: $${potentialPL.toFixed(2)}, totalPL: $${(realizedPL + potentialPL).toFixed(2)}`);
      
      return { realizedPL, potentialPL, totalPL: realizedPL + potentialPL };
    } catch (err) {
      logger.error('Error calculating P/L summary:', err);
      return { realizedPL: 0, potentialPL: 0, totalPL: 0 };
    }
  }, [plPeriod, selectedMonth, selectedYear, executedOrders, topCoins, calculateProfitLoss, portfolio]);

  const orderedWatchlistCoins = useMemo(() => {
    // Defensive check: ensure topCoins is an array
    if (!Array.isArray(topCoins) || topCoins.length === 0) {
      // Silently return empty array during initial load
      return [];
    }

    // Note: LDO_USD availability check removed - debug logs were cluttering console

    const coinsCopy = [...topCoins];
    coinsCopy.sort((a, b) => {
      const aTradeEnabled = coinTradeStatus[normalizeSymbolKey(a.instrument_name)] || false;
      const bTradeEnabled = coinTradeStatus[normalizeSymbolKey(b.instrument_name)] || false;

      if (aTradeEnabled && !bTradeEnabled) return -1;
      if (!aTradeEnabled && bTradeEnabled) return 1;

      const orderA = watchlistOrder[a.instrument_name];
      const orderB = watchlistOrder[b.instrument_name];

      if (orderA !== undefined || orderB !== undefined) {
        const normalizedA = orderA ?? Number.MAX_SAFE_INTEGER;
        const normalizedB = orderB ?? Number.MAX_SAFE_INTEGER;
        if (normalizedA !== normalizedB) {
          return normalizedA - normalizedB;
        }
      }

      return (a.rank || 0) - (b.rank || 0);
    });
    return coinsCopy;
  }, [topCoins, coinTradeStatus, watchlistOrder]);

  const watchlistPositionMap = useMemo(() => {
    if (!orderedWatchlistCoins.length) {
      return {};
    }
    return orderedWatchlistCoins.reduce<Record<string, number>>((acc, coin, index) => {
      acc[coin.instrument_name] = index;
      return acc;
    }, {});
  }, [orderedWatchlistCoins]);

  // Sorted portfolio data
  const sortedPortfolioData = useMemo(() => {
    if (!portfolio || !portfolio.assets || portfolio.assets.length === 0) {
      return [];
    }
    
    if (!portfolioSort.field) {
      // Default sort by USD value descending (original behavior)
      return [...portfolio.assets].sort((a, b) => (b.value_usd ?? 0) - (a.value_usd ?? 0));
    }
    
    return sortData(portfolio.assets, portfolioSort.field, portfolioSort.direction, (item, field) => {
      switch (field) {
        case 'coin':
          return item.coin || '';
        case 'balance':
          return item.balance ?? 0;
        case 'reserved':
          return item.reserved_qty ?? 0;
        case 'usd_value':
          return item.value_usd ?? 0;
        case 'percent':
          const totalValue = portfolio.total_value_usd ?? 0;
          return totalValue > 0 ? ((item.value_usd ?? 0) / totalValue) * 100 : 0;
        default:
          return 0;
      }
    });
  }, [portfolio, portfolioSort, sortData]);

  // Sorted open orders data
  const sortedOpenOrdersData = useMemo(() => {
    if (!filteredOpenOrders || filteredOpenOrders.length === 0) {
      return [];
    }
    
    if (!openOrdersSort.field) {
      return filteredOpenOrders;
    }
    
    return sortData(filteredOpenOrders, openOrdersSort.field, openOrdersSort.direction, (item, field) => {
      switch (field) {
        case 'created_date':
          return item.create_time ?? 0;
        case 'symbol':
          return item.instrument_name || '';
        case 'side':
          return item.side || '';
        case 'type':
          return item.order_type || '';
        case 'quantity':
          return parseFloat(item.quantity || '0');
        case 'price':
          return parseFloat(item.price || '0');
        case 'status':
          return item.status || '';
        default:
          return 0;
      }
    });
  }, [filteredOpenOrders, openOrdersSort, sortData]);

  // Sorted expected TP data
  const sortedExpectedTPData = useMemo(() => {
    if (!expectedTPSummary || expectedTPSummary.length === 0) {
      return [];
    }
    
    if (!expectedTPSort.field) {
      return expectedTPSummary;
    }
    
    return sortData(expectedTPSummary, expectedTPSort.field, expectedTPSort.direction, (item, field) => {
      switch (field) {
        case 'symbol':
          return item.symbol || '';
        case 'net_qty':
          return item.net_qty ?? 0;
        case 'current_price':
          return item.current_price ?? 0;
        case 'position_value':
          return item.position_value ?? 0;
        case 'covered_qty':
          return item.covered_qty ?? 0;
        case 'uncovered_qty':
          return item.uncovered_qty ?? 0;
        case 'expected_profit':
          return item.total_expected_profit ?? 0;
        case 'coverage':
          return item.net_qty > 0 ? (item.covered_qty / item.net_qty) * 100 : 0;
        default:
          return 0;
      }
    });
  }, [expectedTPSummary, expectedTPSort, sortData]);

  // Sorted executed orders data
  const sortedExecutedOrdersData = useMemo(() => {
    if (!filteredExecutedOrders || filteredExecutedOrders.length === 0) {
      return [];
    }
    
    if (!executedOrdersSort.field) {
      return filteredExecutedOrders;
    }
    
    return sortData(filteredExecutedOrders, executedOrdersSort.field, executedOrdersSort.direction, (item, field) => {
      switch (field) {
        case 'created_date':
          return item.create_time ?? 0;
        case 'symbol':
          return item.instrument_name || '';
        case 'side':
          return item.side || '';
        case 'type':
          return item.order_type || '';
        case 'quantity':
          return parseFloat(item.quantity || '0');
        case 'price':
          return parseFloat(item.price || '0');
        case 'total_value':
          return parseFloat(item.quantity || '0') * parseFloat(item.price || '0');
        case 'execution_time':
          return item.update_time ?? item.create_time ?? 0;
        case 'status':
          return item.status || '';
        default:
          return 0;
      }
    });
  }, [filteredExecutedOrders, executedOrdersSort, sortData]);

  const visibleWatchlistCoins = useMemo(
    () => {
      // Defensive check: ensure orderedWatchlistCoins is an array
      if (!Array.isArray(orderedWatchlistCoins)) return [];
      // Filter out deleted coins and show all remaining coins
      const deletedCoins = (() => {
        try {
          const deleted = localStorage.getItem('deleted_coins');
          return deleted ? JSON.parse(deleted) as string[] : [];
        } catch {
          return [];
        }
      })();
      
      const filtered = orderedWatchlistCoins.filter(coin => {
        const coinName = coin.instrument_name.toUpperCase();
        return !deletedCoins.some(deleted => deleted.toUpperCase() === coinName);
      });
      
      // Apply search filter if provided
      if (watchlistFilter.trim()) {
        const filterUpper = watchlistFilter.trim().toUpperCase();
        return filtered.filter(coin => {
          const coinName = coin.instrument_name.toUpperCase();
          return coinName.includes(filterUpper);
        });
      }
      
      return filtered;
    },
    [orderedWatchlistCoins, watchlistFilter]
  );

  // Sorted watchlist data (depends on visibleWatchlistCoins)
  const sortedWatchlistData = useMemo(() => {
    if (!visibleWatchlistCoins || visibleWatchlistCoins.length === 0) {
      return [];
    }
    
    if (!watchlistSort.field) {
      return visibleWatchlistCoins;
    }
    
    return sortData(visibleWatchlistCoins, watchlistSort.field, watchlistSort.direction, (item, field) => {
      switch (field) {
        case 'symbol':
          return item.instrument_name || '';
        case 'last_price':
          return item.current_price ?? 0;
        case 'amount_usd':
          return parseFloat(coinAmounts[normalizeSymbolKey(item.instrument_name)] || '0');
        case 'rsi':
          return signals[item.instrument_name]?.rsi ?? 0;
        case 'atr':
          return signals[item.instrument_name]?.atr ?? 0;
        case 'sl_price':
          return calculatedSL[item.instrument_name] ?? 0;
        case 'tp_price':
          return calculatedTP[item.instrument_name] ?? 0;
        default:
          return 0;
      }
    });
  }, [visibleWatchlistCoins, watchlistSort, sortData, coinAmounts, signals, calculatedSL, calculatedTP]);

  const moveCoin = useCallback((symbol: string, direction: -1 | 1) => {
    if (!symbol || !orderedWatchlistCoins.length) {
      return;
    }

    const orderedSymbols = orderedWatchlistCoins.map((coin) => coin.instrument_name);
    const currentIndex = orderedSymbols.indexOf(symbol);
    if (currentIndex === -1) {
      return;
    }
    const targetIndex = currentIndex + direction;
    if (targetIndex < 0 || targetIndex >= orderedSymbols.length) {
      return;
    }

    const reordered = [...orderedSymbols];
    const [moved] = reordered.splice(currentIndex, 1);
    reordered.splice(targetIndex, 0, moved);

    setWatchlistOrder(() => {
      const nextOrder: Record<string, number> = {};
      reordered.forEach((sym, idx) => {
        nextOrder[sym] = idx + 1;
      });
      return nextOrder;
    });
  }, [orderedWatchlistCoins]);

  // Helpers
  function suggestSLTP({
    price, atr, rules
  }: { price: number; atr?: number; rules: StrategyRules }) {
    let slPrice: number | undefined;
    if (rules.sl.atrMult && atr) slPrice = price - rules.sl.atrMult * atr;
    else if (rules.sl.pct)       slPrice = price * (1 - rules.sl.pct / 100);

    let tpPrice: number | undefined;
    if (rules.tp.rr && slPrice != null) tpPrice = price + rules.tp.rr * (price - slPrice);
    else if (rules.tp.pct)              tpPrice = price * (1 + rules.tp.pct / 100);

    return { slPrice, tpPrice };
  }

  // Helper function to format full strategy name (e.g., "intradia-agresiva")
  function formatFullStrategyName(preset: string, riskMode: RiskMode | string): string {
    const presetLower = preset.toLowerCase();
    const riskLower = riskMode.toLowerCase();
    
    // Map English to Spanish
    const presetMap: Record<string, string> = {
      'swing': 'swing',
      'intraday': 'intradia',
      'scalp': 'scalp'
    };
    
    const riskMap: Record<string, string> = {
      'conservative': 'conservadora',
      'aggressive': 'agresiva'
    };
    
    const presetSpanish = presetMap[presetLower] || presetLower;
    const riskSpanish = riskMap[riskLower] || riskLower;
    
    return `${presetSpanish}-${riskSpanish}`;
  }

  function buildTooltip(preset: Preset, risk: RiskMode, ctx: {
    rsi?: number; ema10?: number; ma50?: number; ma200?: number; atr?: number; currentPrice?: number;
  }, currentStrategy?: StrategyDecision) {
    // Use presetsConfig (editable) if available, fallback to PRESET_CONFIG (defaults)
    const cfg = presetsConfig[preset] || PRESET_CONFIG[preset];
    if (!cfg) {
      return `Preset "${preset}" not found`;
    }
    const rules = cfg.rules[risk];
    if (!rules) {
      return `Risk mode "${risk}" not found for preset "${preset}"`;
    }
    const fullStrategyName = formatFullStrategyName(preset, risk);
    const lines = [
      `📊 Estrategia: ${fullStrategyName}`,
      `RSI: buy<${rules.rsi.buyBelow ?? '-'} / sell>${rules.rsi.sellAbove ?? '-'}`,
    ];
    
    // Build MA conditions with real values if available
    const maConditions: string[] = [];
    if (rules.maChecks.ema10) {
      if (ctx.ema10 !== undefined) {
        maConditions.push(`EMA10=$${formatNumber(ctx.ema10)}`);
      } else {
        maConditions.push(`EMA10=✓`);
      }
    }
    if (rules.maChecks.ma50) {
      if (ctx.ma50 !== undefined && ctx.ema10 !== undefined) {
        const condition = ctx.ma50 > ctx.ema10 ? '✓' : '✗';
        maConditions.push(`MA50=$${formatNumber(ctx.ma50)} ${condition} MA50>EMA10`);
      } else if (ctx.ma50 !== undefined) {
        maConditions.push(`MA50=$${formatNumber(ctx.ma50)}`);
      } else {
        maConditions.push(`MA50=✓`);
      }
    }
    if (rules.maChecks.ma200) {
      if (ctx.ma200 !== undefined && ctx.currentPrice !== undefined) {
        const condition = ctx.currentPrice > ctx.ma200 ? '✓' : '✗';
        maConditions.push(`MA200=$${formatNumber(ctx.ma200)} ${condition} Price>MA200`);
      } else if (ctx.ma200 !== undefined) {
        maConditions.push(`MA200=$${formatNumber(ctx.ma200)}`);
      } else {
        maConditions.push(`MA200=✓`);
      }
    }
    
    if (maConditions.length > 0) {
      lines.push(`MAs: ${maConditions.join(' | ')}`);
    } else {
      lines.push(`MAs: no MA checks`);
    }
    
    lines.push(
      rules.sl.atrMult ? `SL≈ price - ${rules.sl.atrMult}×ATR` : `SL≈ -${rules.sl.pct ?? '-'}%`,
      rules.tp.rr ? `TP≈ price + ${rules.tp.rr}×(price-SL)` : `TP≈ +${rules.tp.pct ?? '-'}%`,
    );
    if (rules.notes?.length) lines.push(`Notas: ${rules.notes.join(' · ')}`);
    // Safely handle currentStrategy - validate it's a proper StrategyDecision before accessing
    const validStrategy = safeGetStrategyDecision(currentStrategy);
    if (validStrategy) {
      lines.push('');
      lines.push('⚙️ Estado actual (backend):');
      const reasonLabels: Record<string, string> = {
        buy_rsi_ok: 'RSI < umbral BUY',
        buy_ma_ok: 'Tendencia (MAs)',
        buy_volume_ok: 'Volumen BUY >= mínimo',
        buy_target_ok: 'Precio dentro de buy target',
        sell_rsi_ok: 'RSI > umbral SELL',
        sell_trend_ok: 'Reversa confirmada',
        sell_volume_ok: 'Volumen SELL >= mínimo',
      };
      // Safely access reasons with multiple layers of validation
      if (validStrategy.reasons && typeof validStrategy.reasons === 'object' && !Array.isArray(validStrategy.reasons)) {
        try {
          Object.entries(validStrategy.reasons).forEach(([key, val]) => {
            if (val === null || val === undefined) return;
            const label = reasonLabels[key] || key;
            lines.push(`  • ${label}: ${val ? '✓' : '✗'}`);
          });
        } catch (e) {
          // Silently ignore if reasons is malformed - don't break the tooltip
          logger.debug('Error processing strategy reasons:', e);
        }
      }
      if (validStrategy.summary && typeof validStrategy.summary === 'string') {
        lines.push('');
        lines.push(`Resumen backend: ${validStrategy.summary}`);
      }
    }
    return lines.join('\n');
  }
  
  // Helper function to safely validate and extract StrategyDecision
  function safeGetStrategyDecision(
    strategyState: unknown,
    fallback?: StrategyDecision
  ): StrategyDecision | undefined {
    // Check if it's a valid object (not null, not array, has decision property)
    if (
      strategyState &&
      typeof strategyState === 'object' &&
      strategyState !== null &&
      !Array.isArray(strategyState) &&
      'decision' in strategyState &&
      typeof (strategyState as { decision?: unknown }).decision === 'string'
    ) {
      const decision = (strategyState as { decision: string }).decision;
      // Validate decision is one of the allowed values
      if (decision === 'BUY' || decision === 'SELL' || decision === 'WAIT') {
        return strategyState as StrategyDecision;
      }
    }
    return fallback;
  }

type StrategyDecisionValue = 'BUY' | 'SELL' | 'WAIT';

function getReasonPrefix(decision: StrategyDecisionValue): 'buy_' | 'sell_' {
  return decision === 'SELL' ? 'sell_' : 'buy_';
}

function hasBlockingStrategyReason(
  decision: StrategyDecisionValue,
  reasons: Record<string, unknown>
): boolean {
  const prefix = getReasonPrefix(decision);
  return Object.entries(reasons).some(([key, value]) => key.startsWith(prefix) && value === false);
}

function computeStrategyIndex(
  decision: StrategyDecisionValue,
  reasons: Record<string, unknown>
): number | null {
  // CANONICAL: Calculate index from backend buy_* reasons
  // Only count boolean flags (ignore None values which mean "not applicable/not blocking")
  // This matches the backend canonical rule logic
  const prefix = getReasonPrefix(decision);
  const relevant = Object.entries(reasons).filter(
    ([key, value]) => key.startsWith(prefix) && typeof value === 'boolean'
  );
  if (!relevant.length) {
    return null;
  }
  // Count how many are True (only False values block the decision)
  // When all are True, index = 100% (matches backend canonical rule)
  const satisfied = relevant.filter(([, value]) => value === true).length;
  return Math.round((satisfied / relevant.length) * 100);
}

function buildDecisionIndexTitle(
  decision: StrategyDecisionValue,
  reasons: Record<string, unknown>,
  indexValue: number
): string {
  const prefix = getReasonPrefix(decision);
  const summary = Object.entries(reasons)
    .filter(([key, value]) => key.startsWith(prefix) && typeof value === 'boolean')
    .map(([key, value]) => `${key.replace(prefix, '')}: ${value ? '✓' : '✗'}`)
    .join(' | ');
  const decisionLabel = decision === 'SELL' ? 'SELL readiness' : 'BUY readiness';
  return summary
    ? `${decisionLabel} index: ${indexValue}% (${summary})`
    : `${decisionLabel} index: ${indexValue}%`;
}

function resolveDecisionIndexColor(value: number): string {
  if (value >= 90) return 'text-green-600';
  if (value >= 70) return 'text-green-500';
  if (value >= 50) return 'text-gray-600';
  if (value >= 30) return 'text-orange-500';
  return 'text-red-500';
}

  // Helper function to build signal criteria explanation tooltip
  // CANONICAL: Uses backend strategyReasons as source of truth for green/red status
  function buildSignalCriteriaTooltip(
    preset: Preset,
    riskMode: RiskMode,
    rules: StrategyRules | undefined,
    rsi: number | undefined,
    ma50: number | undefined,
    ema10: number | undefined,
    ma200: number | undefined,
    currentPrice: number | undefined,
    volume: number | undefined,
    avgVolume: number | undefined,
    symbol?: string,
    currentStrategy?: StrategyDecision,
    strategyVolumeRatio?: number | null,  // Optional: canonical volume ratio from strategy (same as Volume column)
    volumeAvgPeriods?: number | null,  // Optional: number of periods used for avg_volume calculation
    backendMinVolumeRatio?: number,  // CANONICAL: Backend configured threshold from Signal Config (source of truth)
    ma10w?: number | undefined  // Optional: MA10w value for trend reversal check
  ): string {
    if (!rules) {
      return `Estrategia no configurada`;
    }

    // CANONICAL: Extract backend reasons - this is the source of truth for green/red status
    const reasons = currentStrategy?.reasons;
    const strategyReasons = reasons && typeof reasons === 'object' && !Array.isArray(reasons)
      ? reasons as Record<string, boolean | null | undefined>
      : {};

    // CANONICAL: Use backend min_volume_ratio if provided (Signal Config source of truth), otherwise fallback to rules
    // NOTE: Must use ?? (nullish coalescing) not || (falsy check) because 0 is a valid value
    // FIX: Add optional chaining to prevent TypeError if rules is undefined or doesn't have volumeMinRatio
    const minVolumeRatio = backendMinVolumeRatio !== undefined && backendMinVolumeRatio !== null
      ? backendMinVolumeRatio
      : (rules?.volumeMinRatio ?? 0.5);

    const lines: string[] = [];
    const fullStrategyName = formatFullStrategyName(preset, riskMode);
    lines.push(`📊 Estrategia: ${fullStrategyName}`);
    lines.push('');
    
    // BUY Criteria - CANONICAL: Use backend reasons for status, show values for context
    lines.push('🟢 CRITERIOS BUY (todos deben cumplirse):');
    const buyBelow = rules.rsi?.buyBelow ?? 40;
    // CANONICAL: Use backend buy_rsi_ok for status, not local calculation
    const buyRsiOk = strategyReasons.buy_rsi_ok;
    const rsiBuyStatus = buyRsiOk === true ? '✓' : buyRsiOk === false ? '✗' : '?';
    lines.push(`  • RSI < ${buyBelow} ${(rsi !== undefined && rsi !== null) ? `(actual: ${rsi.toFixed(2)}${rsiBuyStatus})` : rsiBuyStatus}`);
    
    // CANONICAL: Use backend buy_ma_ok for status
    const buyMaOk = strategyReasons.buy_ma_ok;
    if (rules.maChecks?.ma50 && ma50 !== undefined && ma50 !== null && ema10 !== undefined && ema10 !== null) {
      const ma50Status = buyMaOk === true ? '✓' : buyMaOk === false ? '✗' : '?';
      lines.push(`  • MA50 > EMA10 ${ma50Status}`);
      lines.push(`    - MA50: $${formatNumber(ma50, symbol)}`);
      lines.push(`    - EMA10: $${formatNumber(ema10, symbol)}`);
    }
    
    if (rules.maChecks?.ma200 && ma200 !== undefined && ma200 !== null && currentPrice !== undefined && currentPrice !== null) {
      // MA200 check is part of buy_ma_ok in backend
      const ma200Status = buyMaOk === true ? '✓' : buyMaOk === false ? '✗' : '?';
      lines.push(`  • Precio > MA200 ${ma200Status}`);
      lines.push(`    - Precio: $${formatNumber(currentPrice, symbol)}`);
      lines.push(`    - MA200: $${formatNumber(ma200, symbol)}`);
    }
    
    // Volume criterion: require volume >= minVolumeRatio x average (market reaction)
    // CANONICAL: Use backend buy_volume_ok for status, show ratio for context
    const buyVolumeOk = strategyReasons.buy_volume_ok;
    let volumeRatio: number | undefined;
    if (strategyVolumeRatio !== undefined && strategyVolumeRatio !== null && strategyVolumeRatio >= 0) {
      // Use canonical strategy volume_ratio (same calculation as Volume column and strategy decision)
      volumeRatio = strategyVolumeRatio;
    } else if (volume !== undefined && volume !== null && avgVolume !== undefined && avgVolume !== null && avgVolume > 0) {
      // Fallback: calculate from volume/avgVolume (should match strategy if same inputs)
      volumeRatio = volume / avgVolume;
    }
    
    if (volumeRatio !== undefined && volumeRatio !== null) {
      // CANONICAL: Use backend buy_volume_ok for status
      const volumeStatus = buyVolumeOk === true ? '✓' : buyVolumeOk === false ? '✗' : '?';
      lines.push(`  • Volume ≥ ${minVolumeRatio}x promedio ${volumeStatus}`);
      lines.push(`    - Ratio actual: ${volumeRatio.toFixed(2)}x (mismo valor que columna Volume)`);
      lines.push(`    - Volume (último período): ${formatNumber(volume, undefined)}`);
      // Show period count if available, otherwise fallback to generic text
      if (volumeAvgPeriods !== undefined && volumeAvgPeriods !== null && volumeAvgPeriods > 0) {
        lines.push(`    - Promedio (${volumeAvgPeriods} períodos): ${formatNumber(avgVolume, undefined)}`);
      } else {
        lines.push(`    - Promedio: ${formatNumber(avgVolume, undefined)}`);
      }
    } else {
      // CANONICAL: Use backend buy_volume_ok for status even when ratio unavailable
      const volumeStatus = buyVolumeOk === true ? '✓' : buyVolumeOk === false ? '✗' : '?';
      lines.push(`  • Volume ≥ ${minVolumeRatio}x promedio ${volumeStatus} (datos no disponibles)`);
    }
    
    // CANONICAL: Show buy_target_ok and buy_price_ok from backend
    const buyTargetOk = strategyReasons.buy_target_ok;
    if (buyTargetOk !== undefined && buyTargetOk !== null) {
      const targetStatus = buyTargetOk === true ? '✓' : '✗';
      lines.push(`  • Precio dentro de buy target ${targetStatus}`);
    }
    
    const buyPriceOk = strategyReasons.buy_price_ok;
    if (buyPriceOk !== undefined && buyPriceOk !== null && buyPriceOk === false) {
      lines.push(`  • Precio válido ✗`);
    }
    
    // Check if ANY MA is required (ema10, ma50, or ma200)
    // IMPORTANT: Only check if explicitly marked as required in config (maChecks.ema10=true)
    const requiresAnyMA = rules.maChecks?.ema10 || rules.maChecks?.ma50 || rules.maChecks?.ma200;
    
    // If EMA10 is required (maChecks.ema10=true) but not shown above (when ma50 is false), show it here
    // Only show EMA10 check if it's explicitly marked as required in the config
    if (rules.maChecks?.ema10 === true && !rules.maChecks?.ma50 && ema10 !== undefined && ema10 !== null && currentPrice !== undefined && currentPrice !== null) {
      // EMA10 check: Price > EMA10 (with tolerance for scalp strategies)
      const ma10Status = buyMaOk === true ? '✓' : buyMaOk === false ? '✗' : '?';
      lines.push(`  • Precio > EMA10 ${ma10Status}`);
      lines.push(`    - Precio: $${formatNumber(currentPrice, symbol)}`);
      lines.push(`    - EMA10: $${formatNumber(ema10, symbol)}`);
    }
    
    // Only show "No se requieren MAs" if NO MAs are required at all
    // This means all maChecks are false or undefined
    if (!requiresAnyMA) {
      lines.push(`  • No se requieren MAs`);
    }
    
    lines.push('');
    
    // SELL Criteria - More strict: require BOTH RSI AND trend reversal (MA reversal OR price below MA10w)
    // CANONICAL: Use backend sell_trend_ok for overall trend status
    const sellTrendOk = strategyReasons.sell_trend_ok;
    const requiresMaReversal = rules.maChecks?.ma50 === true;
    
    if (requiresMaReversal) {
      lines.push('🔴 CRITERIOS SELL (TODOS deben cumplirse):');
    } else {
      lines.push('🔴 CRITERIOS SELL:');
    }
    const sellAbove = rules.rsi?.sellAbove ?? 70;
    // CANONICAL: Use backend sell_rsi_ok for status, not local calculation
    const sellRsiOk = strategyReasons.sell_rsi_ok;
    const rsiSellStatus = sellRsiOk === true ? '✓' : sellRsiOk === false ? '✗' : '?';
    lines.push(`  • RSI > ${sellAbove} ${(rsi !== undefined && rsi !== null) ? `(actual: ${rsi.toFixed(2)}${rsiSellStatus})` : rsiSellStatus}`);
    
    // Trend reversal check: MA50 < EMA10 OR price < MA10w
    // CANONICAL: Use backend sell_trend_ok for overall status, but show individual conditions for clarity
    const trendStatus = sellTrendOk === true ? '✓' : sellTrendOk === false ? '✗' : '?';
    
    if (requiresMaReversal) {
      // Calculate individual conditions first to determine which one satisfied the OR condition
      let ma50Reversal = false;
      let priceBelowMa10w = false;
      
      if (ma50 !== undefined && ema10 !== undefined) {
        const priceDiff = Math.abs(ma50 - ema10);
        const avgPrice = (ma50 + ema10) / 2;
        const percentDiff = (priceDiff / avgPrice) * 100;
        ma50Reversal = ma50 < ema10 && percentDiff >= 0.5;
      }
      
      if (ma10w != null && currentPrice != null) {
        const ma10wNum = typeof ma10w === 'number' ? ma10w : parseFloat(String(ma10w));
        const currentPriceNum = typeof currentPrice === 'number' ? currentPrice : parseFloat(String(currentPrice));
        if (!isNaN(ma10wNum) && !isNaN(currentPriceNum)) {
          priceBelowMa10w = currentPriceNum < ma10wNum;
        }
      }
      
      // Determine which condition(s) satisfied the OR requirement
      const conditionSatisfied = ma50Reversal || priceBelowMa10w;
      const satisfiedBy = [];
      if (ma50Reversal) satisfiedBy.push('MA50<EMA10');
      if (priceBelowMa10w) satisfiedBy.push('Precio<MA10w');
      
      // Show overall trend status from backend first, with clear OR explanation
      const orExplanation = conditionSatisfied && sellTrendOk 
        ? ` (cumplido por: ${satisfiedBy.join(' o ')})` 
        : ' (requiere: MA50<EMA10 O Precio<MA10w)';
      lines.push(`  • Reversa de tendencia confirmada ${trendStatus}${orExplanation}`);
      lines.push(`    ⚠️ Nota: Es una condición OR - solo UNA de las dos debe cumplirse`);
      
      // Show MA50 < EMA10 check details
      if (ma50 !== undefined && ema10 !== undefined) {
        const priceDiff = Math.abs(ma50 - ema10);
        const avgPrice = (ma50 + ema10) / 2;
        const percentDiff = (priceDiff / avgPrice) * 100;
        const ma50ReversalStatus = ma50Reversal ? '✓' : '✗';
        
        lines.push(`    - MA50 < EMA10 (diferencia ≥0.5%) ${ma50ReversalStatus}${ma50Reversal ? ' ← CUMPLE' : ''}`);
        lines.push(`      MA50: $${formatNumber(ma50, symbol)} | EMA10: $${formatNumber(ema10, symbol)}`);
        if (ma50 < ema10) {
          lines.push(`      Diferencia: ${percentDiff.toFixed(2)}% ${percentDiff >= 0.5 ? '(cumple ≥0.5%)' : '(requiere ≥0.5%)'}`);
        }
      }
      
      // Show price < MA10w check (alternative trend reversal signal)
      // Always show if ma10w and currentPrice are available
      if (ma10w != null && currentPrice != null) {
        const ma10wNum = typeof ma10w === 'number' ? ma10w : parseFloat(String(ma10w));
        const currentPriceNum = typeof currentPrice === 'number' ? currentPrice : parseFloat(String(currentPrice));
        
        // Debug logging for TON_USDT
        if (symbol === 'TON_USDT') {
          console.log('[TON_USDT DEBUG] ma10w check:', {
            ma10w,
            ma10wType: typeof ma10w,
            ma10wNum,
            isNaN_ma10w: isNaN(ma10wNum),
            currentPrice,
            currentPriceType: typeof currentPrice,
            currentPriceNum,
            isNaN_currentPrice: isNaN(currentPriceNum),
            requiresMaReversal,
            sellTrendOk
          });
        }
        
        // Show if both are valid numbers
        if (!isNaN(ma10wNum) && !isNaN(currentPriceNum)) {
          const priceBelowStatus = priceBelowMa10w ? '✓' : '✗';
          lines.push(`    - Precio < MA10w ${priceBelowStatus}${priceBelowMa10w ? ' ← CUMPLE' : ''}`);
          lines.push(`      Precio: $${formatNumber(currentPriceNum, symbol)} | MA10w: $${formatNumber(ma10wNum, symbol)}`);
        } else if (symbol === 'TON_USDT') {
          console.log('[TON_USDT DEBUG] Failed validation:', {
            ma10wNum,
            currentPriceNum,
            isNaN_ma10w: isNaN(ma10wNum),
            isNaN_currentPrice: isNaN(currentPriceNum)
          });
        }
      } else if (symbol === 'TON_USDT') {
        console.log('[TON_USDT DEBUG] ma10w or currentPrice is null:', {
          ma10w,
          currentPrice,
          ma10wNull: ma10w == null,
          currentPriceNull: currentPrice == null
        });
      }
    } else {
      // Strategy doesn't require MA checks, but show trend status and details if available
      if (sellTrendOk !== undefined && sellTrendOk !== null) {
        lines.push(`  • Reversa de tendencia confirmada ${trendStatus} (no requerida por estrategia, pero evaluada: MA50<EMA10 O Precio<MA10w)`);
        
        // Show MA50 < EMA10 check details even if not required
        if (ma50 !== undefined && ema10 !== undefined) {
          const priceDiff = Math.abs(ma50 - ema10);
          const avgPrice = (ma50 + ema10) / 2;
          const percentDiff = (priceDiff / avgPrice) * 100;
          const ma50Reversal = ma50 < ema10 && percentDiff >= 0.5;
          const ma50ReversalStatus = ma50Reversal ? '✓' : '✗';
          
          lines.push(`    - MA50 < EMA10 (diferencia ≥0.5%) ${ma50ReversalStatus}`);
          lines.push(`      MA50: $${formatNumber(ma50, symbol)} | EMA10: $${formatNumber(ema10, symbol)}`);
          if (ma50 < ema10) {
            lines.push(`      Diferencia: ${percentDiff.toFixed(2)}% ${percentDiff >= 0.5 ? '(cumple ≥0.5%)' : '(requiere ≥0.5%)'}`);
          }
        }
        
        // Show price < MA10w check even if not required
        // Always show if ma10w and currentPrice are available
        if (ma10w != null && currentPrice != null) {
          const ma10wNum = typeof ma10w === 'number' ? ma10w : parseFloat(String(ma10w));
          const currentPriceNum = typeof currentPrice === 'number' ? currentPrice : parseFloat(String(currentPrice));
          
          // Debug logging for TON_USDT
          if (symbol === 'TON_USDT') {
            console.log('[TON_USDT DEBUG] ma10w check (else branch):', {
              ma10w,
              ma10wType: typeof ma10w,
              ma10wNum,
              isNaN_ma10w: isNaN(ma10wNum),
              currentPrice,
              currentPriceType: typeof currentPrice,
              currentPriceNum,
              isNaN_currentPrice: isNaN(currentPriceNum),
              requiresMaReversal,
              sellTrendOk
            });
          }
          
          // Use same validation as requiresMaReversal=true branch
          // This ensures consistent behavior regardless of requiresMaReversal value
          if (!isNaN(ma10wNum) && !isNaN(currentPriceNum)) {
            const priceBelowMa10w = currentPriceNum < ma10wNum;
            const priceBelowStatus = priceBelowMa10w ? '✓' : '✗';
            lines.push(`    - Precio < MA10w ${priceBelowStatus}`);
            lines.push(`      Precio: $${formatNumber(currentPriceNum, symbol)} | MA10w: $${formatNumber(ma10wNum, symbol)}`);
          } else if (symbol === 'TON_USDT') {
            console.log('[TON_USDT DEBUG] Failed validation (else branch):', {
              ma10wNum,
              currentPriceNum,
              isNaN_ma10w: isNaN(ma10wNum),
              isNaN_currentPrice: isNaN(currentPriceNum)
            });
          }
        } else if (symbol === 'TON_USDT') {
          console.log('[TON_USDT DEBUG] ma10w or currentPrice is null (else branch):', {
            ma10w,
            currentPrice,
            ma10wNull: ma10w == null,
            currentPriceNull: currentPrice == null
          });
        }
      }
    }
    
    // Volume criterion: require volume >= minVolumeRatio x average for SELL (market reaction)
    // CANONICAL: Use backend sell_volume_ok for status, show ratio for context
    const sellVolumeOk = strategyReasons.sell_volume_ok;
    // CANONICAL: Use strategy volume_ratio if provided (same as Volume column), otherwise calculate
    volumeRatio = undefined;
    if (strategyVolumeRatio !== undefined && strategyVolumeRatio !== null && strategyVolumeRatio >= 0) {
      // Use canonical strategy volume_ratio (same calculation as Volume column and strategy decision)
      volumeRatio = strategyVolumeRatio;
    } else if (volume !== undefined && volume !== null && avgVolume !== undefined && avgVolume !== null && avgVolume > 0) {
      // Fallback: calculate from volume/avgVolume (should match strategy if same inputs)
      volumeRatio = volume / avgVolume;
    }
    
    if (volumeRatio !== undefined && volumeRatio !== null) {
      // CANONICAL: Use backend sell_volume_ok for status
      const volumeStatus = sellVolumeOk === true ? '✓' : sellVolumeOk === false ? '✗' : '?';
      lines.push(`  • Volume ≥ ${minVolumeRatio}x promedio ${volumeStatus}`);
      lines.push(`    - Ratio actual: ${volumeRatio.toFixed(2)}x (mismo valor que columna Volume)`);
      lines.push(`    - Volume (último período): ${formatNumber(volume, undefined)}`);
      // Show period count if available, otherwise fallback to generic text
      if (volumeAvgPeriods !== undefined && volumeAvgPeriods !== null && volumeAvgPeriods > 0) {
        lines.push(`    - Promedio (${volumeAvgPeriods} períodos): ${formatNumber(avgVolume, undefined)}`);
      } else {
        lines.push(`    - Promedio: ${formatNumber(avgVolume, undefined)}`);
      }
    } else {
      // CANONICAL: Use backend sell_volume_ok for status even when ratio unavailable
      const volumeStatus = sellVolumeOk === true ? '✓' : sellVolumeOk === false ? '✗' : '?';
      lines.push(`  • Volume ≥ ${minVolumeRatio}x promedio ${volumeStatus} (datos no disponibles)`);
    }
    
    lines.push('');
    
    // Current Status - CANONICAL: Use backend decision and reasons as source of truth
    const backendDecision = currentStrategy?.decision;
    lines.push('📌 ESTADO ACTUAL (backend):');
    
    // CANONICAL: Use backend decision, not local calculation
    if (backendDecision === 'BUY') {
      lines.push('  → Señal: BUY (todos los criterios BUY cumplidos según backend)');
      // Show which criteria are met
      const metCriteria: string[] = [];
      if (buyRsiOk === true) metCriteria.push('RSI');
      if (buyMaOk === true) metCriteria.push('MA');
      if (buyVolumeOk === true) metCriteria.push('Volume');
      if (buyTargetOk === true) metCriteria.push('Target');
      if (buyPriceOk === true) metCriteria.push('Price');
      if (metCriteria.length > 0) {
        lines.push(`  ✓ Criterios cumplidos: ${metCriteria.join(', ')}`);
      }
    } else if (backendDecision === 'SELL') {
      lines.push('  → Señal: SELL (todos los criterios SELL cumplidos según backend)');
      const sellRsiOk = strategyReasons.sell_rsi_ok;
      const sellTrendOk = strategyReasons.sell_trend_ok;
      const sellVolumeOk = strategyReasons.sell_volume_ok;
      const sellCriteria: string[] = [];
      if (sellRsiOk === true) sellCriteria.push('RSI');
      if (sellTrendOk === true) sellCriteria.push('Trend');
      if (sellVolumeOk === true) sellCriteria.push('Volume');
      if (sellCriteria.length > 0) {
        lines.push(`  ✓ Criterios cumplidos: ${sellCriteria.join(', ')}`);
      }
    } else {
      lines.push('  → Señal: WAIT (no se cumplen todos los criterios BUY según backend)');
      // Show which criteria are blocking - be specific about which MA
      const blockingCriteria: string[] = [];
      if (buyRsiOk === false) blockingCriteria.push('RSI');
      if (buyMaOk === false) {
        // Be specific about which MA is blocking - ONLY show if explicitly enabled in config
        // CRITICAL: Only show EMA10 if it's explicitly enabled (ema10 === true)
        // If ema10 is false or undefined, don't show it as blocking
        const ema10Enabled = rules.maChecks?.ema10 === true;
        const ma50Enabled = rules.maChecks?.ma50 === true;
        const ma200Enabled = rules.maChecks?.ma200 === true;
        
        if (ema10Enabled && !ma50Enabled && !ma200Enabled) {
          blockingCriteria.push('EMA10');
        } else if (ma50Enabled) {
          blockingCriteria.push('MA50');
        } else if (ma200Enabled) {
          blockingCriteria.push('MA200');
        } else if (ema10Enabled || ma50Enabled || ma200Enabled) {
          // At least one MA is enabled, but we can't determine which one is blocking
          blockingCriteria.push('MA');
        }
        // If no MAs are enabled (all false or undefined), don't add 'MA' to blocking criteria
      }
      if (buyVolumeOk === false) blockingCriteria.push('Volume');
      if (buyTargetOk === false) blockingCriteria.push('Target');
      if (buyPriceOk === false) blockingCriteria.push('Price');
      if (blockingCriteria.length > 0) {
        lines.push(`  ✗ Criterios bloqueantes: ${blockingCriteria.join(', ')}`);
      } else {
        lines.push('  ℹ️ Algunos criterios no están disponibles (None)');
      }
      
      // Show volume ratio if available for context
      if (volumeRatio !== undefined && volumeRatio !== null && volumeRatio < minVolumeRatio) {
        lines.push(`  ⚠️ Volume ratio (${volumeRatio.toFixed(2)}x) < ${minVolumeRatio}x`);
      }
    }
    
    return lines.join('\n');
  }

  // Helper function to get MA color and explanation based on strategy
  function getMAColorAndTooltip(
    coin: TopCoin,
    maType: 'EMA10' | 'MA50' | 'MA200' | 'MA10w',
    signals: TradingSignals | null | undefined,
    coinPresets: Record<string, string>
  ): { colorClass: string; tooltip: string } {
    if (!signals) {
      return { colorClass: 'text-gray-400', tooltip: 'Signal data not available' };
    }

    const preset = coinPresets[normalizeSymbolKey(coin.instrument_name)] || 'swing';
    let presetType: Preset;
    let riskMode: RiskMode;
    
    if (preset === 'swing' || preset === 'intraday' || preset === 'scalp') {
      presetType = (preset.charAt(0).toUpperCase() + preset.slice(1)) as Preset;
      riskMode = 'Conservative';
    } else if (preset.includes('-conservative')) {
      const basePreset = preset.replace('-conservative', '');
      presetType = (basePreset.charAt(0).toUpperCase() + basePreset.slice(1)) as Preset;
      riskMode = 'Conservative';
    } else if (preset.includes('-aggressive')) {
      const basePreset = preset.replace('-aggressive', '');
      presetType = (basePreset.charAt(0).toUpperCase() + basePreset.slice(1)) as Preset;
      riskMode = 'Aggressive';
    } else {
      presetType = 'Swing';
      riskMode = 'Conservative';
    }

    // Use presetsConfig (editable) if available, fallback to PRESET_CONFIG (defaults)
    const rules = presetsConfig[presetType]?.rules[riskMode] || PRESET_CONFIG[presetType]?.rules[riskMode];
    const currentPrice = coin.current_price;
    const ma50 = signals.ma50;
    const ema10 = signals.ema10;
    const ma200 = signals.ma200;
    const ma10w = signals.ma10w;

    // Determine color and tooltip based on MA type and strategy rules
    switch (maType) {
      case 'EMA10':
        if (ema10 === undefined) {
          return { colorClass: 'text-gray-400', tooltip: 'EMA10 data not available' };
        }
        if (!currentPrice || currentPrice === 0) {
          return { colorClass: 'text-gray-400', tooltip: `EMA10: $${formatNumber(ema10, coin.instrument_name)} (precio no disponible)` };
        }
        if (currentPrice >= ema10) {
          return {
            colorClass: 'palette-text-profit-strong text-green-600',
            tooltip: `🟢 COMPRAR: Precio ($${formatNumber(currentPrice, coin.instrument_name)}) ${currentPrice > ema10 ? '>' : '='} EMA10 ($${formatNumber(ema10, coin.instrument_name)}). Tendencia alcista a corto plazo.`
          };
        } else {
          return {
            colorClass: 'palette-text-loss-strong text-red-600',
            tooltip: `🔴 VENDER: Precio ($${formatNumber(currentPrice, coin.instrument_name)}) < EMA10 ($${formatNumber(ema10, coin.instrument_name)}). Tendencia bajista a corto plazo.`
          };
        }

      case 'MA50':
        if (ma50 === undefined) {
          return { colorClass: 'text-gray-400', tooltip: 'MA50 data not available' };
        }
        // Check if MA50 is used in strategy
        const ma50Check = rules?.maChecks?.ma50;
        if (ma50Check && ema10 !== undefined) {
          // MA50 is active in strategy: MA50 > EMA10 is required for BUY, MA50 < EMA10 suggests SELL
          if (ma50 > ema10) {
            return {
              colorClass: 'palette-text-profit-strong text-green-600',
              tooltip: `✅ Criterio COMPRA cumplido: MA50 ($${formatNumber(ma50, coin.instrument_name)}) > EMA10 ($${formatNumber(ema10, coin.instrument_name)}). Condición necesaria para señal BUY.`
            };
          } else {
            return {
              colorClass: 'palette-text-loss-strong text-red-600',
              tooltip: `❌ Criterio COMPRA NO cumplido: MA50 ($${formatNumber(ma50, coin.instrument_name)}) < EMA10 ($${formatNumber(ema10, coin.instrument_name)}). Esta condición bloquea señal BUY, sugiere SELL.`
            };
          }
        } else {
          // MA50 not used in strategy, just show price comparison for reference
          if (!currentPrice || currentPrice === 0) {
            return { colorClass: 'text-gray-400', tooltip: `MA50: $${formatNumber(ma50, coin.instrument_name)} (precio no disponible)` };
          }
          if (currentPrice >= ma50) {
            return {
              colorClass: 'text-gray-600',
              tooltip: `Precio ($${formatNumber(currentPrice, coin.instrument_name)}) ${currentPrice > ma50 ? '>' : '='} MA50 ($${formatNumber(ma50, coin.instrument_name)}). Tendencia alcista a medio plazo. (No usado en estrategia actual)`
            };
          } else {
            return {
              colorClass: 'text-gray-600',
              tooltip: `Precio ($${formatNumber(currentPrice, coin.instrument_name)}) < MA50 ($${formatNumber(ma50, coin.instrument_name)}). Tendencia bajista a medio plazo. (No usado en estrategia actual)`
            };
          }
        }

      case 'MA200':
        if (ma200 === undefined) {
          return { colorClass: 'text-gray-400', tooltip: 'MA200 data not available' };
        }
        // Check if MA200 is used in strategy
        const ma200Check = rules?.maChecks?.ma200;
        if (!currentPrice || currentPrice === 0) {
          return { colorClass: 'text-gray-400', tooltip: `MA200: $${formatNumber(ma200, coin.instrument_name)} (precio no disponible)` };
        }
        if (ma200Check) {
          // MA200 is active in strategy: Precio > MA200 is required for BUY
          // Important: If MA200 is green (Precio > MA200), this is NOT a sell criterion
          // Green = BUY criterion met, Red = BUY criterion NOT met (blocks BUY, suggests WAIT/SELL)
          if (currentPrice >= ma200) {
            return {
              colorClass: 'palette-text-profit-strong text-green-600',
              tooltip: `✅ Criterio COMPRA cumplido: Precio ($${formatNumber(currentPrice, coin.instrument_name)}) ${currentPrice > ma200 ? '>' : '='} MA200 ($${formatNumber(ma200, coin.instrument_name)}). Condición necesaria para señal BUY. Este criterio NO es para vender - si está verde, NO es razón para SELL.`
            };
          } else {
            return {
              colorClass: 'palette-text-loss-strong text-red-600',
              tooltip: `❌ Criterio COMPRA bloqueado: Precio ($${formatNumber(currentPrice, coin.instrument_name)}) < MA200 ($${formatNumber(ma200, coin.instrument_name)}). Esta condición bloquea señal BUY. Si la señal es SELL, viene de otros criterios (RSI > sellAbove o MA50 < EMA10), NO de MA200.`
            };
          }
        } else {
          // MA200 not used in strategy, just show price comparison for reference
          if (currentPrice >= ma200) {
            return {
              colorClass: 'text-gray-600',
              tooltip: `Precio ($${formatNumber(currentPrice, coin.instrument_name)}) ${currentPrice > ma200 ? '>' : '='} MA200 ($${formatNumber(ma200, coin.instrument_name)}). Tendencia alcista a largo plazo. (No usado en estrategia actual)`
            };
          } else {
            return {
              colorClass: 'text-gray-600',
              tooltip: `Precio ($${formatNumber(currentPrice, coin.instrument_name)}) < MA200 ($${formatNumber(ma200, coin.instrument_name)}). Tendencia bajista a largo plazo. (No usado en estrategia actual)`
            };
          }
        }

      case 'MA10w':
        if (ma10w === undefined) {
          return { colorClass: 'text-gray-400', tooltip: 'MA10w data not available' };
        }
        // MA10w is NOT used in any strategy preset (only EMA10, MA50, MA200 are checked)
        // So we should show it as neutral/informational, not as buy/sell signal
        if (!currentPrice || currentPrice === 0) {
          return { colorClass: 'text-gray-400', tooltip: `MA10w: $${formatNumber(ma10w, coin.instrument_name)} (precio no disponible)` };
        }
        // Show as neutral gray - MA10w is not a strategy criterion
        return {
          colorClass: 'text-gray-600',
          tooltip: `MA10w: $${formatNumber(ma10w, coin.instrument_name)} | Precio: $${formatNumber(currentPrice, coin.instrument_name)}. Este indicador NO se usa en la estrategia actual (solo se usan EMA10, MA50, MA200 según preset). Mostrado solo como referencia informativa.`
        };

      default:
        return { colorClass: 'text-gray-400', tooltip: 'Unknown MA type' };
    }
  }

  // Helper function to update both state and ref - now supports filtering for specific coins
  const mergeCoinData = useCallback((existing: TopCoin | undefined, incoming: TopCoin): TopCoin => {
    if (!existing) {
      return incoming;
    }

    function chooseValue<T>(nextValue: T | undefined, fallbackValue: T, allowZero?: boolean): T;
    function chooseValue<T>(nextValue: T | undefined, fallbackValue: T | undefined, allowZero?: boolean): T | undefined;
    function chooseValue<T>(nextValue: T | undefined, fallbackValue: T | undefined, allowZero = false): T | undefined {
      if (nextValue === undefined || nextValue === null) {
        return fallbackValue;
      }
      if (!allowZero && typeof nextValue === 'number' && nextValue === 0 && typeof fallbackValue === 'number' && fallbackValue !== 0) {
        return fallbackValue;
      }
      return nextValue;
    }

    return {
      ...existing,
      ...incoming,
      current_price: chooseValue<number>(incoming.current_price, existing.current_price),
      volume_24h: chooseValue<number>(incoming.volume_24h, existing.volume_24h, true),
      updated_at: chooseValue<string>(incoming.updated_at, existing.updated_at),
      rsi: chooseValue(incoming.rsi, existing.rsi),
      ma50: chooseValue(incoming.ma50, existing.ma50),
      ma200: chooseValue(incoming.ma200, existing.ma200),
      ema10: chooseValue(incoming.ema10, existing.ema10),
      atr: chooseValue(incoming.atr, existing.atr),
      avg_volume: chooseValue(incoming.avg_volume, existing.avg_volume, true),
      volume_ratio: chooseValue(incoming.volume_ratio, existing.volume_ratio, true),
      res_up: chooseValue(incoming.res_up, existing.res_up),
      res_down: chooseValue(incoming.res_down, existing.res_down),
      strategy: incoming.strategy ?? existing.strategy,
      // Strategy fields from backend
      strategy_key: incoming.strategy_key ?? existing.strategy_key,
      strategy_preset: incoming.strategy_preset ?? existing.strategy_preset,
      strategy_risk: incoming.strategy_risk ?? existing.strategy_risk,
      // SL/TP fields from backend
      sl_price: chooseValue(incoming.sl_price, existing.sl_price),
      tp_price: chooseValue(incoming.tp_price, existing.tp_price),
    };
  }, []);

  useEffect(() => {
    lastUpdateTimesRef.current = lastUpdateTimes;
  }, [lastUpdateTimes]);

  // Helper function to update a single coin in the topCoins array
  const updateSingleCoin = useCallback((symbol: string, updates: Partial<TopCoin>) => {
    const symbolUpper = symbol.toUpperCase();
    const currentCoins = topCoinsRef.current;
    const coinIndex = currentCoins.findIndex(c => c.instrument_name?.toUpperCase() === symbolUpper);
    
    if (coinIndex === -1) {
      logger.warn(`Coin ${symbol} not found in topCoins, cannot update`);
      return;
    }
    
    const existingCoin = currentCoins[coinIndex];
    const updatedCoin = mergeCoinData(existingCoin, { ...existingCoin, ...updates } as TopCoin);
    const updatedCoins = [...currentCoins];
    updatedCoins[coinIndex] = updatedCoin;
    
    topCoinsRef.current = updatedCoins;
    setTopCoins(updatedCoins);
    logger.info(`✅ Updated coin ${symbol} in topCoins array`);
  }, [mergeCoinData]);

  const updateTopCoins = useCallback((newCoins: TopCoin[], filterSymbols?: string[]) => {
    logger.info('🔄 updateTopCoins called with', newCoins.length, 'coins', filterSymbols ? `(filtered to ${filterSymbols.length})` : '');
    logger.info('📊 First few coins:', newCoins.slice(0, 3).map(c => c.instrument_name));
    
    // Merge new coins with existing coins, updating only filtered symbols
      // CRITICAL FIX: Always preserve existing coins, even when filtering
      // This prevents symbols from disappearing when filterTradeYes is used
    let coinsToUpdate: TopCoin[];
    if (filterSymbols && filterSymbols.length > 0) {
      const existingCoins = topCoinsRef.current;
      const coinMap = new Map(existingCoins.map(coin => [coin.instrument_name, coin]));
      
        // CRITICAL: Start with ALL existing coins (preserve them)
        // Then update only the filtered coins with new data
        // This ensures symbols not in the filtered response remain visible
        const mergedMap = new Map<string, TopCoin>();
        
        // First, preserve all existing coins
        existingCoins.forEach(coin => {
          mergedMap.set(coin.instrument_name, coin);
        });
        
        // Then, update only the filtered coins with new data
      newCoins.forEach(coin => {
        if (filterSymbols.includes(coin.instrument_name)) {
            const existingCoin = coinMap.get(coin.instrument_name);
            mergedMap.set(coin.instrument_name, mergeCoinData(existingCoin, coin));
        }
      });
      
        coinsToUpdate = Array.from(mergedMap.values());
        
        // Log if any coins were preserved that aren't in filtered response
        const preservedInFilter = existingCoins
          .filter(coin => !filterSymbols.includes(coin.instrument_name))
          .map(coin => coin.instrument_name);
        if (preservedInFilter.length > 0) {
          logger.info(`🛡️ Preserved ${preservedInFilter.length} coins not in filtered response:`, preservedInFilter.slice(0, 5));
        }
        
      topCoinsRef.current = coinsToUpdate;
      setTopCoins(coinsToUpdate);
        logger.info(`✅ Updated ${coinsToUpdate.length} coins (${newCoins.length} filtered, ${preservedInFilter.length} preserved)`);
      
      // Only update timestamps for filtered coins
      const now = new Date();
      const updateTimes: {[key: string]: {price: Date, signals: Date}} = {};
      filterSymbols.forEach(symbol => {
        updateTimes[symbol] = {
          price: now,
          signals: lastUpdateTimesRef.current[symbol]?.signals || now
        };
      });
      setLastUpdateTimes(prev => ({...prev, ...updateTimes}));
    } else {
      // No filter - update all coins (initial load)
      // CRITICAL FIX: Preserve existing coins that are not in the new response
      // This prevents symbols from disappearing when they're not in MarketPrice but are in watchlist
      const existingCoins = topCoinsRef.current;
      const existingMap = new Map(existingCoins.map(coin => [coin.instrument_name, coin]));
      const newCoinsMap = new Map(newCoins.map(coin => [coin.instrument_name, coin]));
      
      // Start with existing coins and update/merge with new data
      const mergedMap = new Map<string, TopCoin>();
      
      // First, add all existing coins (preserve them even if not in new response)
      existingCoins.forEach(coin => {
        mergedMap.set(coin.instrument_name, coin);
      });
      
      // Then, update/merge with new coins from backend
      newCoins.forEach(coin => {
        const existingCoin = existingMap.get(coin.instrument_name);
        mergedMap.set(coin.instrument_name, mergeCoinData(existingCoin, coin));
      });
      
      coinsToUpdate = Array.from(mergedMap.values());
      
      // Log if any existing coins were preserved that aren't in new response
      const preservedSymbols = existingCoins
        .filter(coin => !newCoinsMap.has(coin.instrument_name))
        .map(coin => coin.instrument_name);
      if (preservedSymbols.length > 0) {
        logger.info(`🛡️ Preserved ${preservedSymbols.length} existing coins not in backend response:`, preservedSymbols);
      }
      
      topCoinsRef.current = coinsToUpdate;
      setTopCoins(coinsToUpdate);
      logger.info(`✅ setTopCoins called with ${coinsToUpdate.length} coins (${newCoins.length} from backend, ${preservedSymbols.length} preserved)`);
      
      // Record price update time for all coins
      const now = new Date();
      const updateTimes: {[key: string]: {price: Date, signals: Date}} = {};
      newCoins.forEach(coin => {
        updateTimes[coin.instrument_name] = {
          price: now,
          signals: lastUpdateTimes[coin.instrument_name]?.signals || now
        };
      });
      setLastUpdateTimes(prev => ({...prev, ...updateTimes}));
    }
    
    // Extract indicators from coins and populate signals object
    // This is critical: indicators are returned in the coin object from backend,
    // but the table reads them from the signals object
    const now = new Date();
    setSignals(prev => {
      const updated = { ...prev };
      const coinsToProcess = filterSymbols 
        ? coinsToUpdate.filter(coin => filterSymbols.includes(coin.instrument_name))
        : coinsToUpdate;
      
      coinsToProcess.forEach(coin => {
        // Always update signals for all coins (even if indicators are missing)
        // This ensures coins are tracked even if some indicators are missing
        const existingSignal = updated[coin.instrument_name] || {} as Partial<TradingSignals>;
        
        // Build signal object with available fields
        const signalData: Partial<TradingSignals> = {
          ...existingSignal,
          symbol: coin.instrument_name,
          exchange: 'CRYPTO_COM',
          price: coin.current_price || existingSignal.price || 0,
        };
        
        // Only set fields that are actually present in coin data
        // For numeric fields, also check for null (not just undefined) and allow 0 values
        if (coin.rsi !== undefined && coin.rsi !== null) signalData.rsi = coin.rsi;
        if (coin.atr !== undefined && coin.atr !== null) signalData.atr = coin.atr;
        if (coin.ma50 !== undefined && coin.ma50 !== null) signalData.ma50 = coin.ma50;
        if (coin.ma200 !== undefined && coin.ma200 !== null) signalData.ma200 = coin.ma200;
        if (coin.ema10 !== undefined && coin.ema10 !== null) signalData.ema10 = coin.ema10;
        if (coin.ma10w !== undefined && coin.ma10w !== null) signalData.ma10w = coin.ma10w;
        if (coin.volume_24h !== undefined) signalData.volume_24h = coin.volume_24h;
        if (coin.current_volume !== undefined) signalData.current_volume = coin.current_volume;
        if (coin.avg_volume !== undefined) signalData.avg_volume = coin.avg_volume;
        if (coin.volume_ratio !== undefined) signalData.volume_ratio = coin.volume_ratio;
        
        // Extract resistance levels from coin data (newly added from backend)
        if (coin.res_up !== undefined) signalData.res_up = coin.res_up;
        if (coin.res_down !== undefined) signalData.res_down = coin.res_down;
        if (coin.strategy) {
          signalData.strategy = coin.strategy;
        } else if (!signalData.strategy && existingSignal?.strategy) {
          signalData.strategy = existingSignal.strategy;
        }
        
        // Preserve existing signal data if present (but allow override from coin data)
        if (existingSignal.res_up === undefined && coin.res_up === undefined) {
          // Keep existing if no new data
        }
        if (existingSignal.res_down === undefined && coin.res_down === undefined) {
          // Keep existing if no new data
        }
        // Note: ma10w is already copied from coin.ma10w above, no need to preserve from existingSignal
        if (existingSignal.signals) signalData.signals = existingSignal.signals;
        
        updated[coin.instrument_name] = signalData as TradingSignals;
        
        // Update signals timestamp
        setLastUpdateTimes(prevTimes => ({
          ...prevTimes,
          [coin.instrument_name]: {
            price: prevTimes[coin.instrument_name]?.price || now,
            signals: now
          }
        }));
        
        logger.info(`✅ Extracted indicators for ${coin.instrument_name}:`, {
          rsi: coin.rsi,
          atr: coin.atr,
          ma50: coin.ma50,
          ma200: coin.ma200,
          ema10: coin.ema10,
          ma10w: coin.ma10w,
          res_up: coin.res_up,
          res_down: coin.res_down
        });
      });
      return updated;
    });
  }, [setTopCoins]);

  const applyPriceToTopCoins = useCallback(
    (symbol: string, price: number) => {
      if (!price || price <= 0) {
        return;
      }
      const updatedCoins = topCoinsRef.current.map(coin =>
        coin.instrument_name === symbol ? { ...coin, current_price: price } : coin
      );
      // Only update state if something actually changed
      const hasChanged = updatedCoins.some((coin, index) => coin !== topCoinsRef.current[index]);
      if (hasChanged) {
        updateTopCoins(updatedCoins);
      }
    },
    [updateTopCoins]
  );
  
  const [_signalConfig, setSignalConfig] = useState({
    rsiPeriod: 14,
    rsiBuyThreshold: 40,
    rsiSellThreshold: 70,
    ma50Period: 50,
    ema10Period: 10,
    ma10wPeriod: 70,
    atrPeriod: 14,
    volumePeriod: 10
  });

  // Helper function to normalize symbol (add _USDT if no pair specified)
  const normalizeSymbol = useCallback((symbol: string | null | undefined): string => {
    if (!symbol) return '';
    const upperSymbol = symbol.toString().toUpperCase().trim();
    if (!upperSymbol) return '';
    
    // Check if symbol already has a pair (USD, USDT, BTC, ETH, EUR, etc.)
    const hasPair = upperSymbol.includes('_') && 
      ['USDT', 'USD', 'BTC', 'ETH', 'EUR', 'USDC'].some(pair => upperSymbol.endsWith(`_${pair}`));
    
    if (!hasPair) {
      // No pair specified - add _USDT
      return `${upperSymbol}_USDT`;
    }
    
    return upperSymbol;
  }, []);

  // Helper function to get price for an asset (ONLY from backend data, NO external API calls)
  // Frontend should ONLY read from backend-processed data (topCoins, signals, dashboard state)
  const getAssetPrice = useCallback(async (asset: string): Promise<number> => {
    // Fiat currencies are 1.0 (or exchange rate for EUR, etc.)
    if (asset === 'USD' || asset === 'USDT') {
      return 1.0;
    }
    if (asset === 'EUR') {
      // Approximate EUR/USD exchange rate
      return 1.08;
    }
    
    // Try to find price from topCoins (backend-processed data)
    // This is the most reliable source as it comes from the backend
    const coin = topCoins.find(c => {
      const base = c.base_currency?.toUpperCase();
      const instrumentBase = c.instrument_name?.split('_')[0]?.toUpperCase();
      return base === asset.toUpperCase() || instrumentBase === asset.toUpperCase();
    });
    if (coin?.current_price && coin.current_price > 0) {
      logger.info(`✅ Found price for ${asset} in topCoins: $${coin.current_price} (source: ${coin.instrument_name})`);
      return coin.current_price;
    }
    
    // Try to find price from signals (backend-processed data)
    const signalKey = Object.keys(signals).find(key => {
      const base = key.split('_')[0]?.toUpperCase();
      return base === asset.toUpperCase();
    });
    if (signalKey) {
      const signal = signals[signalKey];
      if (signal?.price && signal.price > 0) {
        logger.info(`✅ Found price for ${asset} in signals: $${signal.price} (symbol: ${signalKey})`);
        return signal.price;
      }
    }
    
    // NO external API calls - backend should provide all prices
    // Return 0 if price not found in backend data
    logger.debug(`⚠️ No price found for ${asset} in backend data (topCoins or signals)`);
    return 0;
  }, [topCoins, signals]);

  // Fetch portfolio from snapshot (fast, cached)
  const fetchPortfolio = useCallback(async (options: { showLoader?: boolean; backgroundRefresh?: boolean; forceRefresh?: boolean } = {}) => {
    const { showLoader = false, backgroundRefresh = false, forceRefresh = false } = options;
    if (showLoader) {
      setPortfolioLoading(true);
    }
    
    // If forceRefresh is true (user clicked refresh button), force a fresh snapshot from Crypto.com
    if (forceRefresh || showLoader) {
      try {
        logger.info('🔄 Forcing fresh portfolio snapshot from Crypto.com...');
        // refreshPortfolio function removed - using getDashboardState instead
        const refreshResult = await getDashboardState();
        if (refreshResult) {
          logger.info(`✅ Portfolio snapshot refreshed`);
        } else {
          logger.warn(`⚠️ Portfolio refresh failed: ${refreshResult.error || 'Unknown error'}`);
        }
      } catch (refreshErr) {
        logger.warn('⚠️ Failed to refresh portfolio snapshot, will use cached data:', refreshErr);
        // Don't fail the entire fetch if refresh fails - continue with cached data
      }
    }
    
    // Helper function to update portfolio from dashboard state
    const updatePortfolioFromState = (dashboardState: DashboardState, source: string) => {
      try {
        // Expose latest dashboard state globally so helpers (like getOpenOrdersInfo)
        // can access unified open_position_counts without threading state through
        // multiple layers. This is read-only on the client.
        (window as Window & { __LAST_DASHBOARD_STATE__?: DashboardState }).__LAST_DASHBOARD_STATE__ = dashboardState;
      } catch {
        // Ignore if window is not available (e.g., during SSR)
      }
      
      // Set bot status - only update if we have valid status data
      // Preserve last known status on transient errors (don't immediately mark as stopped)
      if (dashboardState.bot_status && dashboardState.bot_status.status) {
        // Only update to "stopped" if we have a clear reason or explicit stopped status
        // If reason is "Status unavailable (checking...)", preserve last known status
        if (dashboardState.bot_status.status === 'stopped' && 
            dashboardState.bot_status.reason === 'Status unavailable (checking...)') {
          // This is a transient error - don't update status
          // Bot status unavailable during initial load, using last known status
        } else {
          setBotStatus(dashboardState.bot_status);
        }
      }
      
      logger.info(`🔍 ${source} - dashboardState:`, {
        source: dashboardState.source,
        balancesCount: dashboardState.balances?.length || 0,
        totalUsd: dashboardState.total_usd_value,
        hasBalances: !!dashboardState.balances && dashboardState.balances.length > 0,
        balances: dashboardState.balances?.slice(0, 5).map(b => ({
          asset: b.asset,
          balance: b.balance,
          total: b.total,
          usd_value: b.usd_value,
          market_value: b.market_value
        })) || []
      });
      
      const dashboardFetchFailed = dashboardState.errors?.some(err => err?.startsWith('FETCH_FAILED')) ?? false;

      const fallbackToEmbeddedPortfolio = (_reason?: string) => {
        // Silenced verbose warnings - this is expected behavior
        // if (reason) {
        //   logger.warn(reason);
        // }
        const fallbackAssets = dashboardState.portfolio?.assets ?? [];
        const fallbackTotal =
          dashboardState.portfolio?.total_value_usd
          ?? dashboardState.total_usd_value
          ?? fallbackAssets.reduce((sum, asset) => sum + (asset.value_usd ?? 0), 0);
        logger.info(`📊 Falling back to embedded portfolio data (${fallbackAssets.length} assets, total=$${fallbackTotal.toFixed(2)})`);
        setPortfolio({ 
          assets: fallbackAssets, 
          total_value_usd: fallbackTotal,
          total_assets_usd: dashboardState.portfolio?.total_assets_usd,
          total_collateral_usd: dashboardState.portfolio?.total_collateral_usd,
          total_borrowed_usd: dashboardState.portfolio?.total_borrowed_usd,
          portfolio_value_source: dashboardState.portfolio?.portfolio_value_source
        });
        // setPortfolioLastUpdate(new Date()); // Removed - not currently used
        setPortfolioError(dashboardFetchFailed ? PORTFOLIO_UNAVAILABLE_MESSAGE : null);
      };

      if (dashboardState.balances && dashboardState.balances.length > 0) {
        // Normalize balances: ensure 'asset' field exists (use currency/coin as fallback)
        // Also ensure usd_value and market_value are preserved
        const normalizedBalances = dashboardState.balances
          .filter(bal => bal && (bal.asset || bal.currency))
          .map(bal => ({
            ...bal,
            asset: bal.asset || bal.currency || '',
            // Preserve USD values - prioritize usd_value, then market_value
            // Don't filter by > 0 - preserve all values including 0
            usd_value: (bal.usd_value !== undefined && bal.usd_value !== null)
              ? bal.usd_value
              : ((bal.market_value !== undefined && bal.market_value !== null)
                  ? bal.market_value
                  : undefined),
            market_value: (bal.market_value !== undefined && bal.market_value !== null)
              ? bal.market_value
              : ((bal.usd_value !== undefined && bal.usd_value !== null)
                  ? bal.usd_value
                  : undefined)
          }));
        setRealBalances(normalizedBalances);

        logger.info(`${source} - normalized balance sample:`, normalizedBalances[0]);

        // Prioritize portfolio.assets from backend if available (has usd_value directly from Crypto.com)
        // Otherwise fall back to creating assets from normalized balances
        let assetsWithValues: PortfolioAsset[];
        if (dashboardState.portfolio?.assets && dashboardState.portfolio.assets.length > 0) {
          // Use backend portfolio assets directly - they have usd_value from Crypto.com
          assetsWithValues = dashboardState.portfolio.assets
            .filter(asset => asset && asset.coin)
          .map(asset => ({
          ...asset,
              // Ensure value_usd is set from usd_value if available
              value_usd: asset.value_usd ?? asset.usd_value ?? 0,
          updated_at: new Date().toISOString()
        }));
          logger.info(`✅ Using backend portfolio.assets (${assetsWithValues.length} assets with usd_value from Crypto.com)`);
        } else {
          // Fallback: create assets from normalized balances
          assetsWithValues = dashboardBalancesToPortfolioAssets(normalizedBalances)
            .filter(asset => asset && asset.coin)
            .map(asset => ({
              ...asset,
              updated_at: new Date().toISOString()
            }));
          logger.info(`⚠️ Using fallback: created assets from normalized balances (${assetsWithValues.length} assets)`);
        }

        if (assetsWithValues.length > 0) {
          // Calculate total as sum of ALL asset values (including negatives)
          // Prioritize backend total_value_usd if available, otherwise calculate from assets
          const calculatedTotal = assetsWithValues.reduce((sum, asset) => sum + (asset.value_usd ?? asset.usd_value ?? 0), 0);
          const totalUsd = dashboardState.portfolio?.total_value_usd ?? dashboardState.total_usd_value ?? calculatedTotal;
          
          // Calculate borrowed amount: sum of negative USD/USDT balances
          const borrowedAmount = assetsWithValues
            .filter(asset => {
              const coin = asset.coin?.toUpperCase() || '';
              return (coin === 'USD' || coin === 'USDT') && (asset.value_usd ?? 0) < 0;
            })
            .reduce((sum, asset) => sum + Math.abs(asset.value_usd ?? 0), 0);
          
          if (borrowedAmount > 0) {
            setTotalBorrowed(borrowedAmount);
          }

          logger.info(`✅ Processed ${assetsWithValues.length} assets from ${normalizedBalances.length} balances`);
          logger.info(`📊 Total Portfolio Value (backend=${dashboardState.total_usd_value ?? 0}, calculated=${calculatedTotal})`);

          const assetsWithUsd = assetsWithValues.filter(a => (a.value_usd ?? a.usd_value ?? 0) > 0);
          if (assetsWithUsd.length === 0) {
            // Silenced: This is expected when backend hasn't computed USD values yet
            // logger.warn('⚠️ WARNING: Portfolio has balances but USD values are 0. Backend should calculate USD values on next sync.');
          } else {
            // Silenced verbose logging
            // logger.info(`💰 Assets with USD values (${assetsWithUsd.length}/${assetsWithValues.length}):`);
            assetsWithUsd.slice(0, 10).forEach(asset => {
              const usdValue = asset.value_usd ?? asset.usd_value ?? 0;
              logger.info(`   ${asset.coin}: $${usdValue.toFixed(2)} (balance: ${asset.balance.toFixed(8)})`);
            });
          }

          setPortfolio({ 
            assets: assetsWithValues, 
            total_value_usd: totalUsd,
            total_assets_usd: dashboardState.portfolio?.total_assets_usd,
            total_collateral_usd: dashboardState.portfolio?.total_collateral_usd,
            total_borrowed_usd: dashboardState.portfolio?.total_borrowed_usd,
            portfolio_value_source: dashboardState.portfolio?.portfolio_value_source
          });
          // setPortfolioLastUpdate(new Date()); // Removed - not currently used
          setPortfolioError(dashboardFetchFailed ? PORTFOLIO_UNAVAILABLE_MESSAGE : null);
          return true; // Successfully updated
        } else {
          // Silenced: This is expected when backend hasn't computed USD values yet
          // fallbackToEmbeddedPortfolio('⚠️ Balances returned but no USD values were computed. Using embedded portfolio object.');
          fallbackToEmbeddedPortfolio();
          return false;
        }
      } else {
        fallbackToEmbeddedPortfolio('⚠️ No balances in dashboardState, using embedded portfolio data');
        return false;
      }
    };
    
    try {
      // STEP 1: Load snapshot FIRST (fast, cached)
      logger.info('📸 Loading dashboard snapshot (fast)...');
      let snapshotLoaded = false;
      try {
        const snapshot = await getDashboardSnapshot();
        const dashboardState = snapshot.data;
        
        // Update snapshot metadata
        setSnapshotStale(snapshot.stale);
        setSnapshotStaleSeconds(snapshot.stale_seconds);
        if (snapshot.last_updated_at) {
          setSnapshotLastUpdated(new Date(snapshot.last_updated_at));
        }
        
        // Only update portfolio if snapshot has data and is not empty
        if (!snapshot.empty && dashboardState.balances && dashboardState.balances.length > 0) {
          logger.info(`✅ Snapshot loaded with ${dashboardState.balances.length} balances - displaying immediately`);
          snapshotLoaded = updatePortfolioFromState(dashboardState, 'fetchPortfolio:snapshot');

          if (Array.isArray(dashboardState.open_orders_summary)) {
            setOpenOrdersSummary(dashboardState.open_orders_summary);
            setOpenOrdersSummaryLoading(false);
            const updatedAt = snapshot.last_updated_at ? new Date(snapshot.last_updated_at) : new Date();
            setOpenOrdersSummaryLastUpdate(updatedAt);
          }
          
          // Fetch loan data and TP/SL values (non-blocking)
          (async () => {
      try {
        const loansUrl = `${getApiUrl()}/loans`;
        const loansResponse = await fetch(loansUrl, { signal: AbortSignal.timeout(5000) });
        if (loansResponse.ok) {
          const loans = await loansResponse.json() as Loan[];
          const totalBorrowedAmount = loans.reduce((sum: number, loan: Loan) => sum + (loan.borrowed_usd_value || 0), 0);
          setTotalBorrowed(totalBorrowedAmount);
        }
      } catch {
        // Silently handle loans fetch errors - not critical for dashboard
        setTotalBorrowed(0);
      }
      
      try {
        const tpSlValues = await getTPSLOrderValues();
        setTpSlOrderValues(tpSlValues);
      } catch {
        // Silently handle TP/SL fetch errors - optional feature
        setTpSlOrderValues({});
      }
          })();
        } else {
          // Snapshot is empty during initial load, will refresh in background
        }
      } catch (snapshotErr) {
        logHandledError(
          'fetchPortfolio:snapshot',
          'Failed to load snapshot - will try background refresh',
          snapshotErr,
          'warn'
        );
      }
      
      // STEP 2: Background refresh with full state (only if not already doing background refresh)
      if (!backgroundRefresh) {
        logger.info('🔄 Starting background refresh with full dashboard state...');
        // Don't await - let it run in background without blocking UI
        (async () => {
          try {
            const dashboardState = await getDashboardState();
            logger.info('✅ Background refresh completed - updating portfolio with fresh data');
            updatePortfolioFromState(dashboardState, 'fetchPortfolio:background');
            if (Array.isArray(dashboardState.open_orders_summary)) {
              setOpenOrdersSummary(dashboardState.open_orders_summary);
              setOpenOrdersSummaryLastUpdate(new Date());
              setOpenOrdersSummaryLoading(false);
            }
            
            // Also update snapshot metadata if available
            try {
              const freshSnapshot = await getDashboardSnapshot();
              setSnapshotStale(freshSnapshot.stale);
              setSnapshotStaleSeconds(freshSnapshot.stale_seconds);
              if (freshSnapshot.last_updated_at) {
                setSnapshotLastUpdated(new Date(freshSnapshot.last_updated_at));
              }
            } catch (snapshotErr) {
              const errorMsg = snapshotErr instanceof Error ? snapshotErr.message : String(snapshotErr);
              // Only log if it's not a network error (those are expected occasionally)
              if (!errorMsg.includes('Failed to fetch') && !errorMsg.includes('NetworkError')) {
                logger.debug('Background snapshot refresh error:', snapshotErr);
              }
              // Ignore snapshot errors in background refresh - keep showing last good data
            }
          } catch (refreshErr) {
            logHandledError(
              'fetchPortfolio:background',
              'Background refresh failed - keeping snapshot data visible',
              refreshErr,
              'warn'
            );
            // Don't clear portfolio on background refresh failure - keep showing snapshot
            // Only show warning if we didn't have snapshot data
            if (!snapshotLoaded) {
              setPortfolioError('Background refresh failed. Showing cached data if available.');
            }
          }
        })();
      }
      
      // If snapshot didn't load any data, we still show empty but don't block
      if (!snapshotLoaded) {
        // Portfolio data not available yet, will load in background
      }
    } catch (err) {
      logHandledError(
        'fetchPortfolio',
        'Failed to fetch portfolio - keeping last known data visible',
        err,
        'warn'
      );
      // Don't clear portfolio on error - keep showing last known data
      setPortfolioError('Failed to load portfolio. Retrying in background...');
    } finally {
      setPortfolioLoading(false);
    }
  }, [getAssetPrice]);

  // Function to remove duplicate coins
  // Calculate SL/TP values based on current price and signals
  const calculateSLTPValues = useCallback((coin: TopCoin) => {
    const currentPrice = coin?.current_price;
    const signal = signals[coin?.instrument_name];
    const isAggressive = coinTradeStatus[normalizeSymbolKey(coin?.instrument_name) + '_SL_TP'];
    const slOverride = coinSLPercent[coin?.instrument_name];
    const tpOverride = coinTPPercent[coin?.instrument_name];
    
    logger.info(`🔍 Calculating SL/TP for ${coin?.instrument_name}:`, {
      currentPrice,
      hasSignal: !!signal,
      isAggressive,
      slOverride,
      tpOverride,
      res_up: signal?.res_up,
      res_down: signal?.res_down
    });
    
    if (!currentPrice || !signal || !coin?.instrument_name) {
      // Missing data for coin during initial load (normal)
      return { sl: 0, tp: 0 };
    }
    
    let slPrice = 0;
    let tpPrice = 0;
    
    // Calculate SL Price
    if (slOverride && slOverride !== '') {
      // Override exists: currentPrice × (1 + value/100)
      const slValue = parseFloat(slOverride);
      if (!isNaN(slValue)) {
        slPrice = currentPrice * (1 + slValue / 100);
      }
    } else {
      // No override: Use resistance levels
      if (isAggressive) {
        // Aggressive: Use res_down for SL (below current price)
        slPrice = signal.res_down || (currentPrice * 0.98);
      } else {
        // Conservative: Use res_down for SL (below current price) - more conservative = lower SL
        slPrice = signal.res_down || (currentPrice * 0.97);
      }
    }
    
    // Calculate TP Price
    if (tpOverride && tpOverride !== '') {
      // Override exists: currentPrice × (1 + value/100)
      const tpValue = parseFloat(tpOverride);
      if (!isNaN(tpValue)) {
        tpPrice = currentPrice * (1 + tpValue / 100);
      }
    } else {
      // No override: Use resistance levels
      if (isAggressive) {
        // Aggressive: Use res_up for TP (above current price)
        tpPrice = signal.res_up || (currentPrice * 1.04);
      } else {
        // Conservative: Use res_up for TP (above current price) - more conservative = higher TP
        tpPrice = signal.res_up || (currentPrice * 1.06);
      }
    }
    
    const result = {
      sl: slPrice,
      tp: tpPrice
    };
    
    logger.info(`✅ Final SL/TP for ${coin.instrument_name}:`, result);
    logger.info(`🔍 SL Price details: ${slPrice} (type: ${typeof slPrice})`);
    logger.info(`🔍 TP Price details: ${tpPrice} (type: ${typeof tpPrice})`);
    return result;
  }, [signals, coinTradeStatus, coinSLPercent, coinTPPercent]);

  const handleQueueSuccess = useCallback((queue: 'fast' | 'slow') => {
    const state = schedulerRef.current;
    if (queue === 'fast') {
      state.fastErrorCount = 0;
      state.fastBackoffMs = REFRESH_FAST_MS;
      state.fastPausedUntil = 0;
      lastFastErrorRef.current = null;
      setFastQueueRateLimited(false);
    } else {
      state.slowErrorCount = 0;
      state.slowBackoffMs = REFRESH_SLOW_MS;
    }
  }, [setFastQueueRateLimited]);

  const handleQueueError = useCallback((queue: 'fast' | 'slow', error: unknown) => {
    const apiError = error as ApiError | undefined;
    const state = schedulerRef.current;

    if (queue === 'fast') {
      state.fastErrorCount += 1;
      lastFastErrorRef.current = apiError ?? null;

      const retryFromHeader = apiError?.retryAfterMs ?? 0;
      if (apiError?.status === RATE_LIMIT_STATUS) {
        const penalty = Math.min(
          MAX_FAST_BACKOFF_MS,
          Math.max(REFRESH_SLOW_MS, retryFromHeader || REFRESH_SLOW_MS)
        );
        state.fastBackoffMs = penalty;
        state.fastPausedUntil = Date.now() + penalty;
        logger.warn(`⚠️ Fast queue rate-limited. Backing off to ${penalty}ms`);
        setFastQueueRateLimited(true);
      } else if ((apiError?.status ?? 0) >= 500 || !apiError?.status) {
        const penalty = Math.min(
          MAX_FAST_BACKOFF_MS,
          Math.max(REFRESH_FAST_MS, state.fastBackoffMs * 2)
        );
        state.fastBackoffMs = penalty;
        state.fastPausedUntil = Date.now() + penalty;
        logger.warn(`⚠️ Fast queue server error (${apiError?.status ?? 'n/a'}). Backoff=${penalty}ms`);
      } else {
        logger.warn(`⚠️ Fast queue error without status`, apiError);
      }
    } else {
      state.slowErrorCount += 1;
      const penalty = Math.min(
        REFRESH_SLOW_MS * 4,
        Math.max(REFRESH_SLOW_MS, state.slowBackoffMs * 1.5)
      );
      state.slowBackoffMs = penalty;
      logger.warn(`⚠️ Slow queue error (${apiError?.status ?? 'n/a'}). Backoff=${penalty}ms`);
    }
  }, [setFastQueueRateLimited]);

  const loadCachedTopCoins = useCallback(() => {
    try {
      const cached = localStorage.getItem('top_coins_cache');
      if (!cached) {
        return false;
      }
      const parsed = JSON.parse(cached) as {
        coins?: TopCoin[];
        fetchedAt?: string | number;
      };
      if (parsed?.coins?.length) {
        updateTopCoins(parsed.coins);
        if (parsed.fetchedAt) {
          const date = new Date(parsed.fetchedAt);
          if (!Number.isNaN(date.valueOf())) {
            setLastTopCoinsFetchAt(date);
          }
        }
        setTopCoinsError(null);
        setTopCoinsLoading(false);
        logger.info(`💾 Loaded ${parsed.coins.length} cached top coins snapshot`);
        return true;
      }
    } catch (err) {
      logger.warn('Failed to load cached top coins snapshot:', err);
    }
    return false;
  }, [updateTopCoins]);

  const formatTimeAgo = useCallback((date?: Date) => {
    if (!date) return '—';
    const diff = Date.now() - date.getTime();
    if (!Number.isFinite(diff) || diff < 0) return '—';
    if (diff < 1000) return 'now';
    const seconds = Math.floor(diff / 1000);
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h`;
    const days = Math.floor(hours / 24);
    return `${days}d`;
  }, []);

  const buildLastUpdatedTitle = useCallback((symbol: string) => {
    const timestamps = lastUpdateTimes[symbol];
    if (!timestamps) {
      return 'Price: —\nSignals: —';
    }
    const priceLabel = timestamps.price ? formatDateTime(timestamps.price) : '—';
    const signalsLabel = timestamps.signals ? formatDateTime(timestamps.signals) : '—';
    return `Price: ${priceLabel}\nSignals: ${signalsLabel}`;
  }, [lastUpdateTimes]);

  // Fetch trading signals for a symbol
  const fetchSignals = useCallback(async (symbol: string) => {
    try {
      // OPTIMIZATION: Removed 500ms delay - batching in runFastTick already handles throttling
      // This reduces total processing time and prevents unnecessary delays
      
      // Load signal config from localStorage if available
      const savedConfig = localStorage.getItem('signal_config');
      const config = savedConfig ? JSON.parse(savedConfig) : null;

      const signalData = await getTradingSignals(symbol, config);
      let updatedSignal = signalData ? { ...signalData } : null;
      let price = updatedSignal?.price ?? 0;

      // NO external API calls - use only backend data
      // If price not available in signal, try to find it in topCoins (backend-processed data)
      if (!price || price <= 0) {
        const coin = topCoinsRef.current.find(c => c.instrument_name === symbol);
        if (coin?.current_price && coin.current_price > 0) {
          price = coin.current_price;
          if (updatedSignal) {
            updatedSignal = { ...updatedSignal, price: coin.current_price };
          }
          applyPriceToTopCoins(symbol, coin.current_price);
          logger.info(`✅ Found price for ${symbol} in topCoins: $${coin.current_price}`);
        } else {
          logger.debug(`⚠️ No price available for ${symbol} in backend data (signal or topCoins)`);
        }
      } else {
        applyPriceToTopCoins(symbol, price);
      }

      if (updatedSignal) {
        setSignals(prev => ({
          ...prev,
          [symbol]: { ...(prev[symbol] || {}), ...updatedSignal } as TradingSignals,
        }));
      }
      
      // Record signals update time - preserve existing price update time if available
      const now = new Date();
      setLastUpdateTimes(prev => ({
        ...prev,
        [symbol]: {
          price: prev[symbol]?.price || now,  // Preserve existing price time, use now if first time
          signals: now  // Always update signals time
        }
      }));
      
      logger.info(`📊 Updated signals for ${symbol}:`, price || 'no price available');
    } catch (err) {
      // Handle circuit breaker errors gracefully - they're protection mechanisms, not real errors
      const error = err as Error & { status?: number; retryAfterMs?: number };
      if (error.message?.includes('Circuit breaker open')) {
        // Circuit breaker is open - this is expected behavior when endpoint is failing
        // Don't log as error, just skip this fetch silently
        // The circuit breaker will auto-reset after timeout
        const retryAfter = error.retryAfterMs ? Math.ceil(error.retryAfterMs / 1000) : 30;
        logger.debug(`⏸️ Signals circuit breaker open for ${symbol}, skipping fetch. Will auto-retry in ~${retryAfter}s`);
        // Don't throw - just silently skip this fetch
        return;
      }
      
      // For other errors, log and re-throw
      logHandledError(
        `fetchSignals:${symbol}`,
        `Failed to fetch signals for ${symbol}; will retry`,
        err
      );
      throw err;
    }
  }, [applyPriceToTopCoins]);

  const runFastTick = useCallback(async () => {
    const symbols = fastQueueRef.current;
    if (!symbols.length) {
      return;
    }

    // Also update top coins data for Trade YES coins ONLY (they need frequent price updates)
    const fetchTopCoinsFn = (fetchTopCoinsRef.current || (() => Promise.resolve()));
    try {
      await fetchTopCoinsFn(true, true);
    } catch (err) {
      // Don't fail the entire fast tick if top coins fetch fails
      logger.warn('⚠️ Failed to fetch top coins (Trade YES) in fast tick:', err);
      // Update timestamp even on error to show last attempt time
      setLastTopCoinsFetchAt(new Date());
    }

    logger.info(`🔄 Fast tick: Processing ${symbols.length} symbols (Trade YES) at ${new Date().toLocaleTimeString()}`);
    for (let i = 0; i < symbols.length; i += FAST_BATCH_SIZE) {
      const batch = symbols.slice(i, i + FAST_BATCH_SIZE);
      logger.info(`📊 Fast batch ${i / FAST_BATCH_SIZE + 1}:`, batch);
      const results = await Promise.allSettled(batch.map(symbol => fetchSignals(symbol)));
      const failure = results.find((result): result is PromiseRejectedResult => result.status === 'rejected');
      if (failure) {
        throw failure.reason;
      }
      if (i + FAST_BATCH_SIZE < symbols.length) {
        await wait(FAST_STAGGER_MS);
      }
    }
    logger.info(`✅ Fast tick completed for ${symbols.length} symbols`);
  }, [fetchSignals]);

  // We need to use refs to avoid circular dependency issues
  const fetchTopCoinsRef = useRef<((preserveLocalChanges?: boolean, filterTradeYes?: boolean) => Promise<void>) | null>(null);
  const fetchPortfolioRef = useRef<(() => Promise<void>) | null>(null);
  const fetchOpenOrdersRef = useRef<(() => Promise<void>) | null>(null);
  const fetchOpenOrdersSummaryRef = useRef<((options?: { showLoader?: boolean; backgroundRefresh?: boolean }) => Promise<void>) | null>(null);
  const fetchExecutedOrdersRef = useRef<((options?: { showLoader?: boolean; limit?: number; offset?: number; loadAll?: boolean }) => Promise<void>) | null>(null);
  const fetchSignalsRef = useRef<((symbol: string) => Promise<void>) | null>(null);

  const runSlowTick = useCallback(async () => {
    // Use refs to avoid circular dependency - these will be set by useEffect hooks
    const fetchPortfolioFn = (fetchPortfolioRef.current || (() => Promise.resolve()));
    const fetchOpenOrdersFn = (fetchOpenOrdersRef.current || (() => Promise.resolve()));
    const fetchExecutedOrdersFn = (fetchExecutedOrdersRef.current || (() => Promise.resolve()));
    const fetchTopCoinsFn = (fetchTopCoinsRef.current || (() => Promise.resolve()));
    const fetchSignalsFn = (fetchSignalsRef.current || (() => Promise.resolve()));

    // Sync executed orders from exchange if we have no orders or if it's the first load
    // This ensures P/L calculation has data to work with
    const shouldSyncOrders = executedOrders.length === 0;
    if (shouldSyncOrders) {
      logger.info('🔄 No executed orders found, syncing from exchange...');
    }

    await Promise.allSettled([
      fetchPortfolioFn(),
      fetchOpenOrdersFn(),
      fetchExecutedOrdersFn({ showLoader: shouldSyncOrders, loadAll: shouldSyncOrders }),
    ]);
    
    // Update top coins data for Trade NO coins (less frequent updates)
    // Also fetch ALL coins periodically to ensure all prices are updated
    try {
      await fetchTopCoinsFn(true, undefined);
      // Fetch ALL coins every 3rd slow tick to ensure all prices are updated
      // This ensures coins without Trade YES/NO status also get price updates
      const slowTickCount = schedulerRef.current.slowTickCount || 0;
      if (slowTickCount % 3 === 0) {
        logger.info('🔄 Fetching ALL coins (no filter) to update all prices');
        await fetchTopCoinsFn(true, undefined);
      }
      schedulerRef.current.slowTickCount = slowTickCount + 1;
    } catch (err) {
      // Don't fail the entire slow tick if top coins fetch fails
      logger.warn('⚠️ Failed to fetch top coins (Trade NO) in slow tick:', err);
      // Update timestamp even on error to show last attempt time
      setLastTopCoinsFetchAt(new Date());
    }

    const slowSymbols = slowQueueRef.current;
    if (!slowSymbols.length) {
      logger.info('⏸️ Slow queue empty, skipping signals update');
      return;
    }

    logger.info(`🔄 Slow tick: Processing ${slowSymbols.length} symbols (Trade NO) at ${new Date().toLocaleTimeString()}`);
    for (let i = 0; i < slowSymbols.length; i += SLOW_BATCH_SIZE) {
      const batch = slowSymbols.slice(i, i + SLOW_BATCH_SIZE);
      logger.info(`📊 Slow batch ${i / SLOW_BATCH_SIZE + 1}:`, batch);
      const results = await Promise.allSettled(batch.map(symbol => fetchSignalsFn(symbol)));
      const failure = results.find((result): result is PromiseRejectedResult => result.status === 'rejected');
      if (failure) {
        throw failure.reason;
      }
      if (i + SLOW_BATCH_SIZE < slowSymbols.length) {
        await wait(FAST_STAGGER_MS * 2);
      }
    }
    logger.info(`✅ Slow tick completed for ${slowSymbols.length} symbols`);
  }, []);

  const scheduleFastTick = useCallback((delay?: number) => {
    const state = schedulerRef.current;

    if (state.fastTimer) {
      clearTimeout(state.fastTimer);
      state.fastTimer = null;
    }

    if (fastQueueRef.current.length === 0) {
      return;
    }

    const now = Date.now();
    let waitMs = delay ?? state.fastBackoffMs;
    if (delay === undefined) {
      if (state.fastPausedUntil > now) {
        waitMs = Math.max(waitMs, state.fastPausedUntil - now);
      }
      waitMs = Math.max(REFRESH_FAST_MS, waitMs);
    }
    
    logger.info(`⏰ Scheduling fast tick in ${waitMs}ms (${waitMs / 1000}s)`);

    const tick = async () => {
      markJobStart();
      try {
        await runFastTick();
        handleQueueSuccess('fast');
      } catch (err) {
        handleQueueError('fast', err);
      } finally {
        markJobEnd();
        const hasFast = fastQueueRef.current.length > 0;
        if (hasFast) {
          scheduleFastTick();
        } else {
          state.fastTimer = null;
        }
      }
    };

    state.fastTimer = setTimeout(tick, waitMs);
  }, [handleQueueError, handleQueueSuccess, markJobEnd, markJobStart, runFastTick]);

  const scheduleSlowTick = useCallback((delay?: number) => {
    const state = schedulerRef.current;

    if (state.slowTimer) {
      clearTimeout(state.slowTimer);
      state.slowTimer = null;
    }

    let waitMs = delay ?? state.slowBackoffMs;
    if (delay === undefined) {
      waitMs = Math.max(REFRESH_SLOW_MS, waitMs);
    }
    
    logger.info(`⏰ Scheduling slow tick in ${waitMs}ms (${waitMs / 1000}s)`);

    const tick = async () => {
      markJobStart();
      try {
        await runSlowTick();
        handleQueueSuccess('slow');
      } catch (err) {
        handleQueueError('slow', err);
      } finally {
        markJobEnd();
        scheduleSlowTick();
      }
    };

    state.slowTimer = setTimeout(tick, waitMs);
  }, [handleQueueError, handleQueueSuccess, markJobEnd, markJobStart, runSlowTick]);

  useEffect(() => {
    const state = schedulerRef.current;

    const coins = topCoinsRef.current;
    if (coins.length === 0) {
      fastQueueRef.current = [];
      slowQueueRef.current = [];
      if (state.fastTimer) {
        clearTimeout(state.fastTimer);
        state.fastTimer = null;
      }
      if (!state.slowTimer) {
        scheduleSlowTick();
      }
      return;
    }

    const fastSymbolSet = new Set(
      coins
        .filter((coin) => coin.instrument_name && coinTradeStatus[normalizeSymbolKey(coin.instrument_name)] === true)
        .map((coin) => coin.instrument_name)
        .filter((symbol): symbol is string => Boolean(symbol))
    );
    const fastSymbols = Array.from(fastSymbolSet);
    const slowSymbolSet = new Set(
      coins
        .filter((coin) => coin.instrument_name && coinTradeStatus[normalizeSymbolKey(coin.instrument_name)] !== true)
        .map((coin) => coin.instrument_name)
        .filter((symbol): symbol is string => Boolean(symbol))
    );
    const slowSymbols = Array.from(slowSymbolSet).filter(symbol => !fastSymbolSet.has(symbol));
    
    logger.info(`🔀 Queue separation: Fast (YES)=${fastSymbols.length}, Slow (NO)=${slowSymbols.length}`);
    if (fastSymbols.length > 0) logger.info(`  Fast symbols:`, fastSymbols);
    if (slowSymbols.length > 0) logger.info(`  Slow symbols:`, slowSymbols);

    const newFastSignature = fastSymbols.slice().sort().join('|');
    const currentFastSignature = fastQueueRef.current.slice().sort().join('|');

    if (newFastSignature !== currentFastSignature) {
      fastQueueRef.current = fastSymbols;
      if (fastSymbols.length === 0) {
        if (state.fastTimer) {
          clearTimeout(state.fastTimer);
          state.fastTimer = null;
        }
      } else {
        state.fastBackoffMs = Math.max(
          REFRESH_FAST_MS,
          Math.min(state.fastBackoffMs, MAX_FAST_BACKOFF_MS)
        );
        state.fastPausedUntil = 0;
        scheduleFastTick(0);
      }
    } else if (fastSymbols.length > 0 && !state.fastTimer) {
      scheduleFastTick(REFRESH_FAST_MS);
    }

    const newSlowSignature = slowSymbols.slice().sort().join('|');
    const currentSlowSignature = slowQueueRef.current.slice().sort().join('|');
    if (newSlowSignature !== currentSlowSignature) {
      slowQueueRef.current = slowSymbols;
      if (!state.slowTimer) {
        scheduleSlowTick();
      }
    } else if (!state.slowTimer && coins.length > 0) {
      logger.info('🔄 No slow timer running, scheduling slow tick');
      scheduleSlowTick();
    } else if (!state.slowTimer && slowSymbols.length > 0) {
      logger.info('🔄 No slow timer running but slow symbols exist, scheduling slow tick');
      scheduleSlowTick();
    }
  }, [coinTradeStatus, coinMembershipSignature, scheduleFastTick, scheduleSlowTick]);

  useEffect(() => {
    return () => {
      const state = schedulerRef.current;
      if (state.fastTimer) {
        clearTimeout(state.fastTimer);
        state.fastTimer = null;
      }
      if (state.slowTimer) {
        clearTimeout(state.slowTimer);
        state.slowTimer = null;
      }
    };
  }, []);

  const removeDuplicates = useCallback((coins: TopCoin[]) => {
    const seen = new Set<string>();
    const cleaned = coins.filter(coin => {
      if (!coin?.instrument_name || typeof coin.instrument_name !== 'string') {
        logger.info('🔄 Skipping coin without instrument_name in removeDuplicates');
        return false;
      }
      const key = coin.instrument_name.toLowerCase();
      if (seen.has(key)) {
        logger.info(`🔄 Removing duplicate: ${coin.instrument_name}`);
        return false;
      }
      seen.add(key);
      return true;
    });
    
    // Also remove coins that are too similar (e.g., BTC_USD and BTC_USDT) for major bases only
    const dedupeByQuoteBases = new Set(['BTC', 'ETH']);
    const finalCoins: TopCoin[] = [];
    for (const coin of cleaned) {
      const [base, quote] = coin.instrument_name.split('_');
      const shouldCheckSimilar = base ? dedupeByQuoteBases.has(base.toUpperCase()) : false;
      const isDuplicate = finalCoins.some(existing => {
        const [existingBase, existingQuote] = existing.instrument_name.split('_');
        if (!shouldCheckSimilar) {
          return false;
        }
        return existingBase === base && 
               (existingQuote === quote || 
                (existingQuote === 'USDT' && quote === 'USD') ||
                (existingQuote === 'USD' && quote === 'USDT'));
      });
      
      if (isDuplicate) {
        logger.info(`🔄 Removing similar coin: ${coin.instrument_name} (similar to existing)`);
      } else {
        finalCoins.push(coin);
      }
    }
    
    logger.info(`✅ Duplicate removal: ${coins.length} → ${finalCoins.length} coins`);
    return finalCoins;
  }, []);

  // Fetch top coins - now supports filtering by Trade YES/NO
  const fetchTopCoins = useCallback(async (preserveLocalChanges = false, filterTradeYes?: boolean) => {
    if (!preserveLocalChanges) {
      setTopCoinsLoading(true);
    }
    try {
      const filterType = filterTradeYes === true ? 'Trade YES' : filterTradeYes === false ? 'Trade NO' : 'ALL';
      logger.info(`🔄 fetchTopCoins called (${filterType}), preserveLocalChanges:`, preserveLocalChanges);
      const data = await getTopCoins();
      logger.info('📊 getTopCoins response:', data);
      let fetchedCoins: TopCoin[] = data.coins || [];
      logger.info('📊 fetchedCoins length (before filter):', fetchedCoins.length);
      logger.info('📊 fetchedCoins symbols (first 10):', fetchedCoins.slice(0, 10).map(c => c.instrument_name));
      
      // Filter coins by Trade YES/NO status if specified
      if (filterTradeYes !== undefined) {
        const filteredCoins = fetchedCoins.filter(coin => {
          const isTradeYes = coinTradeStatus[normalizeSymbolKey(coin.instrument_name)] === true;
          return filterTradeYes ? isTradeYes : !isTradeYes;
        });
        logger.info(`📊 Filtered to ${filterType}: ${filteredCoins.length} coins`);
        fetchedCoins = filteredCoins;
      }
      
      // ALWAYS filter out deleted coins (both on first load and auto-refresh)
      // BUT: Never filter out BTC and ETH (common major coins that shouldn't be permanently hidden)
      try {
        const deletedCoins = localStorage.getItem('deleted_coins');
        if (deletedCoins) {
          const deletedList = JSON.parse(deletedCoins) as string[];
          // Protected coins that should never be filtered out
          const protectedCoins = ['BTC_USDT', 'BTC_USD', 'ETH_USDT', 'ETH_USD', 'BTC', 'ETH'];
          
          // Remove protected coins from deleted list (they shouldn't be permanently hidden)
          const filteredDeletedList = deletedList.filter(coin => {
            const coinUpper = coin.toUpperCase();
            // Check if this deleted coin matches any protected coin exactly or contains it
            return !protectedCoins.some(protectedCoin => {
              const protectedUpper = protectedCoin.toUpperCase();
              // Exact match or coin contains protected coin (e.g., ETH_USDT contains ETH)
              return coinUpper === protectedUpper || coinUpper.includes(protectedUpper);
            });
          });
          
          // If we removed any protected coins, update localStorage
          if (filteredDeletedList.length !== deletedList.length) {
            const removedCoins = deletedList.filter(coin => !filteredDeletedList.includes(coin));
            logger.info('🛡️ Restored protected coins from deleted list:', removedCoins);
            if (filteredDeletedList.length === 0) {
              localStorage.removeItem('deleted_coins');
            } else {
              localStorage.setItem('deleted_coins', JSON.stringify(filteredDeletedList));
            }
          }
          
          // Filter fetched coins, but ALWAYS include protected coins even if they're in deleted list
          logger.info('🗑️ Filtering out deleted coins:', filteredDeletedList);
          const beforeCount = fetchedCoins.length;
          const protectedCoinsSet = new Set(protectedCoins.map(c => c.toUpperCase()));
          const restoredCustomCoins: string[] = [];
          fetchedCoins = fetchedCoins.filter(coin => {
            const coinName = coin.instrument_name.toUpperCase();
            // Never filter out protected coins - check if coin name matches any protected coin
            const isProtected = Array.from(protectedCoinsSet).some(protectedCoin => {
              return coinName === protectedCoin || coinName.includes(protectedCoin) || protectedCoin.includes(coinName.split('_')[0]);
            });
            const isCustom = coin.is_custom === true || ('source' in coin && coin.source === 'custom');
            if (isProtected) {
              logger.info(`🛡️ Keeping protected coin: ${coin.instrument_name}`);
              return true; // Always show protected coins
            }
            // Filter out if it's in the deleted list
            const isDeleted = filteredDeletedList.some(deleted => deleted.toUpperCase() === coinName);
            // FIX: Always show coins returned by backend, even if they're in deleted list (they were explicitly returned by backend)
            // Only filter out if coin is in deleted list AND it's not a custom coin (custom coins are always restored)
            if (isDeleted && isCustom) {
              logger.info(`🧩 Restoring custom coin previously deleted: ${coin.instrument_name}`);
              restoredCustomCoins.push(coin.instrument_name);
              return true;
            }
            // FIX: Show all coins returned by backend by default - don't filter based on deleted list
            // The deleted list is only used for coins that are NOT returned by backend
            return true;
          });
          logger.info(`✅ Filtered fetched coins: ${beforeCount} → ${fetchedCoins.length} (removed ${beforeCount - fetchedCoins.length} deleted coins)`);

          if (restoredCustomCoins.length > 0) {
            const updatedDeletedList = filteredDeletedList.filter(
              coin => !restoredCustomCoins.some(restored => restored.toUpperCase() === coin.toUpperCase())
            );
            if (updatedDeletedList.length === 0) {
              localStorage.removeItem('deleted_coins');
            } else {
              localStorage.setItem('deleted_coins', JSON.stringify(updatedDeletedList));
            }
            logger.info(`🧼 Updated deleted coins list after restoring customs:`, restoredCustomCoins);
          }
        }
      } catch (err) {
        logger.warn('Failed to check deleted coins:', err);
      }
      
      const cleanedCoins = removeDuplicates(fetchedCoins);
      logger.info('🧹 cleanedCoins length:', cleanedCoins.length);
      
      // CRITICAL DEBUG: Check if LDO_USD is in the cleaned coins (silenced - not critical)
      // const ldoInCleaned = cleanedCoins.find(c => c.instrument_name.toUpperCase().includes('LDO'));
      // if (ldoInCleaned) {
      //   logger.info(`✅ LDO found in cleanedCoins: ${ldoInCleaned.instrument_name}`);
      // } else {
      //   logger.warn(`❌ LDO NOT found in cleanedCoins! Total coins: ${cleanedCoins.length}`);
      //   logger.warn(`   First 10 symbols:`, cleanedCoins.slice(0, 10).map(c => c.instrument_name));
      // }
      
      // Debug: Log first few coins' prices
      if (cleanedCoins.length > 0) {
        logger.info('💰 First 3 coins prices:', cleanedCoins.slice(0, 3).map(c => ({
          symbol: c.instrument_name,
          price: c.current_price
        })));
      }
      
      // Determine which symbols to update (only filtered ones, or all if no filter)
      const symbolsToUpdate = filterTradeYes !== undefined 
        ? cleanedCoins.map(c => c.instrument_name)
        : undefined;
      
      // CRITICAL DEBUG: Verify LDO_USD before calling updateTopCoins
      const ldoBeforeUpdate = cleanedCoins.find(c => c.instrument_name.toUpperCase().includes('LDO'));
      logger.info(`🔍 Before updateTopCoins: LDO_USD ${ldoBeforeUpdate ? 'FOUND' : 'NOT FOUND'} in cleanedCoins`);
      
      updateTopCoins(cleanedCoins, symbolsToUpdate);
      logger.info(`✅ updateTopCoins called with ${cleanedCoins.length} coins${symbolsToUpdate ? ` (${symbolsToUpdate.length} filtered)` : ''}`);
      
      // Initialize alert status from backend data to keep frontend and backend in sync
      const buyAlertStatusFromBackend: Record<string, boolean> = {};
      const sellAlertStatusFromBackend: Record<string, boolean> = {};
      cleanedCoins.forEach(coin => {
        if (coin.instrument_name && coin.buy_alert_enabled !== undefined) {
          buyAlertStatusFromBackend[coin.instrument_name] = coin.buy_alert_enabled;
        }
        if (coin.instrument_name && coin.sell_alert_enabled !== undefined) {
          sellAlertStatusFromBackend[coin.instrument_name] = coin.sell_alert_enabled;
        }
      });
      if (Object.keys(buyAlertStatusFromBackend).length > 0) {
        setCoinBuyAlertStatus(prev => ({ ...prev, ...buyAlertStatusFromBackend }));
        logger.info('✅ Initialized buy_alert_enabled from backend:', Object.keys(buyAlertStatusFromBackend).length, 'coins');
      }
      if (Object.keys(sellAlertStatusFromBackend).length > 0) {
        setCoinSellAlertStatus(prev => ({ ...prev, ...sellAlertStatusFromBackend }));
        logger.info('✅ Initialized sell_alert_enabled from backend:', Object.keys(sellAlertStatusFromBackend).length, 'coins');
      }
      
      // CRITICAL DEBUG: Verify LDO_USD after updateTopCoins
      setTimeout(() => {
        const currentCoins = topCoinsRef.current;
        const ldoAfterUpdate = currentCoins.find(c => c.instrument_name.toUpperCase().includes('LDO'));
        logger.info(`🔍 After updateTopCoins: LDO_USD ${ldoAfterUpdate ? 'FOUND' : 'NOT FOUND'} in topCoins (total: ${currentCoins.length})`);
        if (!ldoAfterUpdate && ldoBeforeUpdate) {
          logger.error(`❌ LDO_USD DISAPPEARED after updateTopCoins! This is the bug.`);
        }
      }, 100);
      const fetchedAt = new Date();
      try {
        localStorage.setItem(
          'top_coins_cache',
          JSON.stringify({ coins: cleanedCoins, fetchedAt: fetchedAt.toISOString() })
        );
      } catch (cacheErr) {
        logger.warn('Failed to persist top coins snapshot:', cacheErr);
      }
      setLastTopCoinsFetchAt(fetchedAt);
      setTopCoinsError(null);

      if (preserveLocalChanges) {
        try {
          const localAmounts = localStorage.getItem('watchlist_amounts');
          const localSLPercent = localStorage.getItem('watchlist_sl_percent');
          const localTPPercent = localStorage.getItem('watchlist_tp_percent');
          
          if (localAmounts) {
            const parsedAmounts = JSON.parse(localAmounts);
            setCoinAmounts(prev => ({ ...prev, ...parsedAmounts }));
          }
          if (localSLPercent) {
            const parsedSL = JSON.parse(localSLPercent);
            setCoinSLPercent(prev => ({ ...prev, ...parsedSL }));
          }
          if (localTPPercent) {
            const parsedTP = JSON.parse(localTPPercent);
            setCoinTPPercent(prev => ({ ...prev, ...parsedTP }));
          }
        } catch (err) {
          logger.warn('Failed to preserve watchlist values:', err);
        }
      }
      
      // Only load saved settings if we're not preserving local changes
      if (!preserveLocalChanges) {
        // PRIMARY: Try to load from localStorage (temporary, will be overridden by backend)
        // NOTE: Backend values will take priority when they arrive
        try {
          const localAmounts = localStorage.getItem('watchlist_amounts');
          const localTradeStatus = localStorage.getItem('watchlist_trade_status');
          const localAlertStatus = localStorage.getItem('watchlist_alert_status');
          const localSLPercent = localStorage.getItem('watchlist_sl_percent');
          const localTPPercent = localStorage.getItem('watchlist_tp_percent');
          
          // Load from localStorage as temporary initial state
          // Backend values will override these when they arrive
          // CRITICAL: Clean stale $10 values before loading
          if (localAmounts) {
            const parsedAmounts = JSON.parse(localAmounts) as Record<string, string>;
            // Remove all values that are exactly "10", "10.0", or "10.00" (obsolete defaults)
            const cleanedAmounts: Record<string, string> = {};
            Object.entries(parsedAmounts).forEach(([symbol, value]) => {
              const isStaleValue = value === '10' || value === '10.0' || value === '10.00';
              if (!isStaleValue) {
                cleanedAmounts[symbol] = value;
              }
            });
            
            // Only load cleaned values (non-$10 values)
            if (Object.keys(cleanedAmounts).length > 0) {
              setCoinAmounts(prev => ({
                ...prev,
                ...cleanedAmounts
              }));
            }
          }
          if (localTradeStatus) {
            setCoinTradeStatus(prev => ({
              ...prev,
              ...(JSON.parse(localTradeStatus) as Record<string, boolean>)
            }));
          }
          if (localAlertStatus) {
            setCoinAlertStatus(prev => ({
              ...prev,
              ...(JSON.parse(localAlertStatus) as Record<string, boolean>)
            }));
          }
          if (localSLPercent) {
            setCoinSLPercent(prev => ({
              ...prev,
              ...(JSON.parse(localSLPercent) as Record<string, string>)
            }));
          }
          if (localTPPercent) {
            setCoinTPPercent(prev => ({
              ...prev,
              ...(JSON.parse(localTPPercent) as Record<string, string>)
            }));
          }
          
          logger.info('✅ Loaded watchlist settings from localStorage');
        } catch (err) {
          logger.warn('Failed to load from localStorage:', err);
        }
        
        // SECONDARY: Always load from backend database and update localStorage
        // SIMPLIFIED APPROACH: Backend updates localStorage, dashboard only reads from localStorage
        try {
          // Always load from backend to get the latest saved values
          const dashboardItems: WatchlistItem[] = await getDashboard();
            // Store watchlist items for TP/SL counting
            setWatchlistItems(dashboardItems);
            
            // Build clean data structures from backend (source of truth)
            const backendAmounts: { [key: string]: string } = {};
            const backendTradeStatus: { [key: string]: boolean } = {};
            const backendMarginStatus: { [key: string]: boolean } = {};
            const backendSlTpStatus: { [key: string]: boolean } = {};
            const backendSLPercent: { [key: string]: string } = {};
            const backendTPPercent: { [key: string]: string } = {};
            const backendSLPrices: { [key: string]: number } = {};
            const backendTPPrices: { [key: string]: number } = {};
            const backendAlertStatus: { [key: string]: boolean } = {};
            const backendBuyAlertStatus: { [key: string]: boolean } = {};
            const backendSellAlertStatus: { [key: string]: boolean } = {};
            
            // Get all backend symbols to know which ones are managed by backend
            const backendSymbols = new Set(
              dashboardItems
                .map(item => item.symbol?.toUpperCase())
                .filter(Boolean) as string[]
            );
            
            dashboardItems.forEach(item => {
              if (item.symbol) {
                const symbolUpper = item.symbol?.toUpperCase();
                // Only save non-null values from backend
                if (item.trade_amount_usd !== undefined && item.trade_amount_usd !== null) {
                  backendAmounts[symbolUpper] = item.trade_amount_usd.toString();
                }
                if (item.sl_percentage !== undefined && item.sl_percentage !== null) {
                  backendSLPercent[symbolUpper] = item.sl_percentage.toString();
                }
                if (item.tp_percentage !== undefined && item.tp_percentage !== null) {
                  backendTPPercent[symbolUpper] = item.tp_percentage.toString();
                }
                if (item.trade_enabled !== undefined && item.trade_enabled !== null) {
                  backendTradeStatus[symbolUpper] = item.trade_enabled;
                }
                if (item.alert_enabled !== undefined && item.alert_enabled !== null) {
                  backendAlertStatus[symbolUpper] = item.alert_enabled;
                }
                if (item.buy_alert_enabled !== undefined && item.buy_alert_enabled !== null) {
                  backendBuyAlertStatus[symbolUpper] = item.buy_alert_enabled;
                }
                if (item.sell_alert_enabled !== undefined && item.sell_alert_enabled !== null) {
                  backendSellAlertStatus[symbolUpper] = item.sell_alert_enabled;
                }
                if (item.trade_on_margin !== undefined && item.trade_on_margin !== null) {
                  backendMarginStatus[symbolUpper] = item.trade_on_margin;
                }
              }
            });

            // Set trade status from backend (after processing all items)
            if (Object.keys(backendTradeStatus).length > 0) {
              setCoinTradeStatus(prev => {
                const updated = { ...prev, ...backendTradeStatus };
                logger.info('✅ Initialized trade_enabled from backend:', Object.keys(backendTradeStatus).length, 'coins');
                logger.info('📊 Backend trade status keys:', Object.keys(backendTradeStatus));
                logger.info('📊 Sample trade status values:', Object.entries(backendTradeStatus).slice(0, 5));
                // Debug: Check LTC specifically
                if (backendTradeStatus['LTC_USDT'] !== undefined || backendTradeStatus['LTC'] !== undefined) {
                  logger.info('🔍 LTC trade status from backend:', {
                    'LTC_USDT': backendTradeStatus['LTC_USDT'],
                    'LTC': backendTradeStatus['LTC'],
                    'All LTC keys': Object.keys(backendTradeStatus).filter(k => k.includes('LTC'))
                  });
                }
                return updated;
              });
            }

            // Set margin status from backend (after processing all items)
            if (Object.keys(backendMarginStatus).length > 0) {
              setCoinMarginStatus(prev => ({ ...prev, ...backendMarginStatus }));
              logger.info('✅ Initialized trade_on_margin from backend:', Object.keys(backendMarginStatus).length, 'coins');
            }

            // Set amounts from backend (after processing all items)
            // Don't overwrite recently saved values (within last 5 seconds) to prevent race conditions
            if (Object.keys(backendAmounts).length > 0) {
              const now = Date.now();
              const filteredBackendAmounts: Record<string, string> = {};
              Object.entries(backendAmounts).forEach(([symbol, value]) => {
                const lastSaved = recentlySavedAmounts.current[symbol];
                // Only use backend value if it wasn't recently saved (within 5 seconds)
                if (!lastSaved || (now - lastSaved) > 5000) {
                  filteredBackendAmounts[symbol] = value;
                } else {
                  logger.debug(`Skipping backend amount for ${symbol} (saved ${now - lastSaved}ms ago)`);
                }
              });
              if (Object.keys(filteredBackendAmounts).length > 0) {
                // CRITICAL: Backend is source of truth - always overwrite localStorage values
                // Use functional update to ensure we're using the latest backend values
                setCoinAmounts(prev => {
                  const updated = { ...prev, ...filteredBackendAmounts };
                  // Log specific values for debugging
                  if (filteredBackendAmounts['LTC_USDT']) {
                    logger.info(`🔍 LTC_USDT amount from backend: ${filteredBackendAmounts['LTC_USDT']}, overwriting localStorage value`);
                  }
                  return updated;
                });
                logger.info('✅ Initialized trade_amount_usd from backend:', Object.keys(filteredBackendAmounts).length, 'coins');
                // Update localStorage with backend values to keep them in sync
                try {
                  const currentAmounts = JSON.parse(localStorage.getItem('watchlist_amounts') || '{}');
                  const updatedAmounts = { ...currentAmounts, ...filteredBackendAmounts };
                  localStorage.setItem('watchlist_amounts', JSON.stringify(updatedAmounts));
                  logger.info('✅ Updated localStorage with backend amounts');
                } catch (err) {
                  logger.warn('Failed to update localStorage with backend amounts:', err);
                }
              }
            }

            // Set SL/TP percentages from backend (after processing all items)
            if (Object.keys(backendSLPercent).length > 0) {
              setCoinSLPercent(prev => ({ ...prev, ...backendSLPercent }));
              logger.info('✅ Initialized sl_percentage from backend:', Object.keys(backendSLPercent).length, 'coins');
            }
            if (Object.keys(backendTPPercent).length > 0) {
              setCoinTPPercent(prev => ({ ...prev, ...backendTPPercent }));
              logger.info('✅ Initialized tp_percentage from backend:', Object.keys(backendTPPercent).length, 'coins');
            }
          } catch (err) {
            logger.warn('Failed to load from backend:', err);
          }
        }
      } catch (err) {
        logger.error('Error in fetchTopCoins:', err);
        setTopCoinsError(err instanceof Error ? err.message : 'Failed to fetch top coins');
      } finally {
        if (!preserveLocalChanges) {
          setTopCoinsLoading(false);
        }
      }
    }, [coinTradeStatus]);

  // Set refs for functions to avoid circular dependencies
  useEffect(() => {
    fetchPortfolioRef.current = fetchPortfolio;
    fetchTopCoinsRef.current = fetchTopCoins;
  }, [fetchPortfolio, fetchTopCoins]);

  // Load trading config and initialize coin presets
  useEffect(() => {
    const loadTradingConfig = async () => {
      try {
        const config = await getTradingConfig();
        if (config) {
          setTradingConfig(config);
          // Extract coin presets from trading config
          if (config.coins) {
            const presets: Record<string, string> = {};
            Object.entries(config.coins).forEach(([symbol, coinConfig]) => {
              if (coinConfig.preset) {
                presets[normalizeSymbolKey(symbol)] = coinConfig.preset;
              }
            });
            setCoinPresets(presets);
            logger.info('✅ Loaded trading config and coin presets:', Object.keys(presets).length, 'coins');
          }
        }
      } catch (err) {
        logger.warn('Failed to load trading config:', err);
      }
    };
    loadTradingConfig();
  }, []);

  // Initial data load on mount
  useEffect(() => {
    // Load initial data
    fetchPortfolio({ showLoader: true });
    fetchTopCoins(false);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Load expected TP data when tab is selected
  useEffect(() => {
    if (activeTab === 'expected-take-profit') {
      // Use a ref to track if we're already loading to prevent duplicate requests
      let isMounted = true;
      let isLoading = false;
      
      const loadExpectedTP = async () => {
        // Prevent duplicate concurrent requests
        if (isLoading) {
          return;
        }
        isLoading = true;
        
        setExpectedTPLoading(true);
        try {
          logger.info('Loading expected take profit summary...');
          const summary = await getExpectedTakeProfitSummary();
          logger.info('Expected take profit summary loaded:', summary);
          if (isMounted) {
            setExpectedTPSummary(summary.summary || []);
            setExpectedTPLastUpdate(new Date());
          }
        } catch (err) {
          logger.error('Failed to fetch expected take profit summary:', err);
          // Set empty array on error so UI doesn't stay in loading state
          if (isMounted) {
            setExpectedTPSummary([]);
          }
        } finally {
          isLoading = false;
          if (isMounted) {
            setExpectedTPLoading(false);
          }
        }
      };
      
      loadExpectedTP();
      
      return () => {
        isMounted = false;
      };
    }
  }, [activeTab]); // eslint-disable-line react-hooks/exhaustive-deps

  // Handler for saving strategy configuration
  const handleSaveStrategyConfig = useCallback(async (preset: Preset, riskMode: RiskMode, updatedRules: StrategyRules) => {
    try {
      // Update local state first (optimistic update)
      setPresetsConfig(prev => ({
        ...prev,
        [preset]: {
          ...prev[preset],
          rules: {
            ...prev[preset].rules,
            [riskMode]: updatedRules
          }
        }
      }));
      
      logger.info(`Strategy config saved for ${preset} - ${riskMode}`, updatedRules);
      
      // Save to backend - convert PresetConfig format to backend strategy_rules format
      try {
        // Get current trading config to preserve other settings
        const currentConfig = await getTradingConfig() || {};
        
        // Convert preset name to lowercase (backend expects "swing", not "Swing")
        const presetLower = preset.toLowerCase();
        
        // Build strategy_rules structure matching backend format
        const strategyRules: Record<string, any> = currentConfig.strategy_rules || {};
        
        // Get notification profile from current preset config
        const currentPresetConfig = presetsConfig[preset] || PRESET_CONFIG[preset];
        const notificationProfile = currentPresetConfig?.notificationProfile || presetLower;
        
        // Update or create preset entry
        if (!strategyRules[presetLower]) {
          strategyRules[presetLower] = {
            notificationProfile: notificationProfile,
            rules: {}
          };
        }
        
        // Update the specific risk mode rules
        strategyRules[presetLower].rules[riskMode] = updatedRules;
        
        // Build the config payload
        const configPayload: TradingConfig = {
          ...currentConfig,
          strategy_rules: strategyRules
        };
        
        // Save to backend
        const result = await saveTradingConfig(configPayload);
        
        if (result.ok) {
          logger.info(`✅ Strategy config saved to backend for ${preset} - ${riskMode}`);
          
          // Update local state with backend response if available
          if (result.config) {
            // Reload config to ensure sync
            const updatedConfig = await getTradingConfig();
            if (updatedConfig) {
              setTradingConfig(updatedConfig);
            }
          }
        } else {
          logger.warn('Backend save returned ok=false');
        }
      } catch (backendError) {
        // Log error but don't fail the UI update (optimistic update already applied)
        logger.error('Failed to save strategy config to backend:', backendError);
        // Show user-friendly error message
        throw new Error('Failed to save to backend. Local changes saved, but may not persist after reload.');
      }
    } catch (error) {
      logger.error('Failed to save strategy config:', error);
      throw error;
    }
  }, [presetsConfig]);

  // Get current rules for the selected preset and risk mode
  const currentRules = presetsConfig[selectedConfigPreset]?.rules[selectedConfigRisk] || PRESET_CONFIG[selectedConfigPreset].rules[selectedConfigRisk];

  // Tab navigation configuration
  const tabs: { id: Tab; label: string }[] = [
    { id: 'portfolio', label: 'Portfolio' },
    { id: 'watchlist', label: 'Watchlist' },
    { id: 'signals', label: 'Signals' },
    { id: 'orders', label: 'Orders' },
    { id: 'expected-take-profit', label: 'Expected TP' },
    { id: 'executed-orders', label: 'Executed Orders' },
    { id: 'monitoring', label: 'Monitoring' },
    { id: 'version-history', label: 'Version History' },
  ];

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-slate-900">
      <div className="container mx-auto p-4">
        {/* Header */}
        <div className="mb-4 flex justify-between items-center">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Trading Dashboard</h1>
          <button
            onClick={() => setShowSignalConfig(true)}
            className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors"
          >
            ⚙️ Configure Strategy
          </button>
        </div>

        <MissingSecretsBanner />

        {/* System Health Panel */}
        <ErrorBoundary fallback={<div className="mb-4 p-4 bg-yellow-50 border border-yellow-200 rounded text-yellow-700 text-sm">System Health panel unavailable</div>}>
          <SystemHealthPanel className="mb-4" />
        </ErrorBoundary>

        {/* Tab Navigation Menu */}
        <div className="mb-6 border-b border-gray-200 dark:border-gray-700">
          <nav className="flex flex-wrap gap-2 -mb-px">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`
                  px-4 py-2 text-sm font-medium transition-colors
                  ${
                    activeTab === tab.id
                      ? 'border-b-2 border-blue-600 text-blue-600 dark:text-blue-400'
                      : 'text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
                  }
                `}
              >
                {tab.label}
                {tab.id === 'monitoring' && unreadMonitoringCount > 0 && (
                  <span className="ml-2 px-2 py-0.5 text-xs bg-red-500 text-white rounded-full">
                    {unreadMonitoringCount}
                  </span>
                )}
              </button>
            ))}
          </nav>
        </div>

        {/* Tab Content */}
        <ErrorBoundary>
          {activeTab === 'portfolio' && (
            <PortfolioTab
              portfolio={portfolio}
              portfolioLoading={portfolioLoading}
              portfolioError={portfolioError}
              totalBorrowed={totalBorrowed}
              snapshotLastUpdated={snapshotLastUpdated}
              snapshotStale={snapshotStale}
              snapshotStaleSeconds={snapshotStaleSeconds}
              botStatus={botStatus}
              togglingLiveTrading={togglingLiveTrading}
              isUpdating={isUpdating}
              topCoinsLoading={topCoinsLoading}
              onToggleLiveTrading={async () => {
                setTogglingLiveTrading(true);
                try {
                  await toggleLiveTrading(!botStatus?.live_trading_enabled);
                  // Refresh portfolio to get updated bot status
                  await fetchPortfolio({ showLoader: false, backgroundRefresh: true });
                } catch (err) {
                  logger.error('Failed to toggle live trading:', err);
                } finally {
                  setTogglingLiveTrading(false);
                }
              }}
              onRefreshPortfolio={() => fetchPortfolio({ showLoader: true, forceRefresh: true })}
            />
          )}

          {activeTab === 'watchlist' && (
            <WatchlistTab
              botStatus={botStatus}
              togglingLiveTrading={togglingLiveTrading}
              isUpdating={isUpdating}
              topCoinsLoading={topCoinsLoading}
              portfolioLoading={portfolioLoading}
              dataSourceStatus={dataSourceStatus ? Object.fromEntries(
                Object.entries(dataSourceStatus).map(([key, value]) => [
                  key,
                  {
                    available: value.available,
                    priority: value.priority,
                    response_time: value.response_time,
                    last_check: value.last_check
                  }
                ])
              ) : null}
              fastQueueRateLimited={false}
              onToggleLiveTrading={async () => {
                setTogglingLiveTrading(true);
                try {
                  await toggleLiveTrading(!botStatus?.live_trading_enabled);
                  await fetchPortfolio({ showLoader: false, backgroundRefresh: true });
                } catch (err) {
                  logger.error('Failed to toggle live trading:', err);
                } finally {
                  setTogglingLiveTrading(false);
                }
              }}
              topCoins={topCoins}
              signals={signals}
              coinTradeStatus={coinTradeStatus}
              coinMarginStatus={coinMarginStatus}
              coinAmounts={coinAmounts}
              coinSLPercent={coinSLPercent}
              coinTPPercent={coinTPPercent}
              coinBuyAlertStatus={coinBuyAlertStatus}
              coinSellAlertStatus={coinSellAlertStatus}
              coinAlertStatus={coinAlertStatus}
              watchlistFilter={watchlistFilter}
              onWatchlistFilterChange={setWatchlistFilter}
              tradingConfig={tradingConfig}
              coinPresets={coinPresets}
              onCoinPresetChange={async (symbol: string, preset: string) => {
                const symbolKey = normalizeSymbolKey(symbol);
                setCoinPresets(prev => ({ ...prev, [symbolKey]: preset }));
                try {
                  await updateCoinConfig(symbol, { preset });
                  logger.info(`✅ Strategy updated for ${symbol}: ${preset}`);
                } catch (err) {
                  logger.error(`Failed to update strategy for ${symbol}:`, err);
                }
              }}
              onAmountSaved={(symbol) => {
                // Mark amount as recently saved to prevent overwriting with stale backend data
                recentlySavedAmounts.current[symbol] = Date.now();
              }}
              onCoinUpdated={(symbol, updates) => {
                // Update the coin in topCoins array immediately after mutation
                updateSingleCoin(symbol, updates);
                
                const symbolKey = normalizeSymbolKey(symbol);
                
                // Update trade_enabled state if provided
                if (updates.trade_enabled !== undefined) {
                  setCoinTradeStatus(prev => ({ ...prev, [symbolKey]: updates.trade_enabled! }));
                }
                
                // Update trade_on_margin state if provided
                if (updates.trade_on_margin !== undefined) {
                  setCoinMarginStatus(prev => ({ ...prev, [symbolKey]: updates.trade_on_margin! }));
                }
                
                // Update alert states if provided
                if (updates.alert_enabled !== undefined) {
                  setCoinAlertStatus(prev => ({ ...prev, [symbolKey]: updates.alert_enabled! }));
                }
                if (updates.buy_alert_enabled !== undefined) {
                  setCoinBuyAlertStatus(prev => ({ ...prev, [symbolKey]: updates.buy_alert_enabled! }));
                }
                if (updates.sell_alert_enabled !== undefined) {
                  setCoinSellAlertStatus(prev => ({ ...prev, [symbolKey]: updates.sell_alert_enabled! }));
                }
                
                // Also update SL/TP percentage state if provided in updates
                if (updates.sl_percentage !== undefined) {
                  setCoinSLPercent(prev => {
                    const updated = { ...prev };
                    if (updates.sl_percentage === null || updates.sl_percentage === undefined) {
                      delete updated[symbolKey];
                    } else {
                      updated[symbolKey] = updates.sl_percentage.toString();
                    }
                    return updated;
                  });
                }
                if (updates.tp_percentage !== undefined) {
                  setCoinTPPercent(prev => {
                    const updated = { ...prev };
                    if (updates.tp_percentage === null || updates.tp_percentage === undefined) {
                      delete updated[symbolKey];
                    } else {
                      updated[symbolKey] = updates.tp_percentage.toString();
                    }
                    return updated;
                  });
                }
              }}
            />
          )}

          {activeTab === 'signals' && (
            <div className="space-y-6">
              {/* Header Section */}
              <div className="flex justify-between items-center mb-4">
                <h2 className="text-xl font-semibold text-gray-900 dark:text-white">Signal Configuration</h2>
                <button
                  onClick={() => setShowSignalConfig(true)}
                  className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors flex items-center gap-2"
                >
                  <span>⚙️</span>
                  <span>Configure Strategy</span>
                </button>
              </div>

              {/* Preset and Risk Mode Selectors */}
              <div className="bg-white dark:bg-slate-800 rounded-lg shadow p-6">
                <h3 className="text-lg font-semibold mb-4 text-gray-900 dark:text-white">Current Strategy</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                      Preset
                    </label>
                    <select
                      value={selectedConfigPreset}
                      onChange={(e) => setSelectedConfigPreset(e.target.value as Preset)}
                      aria-label="Strategy preset selection"
                      className="w-full px-3 py-2 border border-gray-300 rounded-md dark:bg-slate-700 dark:border-slate-600 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                    >
                      <option value="Swing">Swing</option>
                      <option value="Intraday">Intraday</option>
                      <option value="Scalp">Scalp</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                      Risk Mode
                    </label>
                    <select
                      value={selectedConfigRisk}
                      onChange={(e) => setSelectedConfigRisk(e.target.value as RiskMode)}
                      aria-label="Risk mode selection"
                      className="w-full px-3 py-2 border border-gray-300 rounded-md dark:bg-slate-700 dark:border-slate-600 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                    >
                      <option value="Conservative">Conservative</option>
                      <option value="Aggressive">Aggressive</option>
                    </select>
                  </div>
                </div>
              </div>

              {/* Configuration Summary */}
              <div className="bg-white dark:bg-slate-800 rounded-lg shadow p-6">
                <h3 className="text-lg font-semibold mb-4 text-gray-900 dark:text-white">Configuration Summary</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {/* RSI Settings */}
                  <div className="border-l-4 border-blue-500 pl-4">
                    <h4 className="font-medium text-gray-700 dark:text-gray-300 mb-2">RSI Thresholds</h4>
                    <div className="space-y-1 text-sm">
                      <div className="text-gray-600 dark:text-gray-400">
                        Buy Below: <span className="font-semibold text-gray-900 dark:text-white">{currentRules.rsi?.buyBelow ?? 'N/A'}</span>
                      </div>
                      <div className="text-gray-600 dark:text-gray-400">
                        Sell Above: <span className="font-semibold text-gray-900 dark:text-white">{currentRules.rsi?.sellAbove ?? 'N/A'}</span>
                      </div>
                    </div>
                  </div>

                  {/* Volume Settings */}
                  <div className="border-l-4 border-green-500 pl-4">
                    <h4 className="font-medium text-gray-700 dark:text-gray-300 mb-2">Volume & Price</h4>
                    <div className="space-y-1 text-sm">
                      <div className="text-gray-600 dark:text-gray-400">
                        Min Volume Ratio: <span className="font-semibold text-gray-900 dark:text-white">{currentRules.volumeMinRatio ?? 'N/A'}x</span>
                      </div>
                      <div className="text-gray-600 dark:text-gray-400">
                        Min Price Change: <span className="font-semibold text-gray-900 dark:text-white">{currentRules.minPriceChangePct ?? 'N/A'}%</span>
                      </div>
                    </div>
                  </div>

                  {/* SL/TP Settings */}
                  <div className="border-l-4 border-red-500 pl-4">
                    <h4 className="font-medium text-gray-700 dark:text-gray-300 mb-2">Stop Loss / Take Profit</h4>
                    <div className="space-y-1 text-sm">
                      <div className="text-gray-600 dark:text-gray-400">
                        SL Fallback: <span className="font-semibold text-gray-900 dark:text-white">{currentRules.sl?.fallbackPct ?? 'N/A'}%</span>
                      </div>
                      <div className="text-gray-600 dark:text-gray-400">
                        Risk:Reward: <span className="font-semibold text-gray-900 dark:text-white">{currentRules.tp?.rr ?? 'N/A'}</span>
                      </div>
                    </div>
                  </div>

                  {/* ATR Settings */}
                  {currentRules.atr && (
                    <div className="border-l-4 border-purple-500 pl-4">
                      <h4 className="font-medium text-gray-700 dark:text-gray-300 mb-2">ATR Configuration</h4>
                      <div className="space-y-1 text-sm">
                        <div className="text-gray-600 dark:text-gray-400">
                          Period: <span className="font-semibold text-gray-900 dark:text-white">{currentRules.atr.period ?? 'N/A'}</span>
                        </div>
                        <div className="text-gray-600 dark:text-gray-400">
                          SL Multiplier: <span className="font-semibold text-gray-900 dark:text-white">{currentRules.atr.multiplier_sl ?? 'N/A'}</span>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Moving Averages */}
                  <div className="border-l-4 border-yellow-500 pl-4">
                    <h4 className="font-medium text-gray-700 dark:text-gray-300 mb-2">Moving Averages</h4>
                    <div className="space-y-1 text-sm">
                      <div className="text-gray-600 dark:text-gray-400">
                        EMA10: <span className={`font-semibold ${currentRules.maChecks?.ema10 ? 'text-green-600 dark:text-green-400' : 'text-gray-400'}`}>
                          {currentRules.maChecks?.ema10 ? '✓ Enabled' : '✗ Disabled'}
                        </span>
                      </div>
                      <div className="text-gray-600 dark:text-gray-400">
                        MA50: <span className={`font-semibold ${currentRules.maChecks?.ma50 ? 'text-green-600 dark:text-green-400' : 'text-gray-400'}`}>
                          {currentRules.maChecks?.ma50 ? '✓ Enabled' : '✗ Disabled'}
                        </span>
                      </div>
                      <div className="text-gray-600 dark:text-gray-400">
                        MA200: <span className={`font-semibold ${currentRules.maChecks?.ma200 ? 'text-green-600 dark:text-green-400' : 'text-gray-400'}`}>
                          {currentRules.maChecks?.ma200 ? '✓ Enabled' : '✗ Disabled'}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Trend Filters */}
                  {currentRules.trendFilters && (
                    <div className="border-l-4 border-indigo-500 pl-4">
                      <h4 className="font-medium text-gray-700 dark:text-gray-300 mb-2">Trend Filters</h4>
                      <div className="space-y-1 text-sm">
                        <div className="text-gray-600 dark:text-gray-400">
                          Price above MA200: <span className={`font-semibold ${currentRules.trendFilters.require_price_above_ma200 ? 'text-green-600 dark:text-green-400' : 'text-gray-400'}`}>
                            {currentRules.trendFilters.require_price_above_ma200 ? '✓ Required' : '✗ Optional'}
                          </span>
                        </div>
                        <div className="text-gray-600 dark:text-gray-400">
                          EMA10 above MA50: <span className={`font-semibold ${currentRules.trendFilters.require_ema10_above_ma50 ? 'text-green-600 dark:text-green-400' : 'text-gray-400'}`}>
                            {currentRules.trendFilters.require_ema10_above_ma50 ? '✓ Required' : '✗ Optional'}
                          </span>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* Active Signals */}
              <div className="bg-white dark:bg-slate-800 rounded-lg shadow p-6">
                <h3 className="text-lg font-semibold mb-4 text-gray-900 dark:text-white">Active Signals</h3>
                {topCoins.length === 0 ? (
                  <p className="text-gray-500 dark:text-gray-400 text-center py-8">No coins available</p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                      <thead className="bg-gray-50 dark:bg-slate-700">
                        <tr>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">Symbol</th>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">Signal</th>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">Price</th>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">RSI</th>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">TP</th>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">SL</th>
                        </tr>
                      </thead>
                      <tbody className="bg-white dark:bg-slate-800 divide-y divide-gray-200 dark:divide-gray-700">
                        {(() => {
                          const activeSignals = topCoins
                            .map(coin => {
                              const signal = signals[coin.instrument_name];
                              if (!signal || (!signal.signals?.buy && !signal.signals?.sell)) {
                                return null;
                              }
                              return { coin, signal };
                            })
                            .filter((item): item is { coin: TopCoin; signal: TradingSignals } => item !== null)
                            .slice(0, 20);
                          
                          if (activeSignals.length === 0) {
                            return (
                              <tr>
                                <td colSpan={6} className="px-4 py-8 text-center text-gray-500 dark:text-gray-400">
                                  No active signals at the moment
                                </td>
                              </tr>
                            );
                          }
                          
                          return activeSignals.map(({ coin, signal }) => {
                            const currentPrice = coin.current_price || signal.price || 0;
                            const rsi = signal.rsi ?? coin.rsi ?? null;
                            const tpPrice = signal.signals?.tp ?? null;
                            const slPrice = signal.signals?.sl ?? null;
                            const signalType = signal.signals?.buy ? 'BUY' : signal.signals?.sell ? 'SELL' : 'NEUTRAL';
                            
                            return (
                              <tr key={coin.instrument_name} className="hover:bg-gray-50 dark:hover:bg-slate-700">
                                <td className="px-4 py-3 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-white">
                                  {coin.instrument_name}
                                </td>
                                <td className="px-4 py-3 whitespace-nowrap">
                                  {signalType === 'BUY' ? (
                                    <span className="px-2 py-1 text-xs font-semibold rounded-full bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200">
                                      BUY
                                    </span>
                                  ) : signalType === 'SELL' ? (
                                    <span className="px-2 py-1 text-xs font-semibold rounded-full bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200">
                                      SELL
                                    </span>
                                  ) : (
                                    <span className="px-2 py-1 text-xs font-semibold rounded-full bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300">
                                      NEUTRAL
                                    </span>
                                  )}
                                </td>
                                <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-900 dark:text-white">
                                  ${formatNumber(currentPrice, coin.instrument_name)}
                                </td>
                                <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-900 dark:text-white">
                                  {rsi !== null ? rsi.toFixed(2) : 'N/A'}
                                </td>
                                <td className="px-4 py-3 whitespace-nowrap text-sm text-green-600 dark:text-green-400">
                                  {tpPrice !== null ? `$${formatNumber(tpPrice, coin.instrument_name)}` : 'N/A'}
                                </td>
                                <td className="px-4 py-3 whitespace-nowrap text-sm text-red-600 dark:text-red-400">
                                  {slPrice !== null ? `$${formatNumber(slPrice, coin.instrument_name)}` : 'N/A'}
                                </td>
                              </tr>
                            );
                          });
                        })()}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          )}

          {activeTab === 'orders' && (
            <OrdersTab
              botStatus={botStatus}
              togglingLiveTrading={togglingLiveTrading}
              isUpdating={isUpdating}
              topCoinsLoading={topCoinsLoading}
              portfolioLoading={portfolioLoading}
              hideCancelledOpenOrders={hideCancelledOpenOrders}
              onToggleLiveTrading={async () => {
                setTogglingLiveTrading(true);
                try {
                  await toggleLiveTrading(!botStatus?.live_trading_enabled);
                  await fetchPortfolio({ showLoader: false, backgroundRefresh: true });
                } catch (err) {
                  logger.error('Failed to toggle live trading:', err);
                } finally {
                  setTogglingLiveTrading(false);
                }
              }}
              onToggleHideCancelled={setHideCancelledOpenOrders}
            />
          )}

          {activeTab === 'expected-take-profit' && (
            <ExpectedTakeProfitTab
              expectedTPSummary={expectedTPSummary}
              expectedTPLoading={expectedTPLoading}
              expectedTPLastUpdate={expectedTPLastUpdate}
              expectedTPDetails={expectedTPDetails}
              expectedTPDetailsLoading={expectedTPDetailsLoading}
              expectedTPDetailsSymbol={expectedTPDetailsSymbol}
              showExpectedTPDetailsDialog={showExpectedTPDetailsDialog}
              onFetchExpectedTakeProfitSummary={async () => {
                setExpectedTPLoading(true);
                try {
                  const summary = await getExpectedTakeProfitSummary();
                  setExpectedTPSummary(summary.summary || []);
                  setExpectedTPLastUpdate(new Date());
                } catch (err) {
                  logger.error('Failed to fetch expected take profit summary:', err);
                } finally {
                  setExpectedTPLoading(false);
                }
              }}
              onFetchExpectedTakeProfitDetails={async (symbol: string) => {
                setExpectedTPDetailsLoading(true);
                setExpectedTPDetailsSymbol(symbol);
                try {
                  const details = await getExpectedTakeProfitDetails(symbol);
                  setExpectedTPDetails(details);
                  setShowExpectedTPDetailsDialog(true);
                } catch (err) {
                  logger.error('Failed to fetch expected take profit details:', err);
                } finally {
                  setExpectedTPDetailsLoading(false);
                }
              }}
              onCloseDetailsDialog={() => setShowExpectedTPDetailsDialog(false)}
            />
          )}

          {activeTab === 'executed-orders' && (
            <ExecutedOrdersTab
              orderFilter={orderFilter}
              hideCancelled={hideCancelled}
              onFilterChange={setOrderFilter}
              onToggleHideCancelled={setHideCancelled}
            />
          )}

          {activeTab === 'monitoring' && (
            <div>
              <h2 className="text-xl font-semibold mb-4">Monitoring</h2>
              <MonitoringPanel 
                telegramMessages={telegramMessages}
                telegramMessagesLoading={telegramMessagesLoading}
                onRequestTelegramRefresh={fetchTelegramMessages}
              />
            </div>
          )}

          {activeTab === 'version-history' && (
            <div>
              <h2 className="text-xl font-semibold mb-4">Version History</h2>
              <div className="space-y-4">
                {VERSION_HISTORY.map((version, index) => (
                  <div key={index} className="border-b border-gray-200 dark:border-gray-700 pb-4">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="font-semibold text-lg">{version.version}</span>
                      <span className="text-sm text-gray-500">{version.date}</span>
                    </div>
                    <p className="font-medium mb-1">{version.change}</p>
                    <div className="text-sm text-gray-600 dark:text-gray-400 whitespace-pre-line">
                      {version.details}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </ErrorBoundary>
      </div>

      {/* Strategy Configuration Modal */}
      <StrategyConfigModal
        isOpen={showSignalConfig}
        onClose={() => setShowSignalConfig(false)}
        preset={selectedConfigPreset}
        riskMode={selectedConfigRisk}
        rules={currentRules}
        onSave={handleSaveStrategyConfig}
      />
    </div>
  );
}
