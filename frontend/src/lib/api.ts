import { getApiUrl } from './environment';

const DEFAULT_API_URL = getApiUrl();

// Types
export interface WatchlistItem {
  id: number;
  symbol: string;
  exchange: string;
  buy_target?: number;
  take_profit?: number;
  stop_loss?: number;
  notes?: string;
  trade_enabled?: boolean;
  trade_amount_usd?: number;
  trade_on_margin?: boolean;
  alert_enabled?: boolean;  // Master switch: Enable automatic alerts and order creation
  buy_alert_enabled?: boolean;  // Enable BUY alerts specifically
  sell_alert_enabled?: boolean;  // Enable SELL alerts specifically
  sl_tp_mode?: string;
  min_price_change_pct?: number | null;
  alert_cooldown_minutes?: number | null;
  sl_percentage?: number | null;
  tp_percentage?: number | null;
  sl_price?: number;
  tp_price?: number;
  order_status?: string;
  price?: number;
  rsi?: number;
  signals?: TradingSignals;
  // Backend fields (may be present in API responses)
  is_deleted?: boolean;
  updated_at?: string;
  created_at?: string;
  // Strategy fields (resolved from trading_config.json + sl_tp_mode)
  strategy_preset?: string | null;  // "swing", "intraday", "scalp"
  strategy_risk?: string | null;    // "conservative", "aggressive"
  strategy_key?: string | null;     // "swing-conservative" (canonical identifier)
}

export interface WatchlistInput {
  symbol: string;
  exchange: string;
  buy_target?: number;
  take_profit?: number;
  stop_loss?: number;
  trade_enabled?: boolean;
  trade_amount_usd?: number;
  trade_on_margin?: boolean;
  sl_tp_mode?: string;
  sl_percentage?: number | null;
  tp_percentage?: number | null;
  min_price_change_pct?: number | null;
  alert_cooldown_minutes?: number | null;
  notes?: string;
}

export interface AccountSummary {
  balance: number;
  available: number;
  currency: string;
}

export type OpenOrder = {
  order_id: string;
  instrument_name: string;
  side: string;
  order_type: string;
  quantity: string;
  price: string;
  status: string;
  order_role?: string | null; // STOP_LOSS, TAKE_PROFIT, etc.
  create_time: number;
  update_time: number;
  imported_at?: number | null; // Timestamp when order was imported from CSV
  cumulative_quantity?: string | null;
  cumulative_value?: string | null;
  avg_price?: string | null;
  trigger_condition?: string | null; // Trigger condition for stop/limit orders
  filled_quantity?: string | null; // Filled quantity for executed orders
  filled_price?: string | null; // Filled price for executed orders
}

// Open Orders Summary Types (for new "Open Orders" tab)
export interface OpenOrderDetail {
  orderId: string;
  side: 'BUY' | 'SELL';
  quantity: number;
  price: number | null;
  createdAt: string;
  hasTakeProfit: boolean;
  hasStopLoss: boolean;
  linkedTakeProfitOrderId?: string;
  linkedStopLossOrderId?: string;
}

export interface OpenOrdersBySymbol {
  symbol: string;
  positionQuantity: number;
  totalOpenQuantity: number;
  openOrders: OpenOrderDetail[];
}

// Open Position structure (BUY-based)
export interface OpenPosition {
  symbol: string;
  baseOrderId: string;
  baseSide: 'BUY' | 'SELL';  // Must be 'BUY'
  baseQuantity: number;
  basePrice: number | null;
  baseTotal: number | null;
  baseCreatedAt: string;
  netOpenQuantity: number;
  positionQuantity: number;
  tpCount: number;
  slCount: number;
  tpPrice: number | null;  // Highest TP limit price
  slPrice: number | null;  // Lowest SL limit price
  tpProfit: number | null;  // Net profit if TP executes
  slProfit: number | null;  // Net loss if SL executes
  childOrders: Array<{
    orderId: string;
    side: 'SELL';
    type: 'TAKE_PROFIT' | 'STOP_LOSS' | 'SELL';
    quantity: number;
    price: number | null;
    createdAt: string;
  }>;
}

export interface UnifiedOpenOrder {
  order_id: string;
  exchange_order_id?: string;
  symbol: string;
  base_symbol?: string;
  side: string;
  order_type?: string;
  type?: string;
  status: string;
  price: number | null;
  trigger_price: number | null;
  quantity: number | null;
  is_trigger: boolean;
  trigger_type?: string | null;
  trigger_condition?: string | null;
  client_oid?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  source?: string;
  raw?: Record<string, unknown>;
}

export interface OpenOrdersSnapshot {
  orders: UnifiedOpenOrder[];
  last_updated: string | null;
  error?: string;
}


export interface ManualTradeRequest {
  symbol: string;
  side: string;
  quantity: number;
  price: number;
  is_margin: boolean;
  leverage: number;
  sl_percentage: number;
  tp_percentage: number;
  sl_tp_mode: string;
}

export interface PortfolioAsset {
  coin: string;
  balance: number;
  available_qty: number;
  reserved_qty: number;
  haircut: number;
  value_usd: number;
  usd_value?: number;  // Optional alternative field name (backend may return either)
  updated_at: string;
  open_orders_count?: number;
  tp?: number | null;
  sl?: number | null;
}

export interface PortfolioResponse {
  assets: PortfolioAsset[];
  total_value_usd: number;
  ok: boolean;
}

export interface StrategyDecision {
  decision: 'BUY' | 'SELL' | 'WAIT';
  summary?: string;
  reasons?: Record<string, boolean | null | undefined>;
  index?: number | null;
  should_trade?: boolean;
  reason?: string;
  confidence?: number;
  risk_level?: string;
}

export interface TopCoin {
  rank: number;
  instrument_name: string;
  base_currency: string;
  quote_currency: string;
  current_price: number;
  volume_24h: number;
  updated_at: string;
  is_custom?: boolean;
  source?: string;
  alert_enabled?: boolean;  // Alert enabled status for TRADE ALERT YES
  buy_alert_enabled?: boolean;  // Enable BUY alerts specifically
  sell_alert_enabled?: boolean;  // Enable SELL alerts specifically
  // Technical indicators (now included in cache)
  rsi?: number;
  ma50?: number;
  ma200?: number;
  ema10?: number;
  ma10w?: number;
  atr?: number;
  avg_volume?: number;
  volume_ratio?: number;
  min_volume_ratio?: number;  // Minimum volume ratio threshold from strategy config
  current_volume?: number;
  volume_avg_periods?: number;
  // Resistance levels
  res_up?: number;
  res_down?: number;
  strategy?: StrategyDecision;  // Legacy field
  strategy_state?: StrategyDecision;  // Backend source of truth (preferred)
  // Strategy fields from WatchlistItem (single source of truth)
  strategy_preset?: string | null;  // "swing", "intraday", "scalp"
  strategy_risk?: string | null;    // "conservative", "aggressive"
  strategy_key?: string | null;     // "swing-conservative" (canonical identifier)
}

// Dashboard State Types (new unified endpoint)
export interface DashboardBalance {
  asset: string;
  balance: number;  // Explicit balance field from Crypto.com
  free: number;
  locked: number;
  total: number;  // Total balance (free + locked)
  usd_value?: number;  // USD value directly from Crypto.com API
  market_value?: number;  // Original field name from Crypto.com
  quantity?: number;
  max_withdrawal?: number;
  currency?: string;  // Alternative field name for asset (used in some API responses)
  tp?: number | null;  // Take Profit price from backend
  sl?: number | null;  // Stop Loss price from backend
}

type RawPortfolioAsset = Partial<PortfolioAsset> & {
  currency?: string;
  symbol?: string;
  asset?: string;
  coin?: string;
  usd_value?: number;
  value_usd?: number;
  market_value?: number;
  available?: number;
  reserved?: number;
  free?: number;
  locked?: number;
  total?: number;
  balance?: number;
  reserved_qty?: number;
  available_qty?: number;
};

type RawDashboardBalance = Partial<DashboardBalance> & {
  currency?: string;
  symbol?: string;
  coin?: string;
  value_usd?: number;
  available?: number;
  reserved?: number;
  reserved_qty?: number;
  available_qty?: number;
};

const normalizeSymbol = (...candidates: Array<unknown>): string => {
  for (const candidate of candidates) {
    if (typeof candidate === 'string' && candidate.trim().length > 0) {
      return candidate.trim().toUpperCase();
    }
  }
  return '';
};

const coerceNumber = (value: unknown, fallback = 0): number => {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : fallback;
  }
  if (typeof value === 'string') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  }
  return fallback;
};

const normalizePortfolioAsset = (raw: RawPortfolioAsset): PortfolioAsset | null => {
  const coin = normalizeSymbol(raw.coin, raw.currency, raw.asset, raw.symbol);
  if (!coin) {
    return null;
  }

  const availableQty = coerceNumber(raw.available_qty ?? raw.free ?? raw.available);
  const reservedQty = coerceNumber(raw.reserved_qty ?? raw.locked ?? raw.reserved);
  const balance = coerceNumber(raw.balance ?? raw.total ?? availableQty + reservedQty);
  const valueUsd = coerceNumber(raw.value_usd ?? raw.usd_value ?? raw.market_value);

  return {
    coin,
    balance,
    available_qty: availableQty || balance,
    reserved_qty: reservedQty,
    haircut: coerceNumber(raw.haircut, 0),
    value_usd: valueUsd,
    updated_at: raw.updated_at ?? new Date().toISOString(),
    open_orders_count: raw.open_orders_count,
    tp: raw.tp !== undefined && raw.tp !== null ? coerceNumber(raw.tp) : null,
    sl: raw.sl !== undefined && raw.sl !== null ? coerceNumber(raw.sl) : null,
  };
};

const normalizePortfolioAssets = (rawAssets?: RawPortfolioAsset[]): PortfolioAsset[] => {
  if (!Array.isArray(rawAssets)) {
    return [];
  }

  return rawAssets
    .map(asset => normalizePortfolioAsset(asset))
    .filter((asset): asset is PortfolioAsset => Boolean(asset));
};

const normalizeDashboardBalance = (raw: RawDashboardBalance): DashboardBalance | null => {
  const asset = normalizeSymbol(raw.asset, raw.currency, raw.symbol, raw.coin);
  if (!asset) {
    return null;
  }

  const free = coerceNumber(raw.free ?? raw.available ?? raw.available_qty);
  const locked = coerceNumber(raw.locked ?? raw.reserved ?? raw.reserved_qty);
  const balance = coerceNumber(raw.balance ?? raw.total ?? free + locked);
  // IMPORTANT: Preserve 0 values - don't convert to undefined
  // Check all possible field names for USD value
  const usdValue = coerceNumber(
    raw.usd_value ?? raw.market_value ?? raw.value_usd,
    0  // Default to 0, not undefined
  );

  return {
    asset,
    balance,
    free: free || balance,
    locked,
    total: balance,
    // Preserve 0 values - only use undefined if the value was never provided
    usd_value: raw.usd_value !== undefined || raw.market_value !== undefined || raw.value_usd !== undefined
      ? usdValue
      : undefined,
    market_value: raw.market_value !== undefined
      ? coerceNumber(raw.market_value, 0)
      : (raw.usd_value !== undefined || raw.value_usd !== undefined ? usdValue : undefined),
    quantity: raw.quantity !== undefined ? coerceNumber(raw.quantity) : undefined,
    max_withdrawal: raw.max_withdrawal !== undefined ? coerceNumber(raw.max_withdrawal) : undefined,
  };
};

const sumAssetValues = (assets: PortfolioAsset[]): number =>
  assets.reduce((sum, asset) => sum + coerceNumber(asset.value_usd), 0);

export function dashboardBalancesToPortfolioAssets(balances: DashboardBalance[]): PortfolioAsset[] {
  const aggregated = new Map<string, PortfolioAsset>();

  balances
    .filter(balance => balance && (balance.asset || balance.currency))
    .forEach(balance => {
      const assetValue = balance.asset || balance.currency || '';
      const coin = normalizeSymbol(assetValue);
      if (!coin) {
        return;
      }

      const availableQty = coerceNumber(balance.free);
      const reservedQty = coerceNumber(balance.locked);
      const balanceQty = coerceNumber(balance.balance ?? balance.total ?? availableQty + reservedQty);
      const valueUsd = coerceNumber(balance.usd_value ?? balance.market_value);

      if (
        !balanceQty &&
        !availableQty &&
        !reservedQty &&
        !valueUsd
      ) {
        return;
      }

      const existing = aggregated.get(coin);
      const tpPrice = balance.tp !== undefined && balance.tp !== null ? coerceNumber(balance.tp) : undefined;
      const slPrice = balance.sl !== undefined && balance.sl !== null ? coerceNumber(balance.sl) : undefined;
      
      if (!existing) {
        aggregated.set(coin, {
        coin,
        balance: balanceQty,
        available_qty: availableQty || balanceQty,
        reserved_qty: reservedQty,
        haircut: 0,
        value_usd: valueUsd,
        updated_at: new Date().toISOString(),
        tp: tpPrice !== undefined ? tpPrice : null,
        sl: slPrice !== undefined ? slPrice : null,
        });
      } else {
        existing.balance += balanceQty;
        existing.available_qty += availableQty || 0;
        existing.reserved_qty += reservedQty || 0;
        existing.value_usd = (existing.value_usd ?? 0) + valueUsd;
        // Keep the highest TP and lowest SL if multiple balances exist
        if (tpPrice !== undefined && (existing.tp === null || existing.tp === undefined || tpPrice > existing.tp)) {
          existing.tp = tpPrice;
        }
        if (slPrice !== undefined && (existing.sl === null || existing.sl === undefined || slPrice < existing.sl)) {
          existing.sl = slPrice;
        }
      }
    });

  return Array.from(aggregated.values());
}

export interface DashboardSignal {
  symbol: string;
  preset: string | null;
  sl_profile: string | null;
  rsi: number | null;
  ma50: number | null;
  ma200: number | null;
  ema10: number | null;
  ma10w?: number | null;
  atr: number | null;
  resistance_up: number | null;
  resistance_down: number | null;
  current_price: number | null;
  volume_24h: number | null;
  volume_ratio: number | null;
  status: string | null;
  should_trade: boolean;
  exchange_order_id: string | null;
  last_update_at: string | null;
  refresh_hint: 'fast' | 'slow';
}

export interface DashboardOrder {
  exchange_order_id: string;
  symbol: string;
  side: string | null;
  order_type: string | null;
  status: string | null;
  price: number | null;
  quantity: number | null;
  cumulative_quantity: number | null;
  cumulative_value: number | null;
  avg_price: number | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface DashboardState {
  source?: string;  // "crypto.com" when using direct API values
  total_usd_value?: number;  // Total USD value from Crypto.com
  balances: DashboardBalance[];
  fast_signals: DashboardSignal[];
  slow_signals: DashboardSignal[];
  open_orders: DashboardOrder[];
  open_orders_summary?: UnifiedOpenOrder[];
  // Unified open position counts per base currency (e.g., ADA, LDO).
  // This uses the same logic as the backend protection system and is used
  // by the Holdings table to show "Open Orders" per coin.
  open_position_counts?: { [symbol: string]: number };
  last_sync: string | null;
  partial?: boolean;
  portfolio?: {
    assets?: PortfolioAsset[];
    total_value_usd?: number;
  };
  errors?: string[];
  bot_status: {
    is_running: boolean;
    status: 'running' | 'stopped';
    reason: string | null;
    live_trading_enabled?: boolean;
    mode?: 'LIVE' | 'DRY_RUN';
  };
}

export interface DashboardSnapshot {
  data: DashboardState;
  last_updated_at: string | null;
  stale_seconds: number | null;
  stale: boolean;
  empty?: boolean;
}

export interface CoinSettings {
  symbol?: string;
  exchange?: string;
  trade_enabled?: boolean;
  trade_amount_usd?: number | null;
  trade_on_margin?: boolean;
  alert_enabled?: boolean;
  buy_alert_enabled?: boolean;
  sell_alert_enabled?: boolean;
  sl_tp_mode?: string;
  min_price_change_pct?: number | null;
  alert_cooldown_minutes?: number | null;
  sl_percentage?: number | null;
  tp_percentage?: number | null;
  sl_price?: number;
  tp_price?: number;
}

// Circuit breaker for signals endpoint
let signalsFailureCount = 0;
let signalsLastFailureTime = 0;
const MAX_FAILURES = 5;
const CIRCUIT_BREAKER_TIMEOUT = 30000; // 30 seconds
const ERROR_LOG_SUPPRESSION_MS = 30000; // Deduplicate identical errors within 30s

const errorLogTimestamps = new Map<string, number>();

const TIMEOUT_WARN_THRESHOLD = 3;
const TIMEOUT_WINDOW_MS = 15000;
const timeoutWarningState = new Map<string, { count: number; windowStart: number }>();

function logTimeoutActivation(endpoint: string, timeoutMs: number): void {
  const now = Date.now();
  const state = timeoutWarningState.get(endpoint);

  if (!state || (now - state.windowStart) > TIMEOUT_WINDOW_MS) {
    timeoutWarningState.set(endpoint, { count: 1, windowStart: now });
    console.debug(`⏳ Timeout activado para ${endpoint} después de ${timeoutMs}ms (silenciado hasta ${TIMEOUT_WARN_THRESHOLD - 1} repetición${TIMEOUT_WARN_THRESHOLD - 1 === 1 ? '' : 'es'} más)`);
    return;
  }

  const nextCount = state.count + 1;
  timeoutWarningState.set(endpoint, { count: nextCount, windowStart: state.windowStart });

  const logger = nextCount >= TIMEOUT_WARN_THRESHOLD ? console.warn : console.debug;
  const suffix = nextCount >= TIMEOUT_WARN_THRESHOLD
    ? `(${nextCount} timeouts en ${Math.round(TIMEOUT_WINDOW_MS / 1000)}s)`
    : `(${nextCount}/${TIMEOUT_WARN_THRESHOLD} antes de alerta)`;
  logger(`⏰ Timeout activado para ${endpoint} después de ${timeoutMs}ms ${suffix}`);
}

function shouldLogError(key: string): boolean {
  const lastLoggedAt = errorLogTimestamps.get(key) ?? 0;
  const now = Date.now();
  if (now - lastLoggedAt >= ERROR_LOG_SUPPRESSION_MS) {
    errorLogTimestamps.set(key, now);
    return true;
  }
  return false;
}

function logRequestIssue(endpoint: string, message: string, error: unknown, level: 'warn' | 'error' = 'error'): void {
  const key = `${endpoint}::${message}`;
  if (!shouldLogError(key)) return;
  const logger = level === 'warn' ? console.warn : console.error;
  if (error instanceof Error) {
    logger(message, { name: error.name, message: error.message, stack: error.stack });
  } else {
    logger(message, error);
  }
}

function isSignalsCircuitOpen(): boolean {
  const now = Date.now();
  
  // Auto-reset if timeout has passed (even if circuit was open)
  if (signalsLastFailureTime > 0 && (now - signalsLastFailureTime) >= CIRCUIT_BREAKER_TIMEOUT) {
    signalsFailureCount = 0;
    signalsLastFailureTime = 0;
    console.log('✅ Signals circuit breaker auto-reset (timeout passed)');
    return false; // Circuit is closed now - reset after timeout
  }
  
  // Check if circuit should be open (only if timeout hasn't passed)
  // Only open circuit for actual errors (not slow responses)
  // Increase threshold since signals endpoint can be slow but still work
  if (signalsFailureCount >= MAX_FAILURES) {
    // Only keep circuit open if we're still within the timeout period
    if (signalsLastFailureTime > 0 && (now - signalsLastFailureTime) < CIRCUIT_BREAKER_TIMEOUT) {
      const remainingTime = Math.ceil((CIRCUIT_BREAKER_TIMEOUT - (now - signalsLastFailureTime)) / 1000);
      // Only log warning occasionally to avoid spam
      if (shouldLogError('circuit-breaker-warning')) {
        console.debug(`🔴 Signals circuit breaker is OPEN (${signalsFailureCount} failures). Retry in ${remainingTime}s`);
      }
      return true; // Circuit is open
    } else {
      // Timeout passed - reset and close circuit
      signalsFailureCount = 0;
      signalsLastFailureTime = 0;
      return false;
    }
  }
  
  return false; // Circuit is closed
}

function recordSignalsFailure(): void {
  signalsFailureCount++;
  signalsLastFailureTime = Date.now();
}

function recordSignalsSuccess(): void {
  signalsFailureCount = 0;
  signalsLastFailureTime = 0;
}

// Reset circuit breaker manually (for debugging/recovery)
export function resetSignalsCircuitBreaker(): void {
  signalsFailureCount = 0;
  signalsLastFailureTime = 0;
  console.log('✅ Signals circuit breaker manually reset');
}

// API Helper
async function fetchAPI<T>(endpoint: string, options?: RequestInit): Promise<T> {
  try {
    // Check circuit breaker for signals endpoint with auto-reset
    if (endpoint.includes('/signals')) {
      const now = Date.now();
      // Auto-reset circuit breaker if timeout has passed
      if (signalsLastFailureTime > 0 && (now - signalsLastFailureTime) >= CIRCUIT_BREAKER_TIMEOUT) {
        resetSignalsCircuitBreaker();
        console.log('✅ Signals circuit breaker auto-reset (timeout passed)');
      }
      // Check if circuit is still open after potential reset
      if (isSignalsCircuitOpen()) {
        // Don't log here - isSignalsCircuitOpen() already logs
        const circuitError = new Error(`Circuit breaker open for signals endpoint`) as Error & { status?: number; retryAfterMs?: number };
        circuitError.status = 503; // Service Unavailable
        const remainingTime = CIRCUIT_BREAKER_TIMEOUT - (now - signalsLastFailureTime);
        circuitError.retryAfterMs = Math.max(0, remainingTime);
        throw circuitError;
      }
    }
    
    const apiUrl = typeof window !== 'undefined' ? getApiUrl() : DEFAULT_API_URL;
    const fullUrl = `${apiUrl}${endpoint}`;
    // Debug logs removed to reduce console noise - uncomment if needed for debugging
    // console.log('🌐 fetchAPI: Making request to:', fullUrl);
    
        // Create an AbortController for timeout
        // Signals, top-coins-data, dashboard/state, and orders/history endpoints can take longer due to multi-source price fetching or database queries
        let timeoutMs = 30000; // Default 30s
        if (endpoint.includes('/signals')) {
          timeoutMs = 20000; // 20s for signals (backend has strict timeouts, but may need extra time for slow networks)
        } else if (endpoint.includes('/market/top-coins-data')) {
          timeoutMs = 60000; // 60s for top-coins-data (increased to allow for database queries and external API delays)
        } else if (endpoint.includes('/dashboard/snapshot')) {
          timeoutMs = 15000; // 15s for dashboard/snapshot - increased to handle slow database queries
        } else if (endpoint.includes('/dashboard/state')) {
          timeoutMs = 180000; // 180s (3 minutes) for dashboard/state - backend can take 50-70s, so we need generous timeout
        } else if (endpoint.includes('/monitoring/summary')) {
          timeoutMs = 60000; // 60s for monitoring/summary (lightweight endpoint but may need time if backend is busy)
        } else if (endpoint.includes('/orders/history')) {
          timeoutMs = 60000; // 60s for orders/history (database query with pagination)
        } else if (endpoint.includes('/test/simulate-alert')) {
          timeoutMs = 60000; // 60s for simulate-alert (needs to create order, may take time)
        } else if (endpoint.includes('/watchlist/') && endpoint.includes('/alert')) {
          timeoutMs = 15000; // 15s for watchlist alert updates (increased from 10s to allow for network delays)
        } else if (endpoint.includes('/market/top-coins/custom')) {
          timeoutMs = 30000; // 30s for adding custom coins (database operations)
        } else if (endpoint.includes('/monitoring/workflows')) {
          timeoutMs = 150000; // 150s (2.5 minutes) for workflows - may need time for file system operations and initialization
        }
        const controller = new AbortController();
        const timeoutId = setTimeout(() => {
          logTimeoutActivation(endpoint, timeoutMs);
          controller.abort();
        }, timeoutMs);
    
    console.log(`🔄 Iniciando fetch para ${endpoint} con timeout de ${timeoutMs}ms`);
    console.log(`🌐 URL completa: ${fullUrl}`);
    const fetchStartTime = Date.now();
    
    let response: Response;
    try {
      response = await fetch(fullUrl, {
      ...options,
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': 'demo-key', // Add authentication header
        ...options?.headers,
      },
    });
    } catch (fetchError) {
      clearTimeout(timeoutId);
      const fetchElapsed = Date.now() - fetchStartTime;
      const errorMsg = fetchError instanceof Error ? fetchError.message : String(fetchError);
      
      // Provide more detailed error information for network errors
      if (errorMsg.includes('Failed to fetch') || errorMsg.includes('NetworkError')) {
        console.error(`❌ Network error for ${endpoint}:`, {
          url: fullUrl,
          elapsed: `${fetchElapsed}ms`,
          error: errorMsg,
          possibleCauses: [
            'Backend not running or not accessible',
            'CORS configuration issue',
            'Network connectivity problem',
            'Backend timeout or crash'
          ]
        });
      } else if (errorMsg.includes('aborted') || errorMsg.includes('AbortError')) {
        console.error(`⏱️ Request timeout for ${endpoint} after ${timeoutMs}ms:`, {
          url: fullUrl,
          elapsed: `${fetchElapsed}ms`
        });
      } else {
        console.error(`❌ Fetch error for ${endpoint}:`, {
          url: fullUrl,
          elapsed: `${fetchElapsed}ms`,
          error: errorMsg
        });
      }
      
      throw fetchError;
    }
    
    const fetchElapsed = Date.now() - fetchStartTime;
    console.log(`✅ Fetch completado para ${endpoint} en ${fetchElapsed}ms`);
    clearTimeout(timeoutId);
    
    if (!response.ok) {
      // Try to parse the error response body to get the detailed error message
      let errorDetail = `HTTP error! status: ${response.status}`;
      try {
        const errorJson = await response.json();
        // FastAPI returns errors in { detail: "..." } format
        if (errorJson.detail) {
          errorDetail = errorJson.detail;
        } else if (errorJson.message) {
          errorDetail = errorJson.message;
        } else if (typeof errorJson === 'string') {
          errorDetail = errorJson;
        } else if (errorJson.error) {
          errorDetail = errorJson.error;
        }
      } catch {
        // If parsing fails, try to get text response
        try {
          const errorText = await response.text();
          if (errorText) {
            errorDetail = errorText;
          }
        } catch {
          // Use default error message
        }
      }
      
      const error = new Error(errorDetail) as Error & {
        status?: number;
        retryAfterMs?: number;
        detail?: string;
      };
      error.status = response.status;
      error.detail = errorDetail;
      
      const retryAfter = response.headers.get('retry-after');
      if (retryAfter) {
        const retrySeconds = Number(retryAfter);
        if (!Number.isNaN(retrySeconds)) {
          error.retryAfterMs = retrySeconds * 1000;
        } else {
          const retryDate = Date.parse(retryAfter);
          if (!Number.isNaN(retryDate)) {
            error.retryAfterMs = Math.max(0, retryDate - Date.now());
          }
        }
      }
      throw error;
    }
    
    const json = await response.json();
    
    // Record success for circuit breaker
    if (endpoint.includes('/signals')) {
      recordSignalsSuccess();
    }
    
    return json as T;
    } catch (error) {
      // Record failure for circuit breaker (but not if circuit breaker itself caused the error, or if it's just a timeout)
      if (endpoint.includes('/signals') && error instanceof Error) {
        // Don't record timeout errors as failures - they're just slow responses, not actual failures
        const isTimeout = error.message.includes('timeout') || error.message.includes('Request timeout') || error.name === 'AbortError';
        const isCircuitBreaker = error.message.includes('Circuit breaker');
        
        if (!isCircuitBreaker && !isTimeout) {
          recordSignalsFailure();
        } else if (isTimeout) {
          // Timeouts are slow but not failures - don't count them against circuit breaker
          console.debug(`⏱️ Signals endpoint timeout for ${endpoint} - slow response but not a failure`);
        }
      }
      
        if (error instanceof Error) {
        if (error.name === 'AbortError') {
          let timeoutSeconds = 30;
          if (endpoint.includes('/signals')) {
            timeoutSeconds = 15; // 15s for signals (matches timeoutMs)
          } else if (endpoint.includes('/market/top-coins-data')) {
            timeoutSeconds = 60; // 60s for top-coins-data (matches timeoutMs)
          } else if (endpoint.includes('/dashboard/snapshot')) {
            timeoutSeconds = 5; // 5s for dashboard/snapshot (matches timeoutMs)
          } else if (endpoint.includes('/dashboard/state')) {
            timeoutSeconds = 180; // 180s for dashboard/state (matches timeoutMs)
          } else if (endpoint.includes('/monitoring/summary')) {
            timeoutSeconds = 60; // 60s for monitoring/summary (matches timeoutMs)
          } else if (endpoint.includes('/orders/history')) {
            timeoutSeconds = 60;
          } else if (endpoint.includes('/test/simulate-alert')) {
            timeoutSeconds = 60; // 60s for simulate-alert (matches timeoutMs)
          } else if (endpoint.includes('/watchlist/') && endpoint.includes('/alert')) {
            timeoutSeconds = 10; // 10s for watchlist alert updates (matches timeoutMs)
          } else if (endpoint.includes('/market/top-coins/custom')) {
            timeoutSeconds = 30; // 30s for adding custom coins (matches timeoutMs)
          } else if (endpoint.includes('/monitoring/workflows')) {
            timeoutSeconds = 150; // 150s for workflows (matches timeoutMs)
          }
          logRequestIssue(
            endpoint,
            `⏰ API Timeout: ${endpoint} (after ${timeoutSeconds} seconds)`,
            error,
            'warn'
          );
          const timeoutError = new Error(`Request timeout for ${endpoint}. The server may be processing the request. Please try again.`) as Error & { status?: number; retryAfterMs?: number };
          timeoutError.status = 408; // Request Timeout
          timeoutError.retryAfterMs = 5000; // Retry after 5 seconds
          throw timeoutError;
        } else if (error.message.includes('Failed to fetch')) {
          logRequestIssue(
            endpoint,
            `🌐 Network Error: ${endpoint} (${error.message})`,
            error,
            'warn'
          );
          // For /signals, /market/top-coins-data, /dashboard/state, and /orders/history endpoints, this might be a timeout issue
          // Note: /dashboard/snapshot should be fast, so don't include it here
          if (endpoint.includes('/signals') || endpoint.includes('/market/top-coins-data') || endpoint.includes('/dashboard/state') || endpoint.includes('/orders/history')) {
            const networkError = new Error(`Network error for ${endpoint}. The server may be taking too long to respond. Please try again.`) as Error & { status?: number; retryAfterMs?: number };
            networkError.status = 0; // Network error
            networkError.retryAfterMs = 3000; // Retry after 3 seconds for long-running endpoints
            throw networkError;
          } else {
            const networkError = new Error(`Network error for ${endpoint}: ${error.message}`) as Error & { status?: number; retryAfterMs?: number };
            networkError.status = 0; // Network error
            networkError.retryAfterMs = 2000; // Retry after 2 seconds
            throw networkError;
          }
        }
      }
      logRequestIssue(endpoint, `API Error: ${endpoint}`, error);
      throw error;
    }
}

// Dashboard/Watchlist functions
export async function getDashboard(): Promise<WatchlistItem[]> {
  try {
    const data = await fetchAPI<WatchlistItem[]>('/dashboard');
    const items = Array.isArray(data) ? data : [];
    return items.map((item) => ({
      ...item,
      symbol: item?.symbol ? item.symbol.toUpperCase() : ''
    }));
  } catch (error) {
    logRequestIssue(
      'getDashboard',
      'Handled dashboard fetch failure (returning empty list)',
      error,
      'warn'
    );
    return [];
  }
}

export async function addToDashboard(item: WatchlistInput): Promise<WatchlistItem> {
  const data = await fetchAPI<WatchlistItem>('/dashboard', {
    method: 'POST',
    body: JSON.stringify(item),
  });
  return data;
}

export async function updateDashboardItem(id: number, item: Partial<WatchlistItem>): Promise<WatchlistItem & { message?: string }> {
  const data = await fetchAPI<WatchlistItem & { message?: string }>(`/dashboard/${id}`, {
    method: 'PUT',
    body: JSON.stringify(item),
  });
  if (data.message) {
    console.log(`✅ Backend: ${data.message}`);
  }
  return data;
}

export async function saveCoinSettings(symbol: string, settings: Partial<CoinSettings>): Promise<WatchlistItem & { message?: string }> {
  const normalizedSymbol = symbol ? symbol.toUpperCase() : '';
  const settingsKeys = Object.keys(settings).filter(k => settings[k as keyof typeof settings] !== undefined);
  
  // Debug logging
  console.debug(`[saveCoinSettings] Starting for ${normalizedSymbol}`, {
    symbol: normalizedSymbol,
    settingsKeys,
    settingsCount: settingsKeys.length
  });
  
  try {
    const { trade_amount_usd, ...otherSettings } = settings;
    // Explicitly include null values to allow clearing fields (e.g., sl_percentage: null)
    const normalizedSettings: Partial<WatchlistItem> = {
      ...otherSettings,
      ...(trade_amount_usd !== null && trade_amount_usd !== undefined
        ? { trade_amount_usd }
        : {}),
    };
    // Ensure null values are explicitly included (not omitted by JSON.stringify)
    if ('sl_percentage' in settings) normalizedSettings.sl_percentage = settings.sl_percentage ?? null;
    if ('tp_percentage' in settings) normalizedSettings.tp_percentage = settings.tp_percentage ?? null;
    if ('min_price_change_pct' in settings) normalizedSettings.min_price_change_pct = settings.min_price_change_pct ?? null;
    if ('alert_cooldown_minutes' in settings) normalizedSettings.alert_cooldown_minutes = settings.alert_cooldown_minutes ?? null;
    
    // First, get the existing item by symbol
    let items: WatchlistItem[] = [];
    try {
      const dashboardItems = await getDashboard();
      items = Array.isArray(dashboardItems) ? dashboardItems : [];
    } catch (error) {
      console.error(`[saveCoinSettings] Failed to fetch dashboard items for ${normalizedSymbol}:`, error);
      throw new Error(`Failed to fetch watchlist: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
    
    // Find all items matching the symbol (may have duplicates)
    const matchingItems = items.filter(item => (item.symbol || '').toUpperCase() === normalizedSymbol);
    
    // Use canonical selector logic (same as backend's select_preferred_watchlist_item)
    // Priority: 1) Not deleted, 2) alert_enabled=true, 3) Newer timestamp, 4) Higher ID
    const selectCanonicalItem = (items: WatchlistItem[]): WatchlistItem | undefined => {
      if (items.length === 0) return undefined;
      if (items.length === 1) return items[0];
      
      // Filter out deleted items first
      const nonDeleted = items.filter(item => !item.is_deleted);
      const candidates = nonDeleted.length > 0 ? nonDeleted : items;
      
      // Sort by priority: alert_enabled (true first), then by timestamp (newer first), then by ID (higher first)
      const sorted = [...candidates].sort((a, b) => {
        // Priority 1: alert_enabled (true = 0, false = 1)
        const aAlert = a.alert_enabled ? 0 : 1;
        const bAlert = b.alert_enabled ? 0 : 1;
        if (aAlert !== bAlert) return aAlert - bAlert;
        
        // Priority 2: timestamp (newer = higher priority, so negate)
        const aTime = a.updated_at || a.created_at || '';
        const bTime = b.updated_at || b.created_at || '';
        const aTimestamp = aTime ? new Date(aTime).getTime() : 0;
        const bTimestamp = bTime ? new Date(bTime).getTime() : 0;
        if (aTimestamp !== bTimestamp) return bTimestamp - aTimestamp; // Descending (newer first)
        
        // Priority 3: ID (higher = better, so negate)
        return (b.id || 0) - (a.id || 0); // Descending (higher ID first)
      });
      
      return sorted[0];
    };
    
    const existingItem = selectCanonicalItem(matchingItems);
    
    if (existingItem && existingItem.id) {
      console.debug(`[saveCoinSettings] Found existing item for ${normalizedSymbol}`, {
        id: existingItem.id,
        symbol: existingItem.symbol,
        endpoint: `PUT /api/dashboard/${existingItem.id}`
      });
      
      try {
        // Update existing item - merge with existing data
        // CORRECT ENDPOINT: PUT /api/dashboard/{item_id}
        const result = await updateDashboardItem(existingItem.id, {
          symbol,
          exchange: existingItem.exchange || 'CRYPTO_COM',
          buy_target: existingItem.buy_target,
          take_profit: existingItem.take_profit,
          stop_loss: existingItem.stop_loss,
          ...normalizedSettings
        });
        
        console.debug(`[saveCoinSettings] Successfully updated ${normalizedSymbol}`, {
          id: existingItem.id,
          message: result.message
        });
        
        if (result.message) {
          console.log(`✅ Backend confirmation: ${result.message}`);
        }
        return result;
      } catch (error) {
        // Enhanced error handling with specific 405 detection
        const errorWithStatus = error as Error & { status?: number; detail?: string };
        const errorMsg = error instanceof Error ? error.message : String(error);
        const status = errorWithStatus.status;
        
        // Handle 405 Method Not Allowed - this should never happen with correct endpoint
        if (status === 405) {
          const fatalMsg = `[FATAL] Method: PUT, Caller: saveCoinSettings - PUT /api/dashboard/${existingItem.id} returned 405. This endpoint should exist.`;
          console.error(fatalMsg, {
            symbol: normalizedSymbol,
            itemId: existingItem.id,
            endpoint: `/api/dashboard/${existingItem.id}`,
            method: 'PUT',
            error: errorMsg
          });
          logRequestIssue(
            `saveCoinSettings:${normalizedSymbol}`,
            fatalMsg,
            error,
            'error'
          );
          throw new Error(`Backend endpoint mismatch (405): PUT /api/dashboard/${existingItem.id} is not supported. This is a bug.`);
        }
        
        // Handle other HTTP errors
        if (status === 404 || errorMsg.includes('404') || errorMsg.includes('not found')) {
          throw new Error(`Watchlist item for ${normalizedSymbol} not found. It may have been deleted.`);
        } else if (status === 422 || errorMsg.includes('422') || errorMsg.includes('validation')) {
          const warnMsg = `[WARN] Validation error saving ${normalizedSymbol}: ${errorMsg}`;
          console.warn(warnMsg, { symbol: normalizedSymbol, settings: normalizedSettings });
          logRequestIssue(
            `saveCoinSettings:${normalizedSymbol}`,
            warnMsg,
            error,
            'warn'
          );
          throw new Error(`Validation error: ${errorMsg}`);
        } else if (status === 502 || errorMsg.includes('502') || errorMsg.includes('Bad Gateway')) {
          throw new Error(`Backend service unavailable (502). Please check if the backend is running.`);
        } else if (status === 500 || errorMsg.includes('500')) {
          throw new Error(`Backend error (500): ${errorMsg}`);
        } else {
          throw new Error(`Failed to update ${normalizedSymbol}: ${errorMsg}`);
        }
      }
    } else {
      console.debug(`[saveCoinSettings] Creating new item for ${normalizedSymbol}`, {
        endpoint: 'POST /api/dashboard'
      });
      
      try {
        // Create new item - explicitly construct WatchlistInput to avoid type issues
        const newItem: WatchlistInput = {
          symbol,
          exchange: 'CRYPTO_COM',
          buy_target: normalizedSettings.buy_target,
          take_profit: normalizedSettings.take_profit,
          stop_loss: normalizedSettings.stop_loss,
          trade_enabled: normalizedSettings.trade_enabled,
          trade_amount_usd: normalizedSettings.trade_amount_usd,
          trade_on_margin: normalizedSettings.trade_on_margin,
          sl_tp_mode: normalizedSettings.sl_tp_mode,
          min_price_change_pct: normalizedSettings.min_price_change_pct,
          sl_percentage: normalizedSettings.sl_percentage,
          tp_percentage: normalizedSettings.tp_percentage,
          notes: normalizedSettings.notes,
        };
        const result = await addToDashboard(newItem);
        console.debug(`[saveCoinSettings] Successfully created ${normalizedSymbol}`, {
          id: result.id,
          symbol: result.symbol
        });
        return result;
      } catch (error) {
        const errorWithStatus = error as Error & { status?: number };
        const errorMsg = error instanceof Error ? error.message : String(error);
        const status = errorWithStatus.status;
        
        if (status === 405) {
          const fatalMsg = `[FATAL] Method: POST, Caller: saveCoinSettings - POST /api/dashboard returned 405. This endpoint should exist.`;
          console.error(fatalMsg, {
            symbol: normalizedSymbol,
            endpoint: '/api/dashboard',
            method: 'POST',
            error: errorMsg
          });
          logRequestIssue(
            `saveCoinSettings:${normalizedSymbol}`,
            fatalMsg,
            error,
            'error'
          );
          throw new Error(`Backend endpoint mismatch (405): POST /api/dashboard is not supported. This is a bug.`);
        } else if (status === 502 || errorMsg.includes('502') || errorMsg.includes('Bad Gateway')) {
          throw new Error(`Backend service unavailable (502). Please check if the backend is running.`);
        } else if (status === 500 || errorMsg.includes('500')) {
          throw new Error(`Backend error (500): ${errorMsg}`);
        } else {
          throw new Error(`Failed to create watchlist item for ${normalizedSymbol}: ${errorMsg}`);
        }
      }
    }
  } catch (error) {
    // Final error handling - log and re-throw with context
    if (error instanceof Error) {
      // Only log as FATAL for 404/405/500+ errors, WARN for validation errors
      const errorWithStatus = error as Error & { status?: number };
      const status = errorWithStatus.status;
      const isFatal = status === 404 || status === 405 || (status !== undefined && status >= 500);
      const level = isFatal ? 'error' : 'warn';
      
      logRequestIssue(
        `saveCoinSettings:${normalizedSymbol}`,
        `Error saving coin settings for ${normalizedSymbol}: ${error.message}`,
        error,
        level
      );
      throw error;
    }
    // Otherwise wrap it
    logRequestIssue(
      `saveCoinSettings:${normalizedSymbol}`,
      `Handled error while saving coin settings for ${normalizedSymbol}`,
      error,
      'warn'
    );
    throw new Error(`Failed to save settings for ${normalizedSymbol}: ${String(error)}`);
  }
}

export async function deleteDashboardItem(id: number): Promise<void> {
  await fetchAPI(`/dashboard/${id}`, {
    method: 'DELETE',
  });
}

export async function deleteDashboardItemBySymbol(symbol: string): Promise<void> {
  await fetchAPI(`/dashboard/symbol/${encodeURIComponent(symbol)}`, {
    method: 'DELETE',
  });
}

export async function getWatchlistItemBySymbol(symbol: string): Promise<WatchlistItem | null> {
  if (!symbol) {
    return null;
  }
  const normalizedSymbol = symbol.toUpperCase();
  try {
    const data = await fetchAPI<WatchlistItem>(`/dashboard/symbol/${encodeURIComponent(normalizedSymbol)}`);
    if (data && data.symbol) {
      return {
        ...data,
        symbol: data.symbol.toUpperCase(),
      };
    }
    return null;
  } catch (error) {
    logRequestIssue(
      `getWatchlistItemBySymbol:${normalizedSymbol}`,
      'Handled error while fetching single watchlist item',
      error,
      'warn'
    );
    return null;
  }
}

// Instruments
export async function getInstruments(): Promise<string[]> {
  try {
    const data = await fetchAPI<string[]>('/instruments');
    return data || [];
  } catch (error) {
    logRequestIssue(
      'getInstruments',
      'Handled instruments fetch failure (returning empty list)',
      error,
      'warn'
    );
    return [];
  }
}

// Account
export async function getAccountBalance(): Promise<AccountSummary[]> {
  try {
    const data = await fetchAPI<AccountSummary[]>('/account/balance?exchange=CRYPTO_COM');
    return data || [];
  } catch (error) {
    logRequestIssue(
      'getAccountBalance',
      'Handled account balance fetch failure (returning empty list)',
      error,
      'warn'
    );
    return [];
  }
}

// Orders
export async function getOpenOrders(): Promise<{ orders: OpenOrder[], count: number }> {
  try {
    const data = await fetchAPI<{ orders?: OpenOrder[]; count?: number }>('/orders/open');
    return { orders: data.orders || [], count: data.count || 0 };
  } catch (error) {
    logRequestIssue(
      'getOpenOrders',
      'Handled open orders fetch failure (returning empty list)',
      error,
      'warn'
    );
    return { orders: [], count: 0 };
  }
}

export interface TPSLOrderValues {
  [currency: string]: {
    tp_value_usd: number;
    sl_value_usd: number;
  };
}

export async function getTPSLOrderValues(): Promise<TPSLOrderValues> {
  try {
    const data = await fetchAPI<TPSLOrderValues>('/orders/tp-sl-values');
    return data || {};
  } catch (error) {
    logRequestIssue(
      'getTPSLOrderValues',
      'Handled TP/SL values fetch failure (returning empty object)',
      error,
      'warn'
    );
    return {};
  }
}

export async function getOpenOrdersSummary(): Promise<{ orders: UnifiedOpenOrder[]; last_updated: string | null }> {
  try {
    const data = await fetchAPI<{ orders: UnifiedOpenOrder[]; last_updated?: string | null }>('/dashboard/open-orders-summary');
    const orders = data.orders || [];
    return { orders, last_updated: data.last_updated ?? null };
  } catch (error) {
    logRequestIssue(
      'getOpenOrdersSummary',
      'Handled open orders summary fetch failure (returning empty array)',
      error,
      'warn'
    );
    return { orders: [], last_updated: null };
  }
}

// Expected Take Profit types
export interface ExpectedTPSummary {
  symbol: string;
  net_qty: number;
  current_price: number;
  position_value: number;
  actual_position_value?: number;  // Value at buy price (for gain/loss calculation)
  covered_qty: number;
  uncovered_qty: number;
  total_expected_profit: number;
  coverage_ratio: number;
}

export interface ExpectedTPMatchedLot {
  symbol: string;
  buy_order_id: string;
  buy_order_ids?: string[]; // For grouped entries
  buy_order_count?: number; // For grouped entries
  buy_time: string | null;
  buy_price: number;
  lot_qty: number;
  tp_order_id: string;
  tp_time: string | null;
  tp_price: number;
  tp_qty: number;
  tp_status: string;
  match_origin: string;
  expected_profit: number;
  expected_profit_pct: number;
  is_grouped?: boolean; // For grouped entries
}

export interface ExpectedTPDetails {
  symbol: string;
  net_qty: number;
  current_price?: number; // Optional for flexibility
  position_value: number;
  actual_position_value?: number;  // Value based on buy prices, not current market price
  covered_qty: number;
  uncovered_qty: number;
  total_expected_profit: number;
  matched_lots: ExpectedTPMatchedLot[];
  has_uncovered?: boolean; // Optional for flexibility
  uncovered_entry?: {
    symbol: string;
    uncovered_qty: number;
    label: string;
    is_uncovered?: true; // Optional for flexibility
  };
}

export async function getExpectedTakeProfitSummary(): Promise<{
  summary: ExpectedTPSummary[];
  total_symbols: number;
  last_updated: string | null;
}> {
  try {
    const data = await fetchAPI<{
      summary: ExpectedTPSummary[];
      total_symbols: number;
      last_updated?: string | null;
    }>('/dashboard/expected-take-profit');
    return {
      summary: data.summary || [],
      total_symbols: data.total_symbols || 0,
      last_updated: data.last_updated ?? null,
    };
  } catch (error) {
    logRequestIssue(
      'getExpectedTakeProfitSummary',
      'Handled expected take profit summary fetch failure (returning empty array)',
      error,
      'warn'
    );
    return { summary: [], total_symbols: 0, last_updated: null };
  }
}

export async function getExpectedTakeProfitDetails(symbol: string): Promise<ExpectedTPDetails | null> {
  try {
    const data = await fetchAPI<ExpectedTPDetails>(`/dashboard/expected-take-profit/${symbol}`);
    return data;
  } catch (error) {
    logRequestIssue(
      'getExpectedTakeProfitDetails',
      `Handled expected take profit details fetch failure for ${symbol}`,
      error,
      'warn'
    );
    return null;
  }
}

export async function getOrderHistory(limit: number = 100, offset: number = 0, sync: boolean = false): Promise<{ 
  orders: OpenOrder[], 
  count: number,
  total?: number,
  has_more?: boolean
}> {
  try {
    const params = new URLSearchParams({
      limit: limit.toString(),
      offset: offset.toString()
    });
    if (sync) {
      params.set('sync', 'true');
    }
    const data = await fetchAPI<{ 
      orders?: OpenOrder[]; 
      count?: number;
      total?: number;
      has_more?: boolean;
  }>(`/orders/history?${params.toString()}`);
  return { 
    orders: data.orders || [], 
    count: data.count || 0,
    total: data.total,
    has_more: data.has_more
  };
} catch (error) {
  logRequestIssue(
    'getOrderHistory',
    'Handled order history fetch failure (returning empty list)',
    error,
    'warn'
  );
  return { orders: [], count: 0 };
}
}

export async function syncOrderHistory(): Promise<{ ok: boolean; message?: string }> {
  try {
    const data = await fetchAPI<{ ok: boolean; message?: string }>('/orders/sync-history', {
      method: 'POST',
    });
    return data;
  } catch (error) {
    logRequestIssue(
      'syncOrderHistory',
      'Failed to sync order history from exchange',
      error,
      'warn'
    );
    throw error;
  }
}

export async function deleteOrder(orderId: string): Promise<{ ok: boolean; message?: string; deleted_order?: any }> {
  try {
    const data = await fetchAPI<{ ok: boolean; message?: string; deleted_order?: any }>(`/orders/${orderId}`, {
      method: 'DELETE',
    });
    return data;
  } catch (error) {
    logRequestIssue(
      'deleteOrder',
      'Failed to delete order',
      error,
      'warn'
    );
    throw error;
  }
}

export async function deleteOrderByCriteria(params: {
  symbol?: string;
  side?: string;
  price?: number;
  quantity?: number;
  date?: string;
}): Promise<{ ok: boolean; message?: string; deleted_count?: number; deleted_orders?: any[] }> {
  try {
    const queryParams = new URLSearchParams();
    if (params.symbol) queryParams.append('symbol', params.symbol);
    if (params.side) queryParams.append('side', params.side);
    if (params.price !== undefined) queryParams.append('price', params.price.toString());
    if (params.quantity !== undefined) queryParams.append('quantity', params.quantity.toString());
    if (params.date) queryParams.append('date', params.date);
    
    const data = await fetchAPI<{ ok: boolean; message?: string; deleted_count?: number; deleted_orders?: any[] }>(`/orders/by-criteria?${queryParams.toString()}`, {
      method: 'DELETE',
    });
    return data;
  } catch (error) {
    logRequestIssue(
      'deleteOrderByCriteria',
      'Failed to delete orders by criteria',
      error,
      'warn'
    );
    throw error;
  }
}

export async function updateOrderTime(
  orderId: string,
  updateTime?: string,
  createTime?: string
): Promise<{ ok: boolean; message?: string; updated_fields?: string[]; order?: any }> {
  try {
    const body: any = {};
    if (updateTime) body.update_time = updateTime;
    if (createTime) body.create_time = createTime;
    
    const data = await fetchAPI<{ ok: boolean; message?: string; updated_fields?: string[]; order?: any }>(`/orders/${orderId}/update-time`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    });
    return data;
  } catch (error) {
    logRequestIssue(
      'updateOrderTime',
      'Failed to update order time',
      error,
      'warn'
    );
    throw error;
  }
}

export async function syncOrderFromExchange(orderId: string): Promise<{ ok: boolean; message?: string; order?: any }> {
  try {
    const data = await fetchAPI<{ ok: boolean; message?: string; order?: any }>(`/orders/${orderId}/sync-from-exchange`, {
      method: 'POST',
    });
    return data;
  } catch (error) {
    logRequestIssue(
      'syncOrderFromExchange',
      'Failed to sync order from Crypto.com exchange',
      error,
      'warn'
    );
    throw error;
  }
}

// Trading
export async function executeManualTrade(trade: ManualTradeRequest): Promise<unknown> {
  const data = await fetchAPI<unknown>('/manual-trade', {
    method: 'POST',
    body: JSON.stringify(trade),
  });
  return data;
}

export async function getCurrentPrice(symbol: string): Promise<number> {
  try {
    // Use a direct fetch call to avoid error propagation from fetchAPI
    // This allows us to handle 400 errors silently (symbol not available)
    const apiUrl = getApiUrl();
    const fullUrl = `${apiUrl}/signals?exchange=CRYPTO_COM&symbol=${symbol}`;
    
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 10000); // 10 second timeout
    
    const response = await fetch(fullUrl, {
      method: 'GET',
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': 'demo-key',
      },
    });
    
    clearTimeout(timeoutId);
    
    // Handle 400 errors silently (symbol not available) - this is expected for many assets
    if (!response.ok) {
      if (response.status === 400) {
        // 400 means symbol not available - return 0 silently (don't log or throw)
        return 0;
      }
      // For other errors, return 0 but don't throw to avoid console errors
      return 0;
    }
    
    const data = await response.json();
    return data.price || 0;
  } catch {
    // Silently handle all errors - return 0 for unavailable symbols
    // This is expected behavior when fetching prices for assets not available in the API
    // Don't log or throw to avoid console spam
    return 0;
  }
}

// Portfolio
export async function getPortfolio(): Promise<PortfolioResponse> {
  try {
    const data = await fetchAPI<{ 
      portfolio?: { assets?: RawPortfolioAsset[]; total_value_usd?: number }; 
      total_usd_value?: number;
    }>('/dashboard/state');

    const normalizedAssets = normalizePortfolioAssets(data.portfolio?.assets);
    const totalUsd = data.portfolio?.total_value_usd 
      ?? data.total_usd_value 
      ?? sumAssetValues(normalizedAssets);

    return { 
      assets: normalizedAssets, 
      total_value_usd: totalUsd,
      ok: true
    };
  } catch (error) {
    logRequestIssue(
      'getPortfolio',
      'Handled portfolio fetch failure (returning empty data)',
      error,
      'warn'
    );
    return { assets: [], total_value_usd: 0, ok: false };
  }
}

// Top Coins
export async function getTopCoins(): Promise<{ coins: TopCoin[], count: number }> {
  try {
    console.log('🔄 getTopCoins: Making API call to /market/top-coins-data');
    const apiUrl = typeof window !== 'undefined' ? getApiUrl() : DEFAULT_API_URL;
    console.log('🌐 API_URL being used:', apiUrl);
    const data = await fetchAPI<{ coins?: TopCoin[]; count?: number }>('/market/top-coins-data');
    console.log('📊 getTopCoins: API response received:', data);
    const result = { coins: data.coins || [], count: data.count || 0 };
    console.log('📊 getTopCoins: Returning result:', result);
    return result;
  } catch (error) {
    logRequestIssue(
      'getTopCoins',
      'Handled top coins fetch failure',
      error,
      'warn'
    );
    throw error;
  }
}

export interface CustomTopCoinPayload {
  instrument_name: string;
  base_currency?: string;
  quote_currency?: string;
}

export async function addCustomTopCoin(payload: CustomTopCoinPayload): Promise<{ ok: boolean; instrument_name: string }> {
  const data = await fetchAPI<{ ok: boolean; instrument_name: string }>('/market/top-coins/custom', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return data;
}

export async function removeCustomTopCoin(symbol: string): Promise<{ ok: boolean; instrument_name: string }> {
  const data = await fetchAPI<{ ok: boolean; instrument_name: string }>(`/market/top-coins/custom/${symbol}`, {
    method: 'DELETE',
  });
  return data;
}

// Trading Signals
export interface TradingSignals {
  symbol: string;
  exchange: string;
  price: number;
  rsi: number;
  atr: number;
  ma50: number;
  ma200: number;
  ema10: number;
  ma10w: number;
  volume: number;
  avg_volume: number;
  volume_ratio?: number;
  min_volume_ratio?: number;  // Minimum volume ratio threshold from strategy config
  volume_24h?: number;
  current_volume?: number;
  volume_avg_periods?: number;
  res_up: number;
  res_down: number;
  signals: {
    buy: boolean;
    sell: boolean;
    tp: number | null;
    sl: number | null;
    tp_boosted: boolean;
    exhaustion: boolean;
    ma10w_break: boolean;
  };
  stop_loss_take_profit: {
    stop_loss: {
      conservative: { value: number; percentage: number };
      aggressive: { value: number; percentage: number };
    };
    take_profit: {
      conservative: { value: number; percentage: number };
      aggressive: { value: number; percentage: number };
    };
  };
  rationale: string[];
  method: string;
  strategy?: StrategyDecision;
}

export async function getTradingSignals(symbol: string, config?: {
  rsi_period?: number;
  rsi_buy_threshold?: number;
  rsi_sell_threshold?: number;
  ma50_period?: number;
  ema10_period?: number;
  ma10w_period?: number;
  atr_period?: number;
  volume_period?: number;
}): Promise<TradingSignals | null> {
  const maxRetries = 2; // Reduced from 3 to 2
  let lastError: Error | null = null;
  
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      console.log(`🔄 getTradingSignals attempt ${attempt}/${maxRetries} for ${symbol}`);
      
      // Build query parameters
      const params = new URLSearchParams({
        exchange: 'CRYPTO_COM',
        symbol: symbol
      });
      
      // Add config parameters if provided
      if (config) {
        Object.entries(config).forEach(([key, value]) => {
          if (value !== undefined) {
            params.append(key, value.toString());
          }
        });
      }
      
      const data = await fetchAPI(`/signals?${params.toString()}`);
      console.log(`✅ getTradingSignals success for ${symbol} on attempt ${attempt}`);
      // Note: fetchAPI already records success for circuit breaker, no need to do it here
      return data as TradingSignals;
    } catch (error) {
      const err = error as Error & { status?: number; retryAfterMs?: number };
      lastError = err;
      
      // Handle circuit breaker errors gracefully - don't retry or log as error
      if (err.message?.includes('Circuit breaker open')) {
        const retryAfter = err.retryAfterMs ? Math.ceil(err.retryAfterMs / 1000) : 30;
        console.debug(`⏸️ Circuit breaker open for ${symbol}, skipping fetch. Will auto-retry in ~${retryAfter}s`);
        // Return null instead of throwing - circuit breaker will auto-reset
        // Note: fetchAPI already handles circuit breaker errors, so we just return null here
        return null;
      }
      
      // Note: fetchAPI already records failure for circuit breaker (for non-circuit-breaker errors)
      
      console.warn(`⚠️ getTradingSignals attempt ${attempt}/${maxRetries} failed for ${symbol}:`, error);
      
      if (attempt < maxRetries) {
        const delay = Math.pow(2, attempt) * 1000; // Exponential backoff: 2s, 4s, 8s
        console.log(`⏳ Retrying in ${delay}ms...`);
        await new Promise(resolve => setTimeout(resolve, delay));
      }
    }
  }
  
  // Only log and throw if it's not a circuit breaker error
  if (lastError && !lastError.message?.includes('Circuit breaker open')) {
    logRequestIssue(
      `getTradingSignals:${symbol}`,
      `❌ getTradingSignals exhausted retries (${maxRetries})`,
      lastError,
      'warn'
    );
  }
  
  // Return null instead of throwing circuit breaker errors
  if (lastError?.message?.includes('Circuit breaker open')) {
    return null;
  }
  
  throw lastError;
}

export interface AlertRatio {
  ratio: number;  // 0-100 where 100 = BUY ALERT, 0 = SELL ALERT, 50 = WAIT/NEUTRAL
}

export async function getAlertRatio(symbol: string): Promise<AlertRatio | null> {
  try {
    const params = new URLSearchParams({
      symbol: symbol
    });
    
    const data = await fetchAPI(`/alert-ratio?${params.toString()}`);
    return data as AlertRatio;
  } catch (error) {
    console.warn(`⚠️ getAlertRatio failed for ${symbol}:`, error);
    return null;  // Return null on error instead of throwing
  }
}

export interface DataSourceStatusEntry {
  available: boolean;
  priority: number;
  response_time: number | null;
  last_check: string | null;
}

export type DataSourceStatus = Record<string, DataSourceStatusEntry>;

export async function getDataSourcesStatus(): Promise<DataSourceStatus | null> {
  try {
    const data = await fetchAPI<DataSourceStatus>('/data-sources/status');
    return data;
  } catch (error) {
    // Log more details about the error
    const errorMessage = error instanceof Error ? error.message : String(error);
    logRequestIssue(
      'getDataSourcesStatus',
      `🌐 Network issue while fetching data source status (${errorMessage})`,
      error,
      'warn'
    );
    
    // Return a default status object instead of null to avoid breaking the UI
    return {
      binance: {
        available: false,
        priority: 1,
        response_time: 0,
        last_check: null
      },
      kraken: {
        available: false,
        priority: 2,
        response_time: 0,
        last_check: null
      },
      crypto_com: {
        available: false,
        priority: 3,
        response_time: 0,
        last_check: null
      },
      coinpaprika: {
        available: false,
        priority: 4,
        response_time: 0,
        last_check: null
      }
    };
  }
}

// Trading Configuration APIs
export interface TradingPreset {
  RSI_PERIOD?: number;
  RSI_BUY?: number;
  RSI_SELL?: number;
  MA50?: number;
  EMA10?: number;
  MA10W?: number;
  ATR?: number;
  VOL?: number;
  [key: string]: number | string | boolean | null | undefined;
}

export interface CoinConfig {
  preset?: string;
  overrides?: Record<string, unknown>;
}

export interface StrategyRulesConfigEntry {
  notificationProfile?: string;
  rules?: Record<string, Record<string, unknown>>;
}

export interface TradingConfig {
  presets?: Record<string, TradingPreset>;
  strategy_rules?: Record<string, StrategyRulesConfigEntry>;
  coins?: Record<string, CoinConfig>;
  [key: string]: unknown;
}

export async function getTradingConfig(): Promise<TradingConfig | null> {
  try {
    const data = await fetchAPI<TradingConfig>('/config');
    return data;
  } catch (error) {
    logRequestIssue(
      'getTradingConfig',
      'Handled trading config fetch failure',
      error,
      'warn'
    );
    return null;
  }
}

export async function saveTradingConfig(config: TradingConfig): Promise<{ ok: boolean; config?: TradingConfig }> {
  try {
    const data = await fetchAPI<{ ok: boolean; config?: TradingConfig }>('/config', {
      method: 'PUT',
      body: JSON.stringify(config)
    });
    return data;
  } catch (error) {
    logRequestIssue(
      'saveTradingConfig',
      'Handled trading config save failure',
      error,
      'warn'
    );
    throw error;
  }
}

export type CoinParams = Record<string, number | string | boolean | null>;

export async function getCoinParams(symbol: string): Promise<CoinParams | null> {
  try {
    const data = await fetchAPI<CoinParams>(`/params/${symbol}`);
    return data as CoinParams;
  } catch (error) {
    logRequestIssue(
      `getCoinParams:${symbol}`,
      'Handled coin params fetch failure (returning null)',
      error,
      'warn'
    );
    return null;
  }
}

export interface CoinConfigUpdate {
  preset?: string;
  overrides?: Record<string, unknown>;
}

export async function updateCoinConfig(symbol: string, config: CoinConfigUpdate): Promise<{ ok: boolean }> {
  try {
    const data = await fetchAPI<{ ok: boolean }>(`/coins/${symbol}`, {
      method: 'PUT',
      body: JSON.stringify(config)
    });
    return data;
  } catch (error) {
    logRequestIssue(
      `updateCoinConfig:${symbol}`,
      'Handled coin config update failure',
      error,
      'warn'
    );
    throw error;
  }
}

// Update alert_enabled for watchlist item
export async function updateWatchlistAlert(
  symbol: string,
  alertEnabled: boolean,
  options?: { buyAlertEnabled?: boolean; sellAlertEnabled?: boolean }
): Promise<{
  ok: boolean;
  symbol: string;
  alert_enabled: boolean;
  buy_alert_enabled?: boolean | null;
  sell_alert_enabled?: boolean | null;
}> {
  try {
    const payload: Record<string, boolean> = {
      alert_enabled: alertEnabled,
    };
    if (options?.buyAlertEnabled !== undefined) {
      payload.buy_alert_enabled = options.buyAlertEnabled;
    }
    if (options?.sellAlertEnabled !== undefined) {
      payload.sell_alert_enabled = options.sellAlertEnabled;
    }
    const data = await fetchAPI<{
      ok?: boolean;
      symbol?: string;
      alert_enabled?: boolean;
      buy_alert_enabled?: boolean | null;
      sell_alert_enabled?: boolean | null;
    }>(`/watchlist/${symbol}/alert`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
    return {
      ok: data.ok ?? true,
      symbol: data.symbol ?? symbol,
      alert_enabled: data.alert_enabled ?? alertEnabled,
      buy_alert_enabled:
        data.buy_alert_enabled ??
        options?.buyAlertEnabled ??
        alertEnabled,
      sell_alert_enabled:
        data.sell_alert_enabled ??
        options?.sellAlertEnabled ??
        alertEnabled,
    };
  } catch (error) {
    logRequestIssue(
      `updateWatchlistAlert:${symbol}`,
      'Handled alert update failure',
      error,
      'warn'
    );
    throw error;
  }
}

export async function updateBuyAlert(symbol: string, buyAlertEnabled: boolean): Promise<{ ok: boolean; symbol: string; buy_alert_enabled: boolean; sell_alert_enabled: boolean; message?: string }> {
  try {
    const data = await fetchAPI<{
      ok?: boolean;
      symbol?: string;
      buy_alert_enabled?: boolean;
      sell_alert_enabled?: boolean;
      alert_enabled?: boolean;
      message?: string;
    }>(`/watchlist/${symbol}/buy-alert`, {
      method: 'PUT',
      body: JSON.stringify({ buy_alert_enabled: buyAlertEnabled })
    });
    return {
      ok: data.ok ?? true,
      symbol: data.symbol ?? symbol,
      buy_alert_enabled: data.buy_alert_enabled ?? buyAlertEnabled,
      sell_alert_enabled: data.sell_alert_enabled ?? data.alert_enabled ?? false,
      message: data.message
    };
  } catch (error) {
    logRequestIssue(
      `updateBuyAlert:${symbol}`,
      'Handled buy alert update failure',
      error,
      'warn'
    );
    throw error;
  }
}

export async function updateSellAlert(symbol: string, sellAlertEnabled: boolean): Promise<{ ok: boolean; symbol: string; buy_alert_enabled: boolean; sell_alert_enabled: boolean; message?: string }> {
  try {
    const data = await fetchAPI<{
      ok?: boolean;
      symbol?: string;
      buy_alert_enabled?: boolean;
      sell_alert_enabled?: boolean;
      alert_enabled?: boolean;
      message?: string;
    }>(`/watchlist/${symbol}/sell-alert`, {
      method: 'PUT',
      body: JSON.stringify({ sell_alert_enabled: sellAlertEnabled })
    });
    return {
      ok: data.ok ?? true,
      symbol: data.symbol ?? symbol,
      buy_alert_enabled: data.buy_alert_enabled ?? data.alert_enabled ?? false,
      sell_alert_enabled: data.sell_alert_enabled ?? sellAlertEnabled,
      message: data.message
    };
  } catch (error) {
    logRequestIssue(
      `updateSellAlert:${symbol}`,
      'Handled sell alert update failure',
      error,
      'warn'
    );
    throw error;
  }
}

export interface BulkUpdateAlertsResponse {
  ok: boolean;
  updated_count: number;
  total_items: number;
  buy_alert_enabled: boolean;
  sell_alert_enabled: boolean;
  trade_enabled: boolean;
  message: string;
}

export async function bulkUpdateAlerts(
  buyAlerts: boolean = true,
  sellAlerts: boolean = true,
  tradeEnabled: boolean = false
): Promise<BulkUpdateAlertsResponse> {
  try {
    const data = await fetchAPI<BulkUpdateAlertsResponse>('/dashboard/bulk-update-alerts', {
      method: 'POST',
      body: JSON.stringify({
        buy_alerts: buyAlerts,
        sell_alerts: sellAlerts,
        trade_enabled: tradeEnabled
      })
    });
    return data;
  } catch (error) {
    logRequestIssue(
      'bulkUpdateAlerts',
      'Handled bulk update alerts failure',
      error,
      'warn'
    );
    throw error;
  }
}

// Simulate alert for testing
export interface SimulateAlertResponse {
  ok: boolean;
  message: string;
  symbol: string;
  signal_type: string;
  price: number;
  alert_sent: boolean;
  order_created: boolean;
  trade_amount_usd?: number;
  alert_enabled?: boolean;
  note?: string;
  order_error?: string; // Add order_error property
}

export async function simulateAlert(symbol: string, signalType: 'BUY' | 'SELL', forceOrder: boolean = false, tradeAmountUsd?: number, tradeEnabled?: boolean): Promise<SimulateAlertResponse> {
  try {
    const payload: {
      symbol: string;
      signal_type: 'BUY' | 'SELL';
      force_order: boolean;
      trade_amount_usd?: number;
      trade_enabled?: boolean;
    } = {
      symbol,
      signal_type: signalType,
      force_order: forceOrder
    };
    
    // Only include trade_amount_usd if provided (optional - backend will use watchlist value if available)
    if (tradeAmountUsd && tradeAmountUsd > 0) {
      payload.trade_amount_usd = tradeAmountUsd;
    }
    
    // Include trade_enabled if provided (allows overriding database value)
    if (tradeEnabled !== undefined) {
      payload.trade_enabled = tradeEnabled;
    }
    
    const data = await fetchAPI<SimulateAlertResponse>('/test/simulate-alert', {
      method: 'POST',
      body: JSON.stringify(payload)
    });
    return data;
  } catch (error) {
    logRequestIssue(
      `simulateAlert:${symbol}`,
      'Handled alert simulation failure',
      error,
      'warn'
    );
    throw error;
  }
}

// Quick Order API
export interface QuickOrderRequest {
  symbol: string;
  side: 'BUY' | 'SELL';
  price: number;
  amount_usd: number;
  use_margin: boolean;
}

export interface QuickOrderResponse {
  ok: boolean;
  dry_run: boolean;
  exchange: string;
  symbol: string;
  side: string;
  type: string;
  order_id: string;
  qty: number;
  price: number;
  result: unknown;
}

export async function quickOrder(request: QuickOrderRequest): Promise<QuickOrderResponse> {
  try {
    const data = await fetchAPI<QuickOrderResponse>('/orders/quick', {
      method: 'POST',
      body: JSON.stringify(request)
    });
    return data;
  } catch (error) {
    logRequestIssue(
      'quickOrder',
      'Handled quick order failure',
      error,
      'warn'
    );
    throw error;
  }
}

// LIVE_TRADING Toggle API
export interface LiveTradingStatus {
  ok: boolean;
  live_trading_enabled: boolean;
  mode: 'LIVE' | 'DRY_RUN';
  message: string;
}

export async function getLiveTradingStatus(): Promise<LiveTradingStatus> {
  try {
    const data = await fetchAPI<LiveTradingStatus>('/trading/live-status');
    return data;
  } catch (error) {
    logRequestIssue(
      'getLiveTradingStatus',
      'Handled live trading status fetch failure',
      error,
      'warn'
    );
    throw error;
  }
}

export async function toggleLiveTrading(enabled: boolean): Promise<LiveTradingStatus> {
  try {
    const apiUrl = typeof window !== 'undefined' ? getApiUrl() : DEFAULT_API_URL;
    const fullUrl = `${apiUrl}/trading/live-toggle`;
    
    console.log('🔄 toggleLiveTrading: Making request to:', fullUrl);
    console.log('🔄 toggleLiveTrading: enabled=', enabled);
    
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 10000); // 10 second timeout
    
    const response = await fetch(fullUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ enabled }),
      signal: controller.signal,
    });
    
    clearTimeout(timeoutId);
    
    if (!response.ok) {
      let errorDetail = `HTTP error! status: ${response.status}`;
      try {
        const errorJson = await response.json();
        errorDetail = errorJson.detail || errorJson.message || errorDetail;
      } catch {
        const text = await response.text();
        errorDetail = text || errorDetail;
      }
      const error = new Error(`Network error for /trading/live-toggle: ${errorDetail}`) as Error & { status?: number };
      error.status = response.status;
      throw error;
    }
    
    const data = await response.json();
    console.log('✅ toggleLiveTrading: Success:', data);
    return data;
  } catch (error) {
    console.error('❌ toggleLiveTrading: Error details:', error);
    
    // Provide more detailed error information
    let errorMessage = 'Unknown error occurred';
    if (error instanceof Error) {
      if (error.name === 'AbortError') {
        errorMessage = 'Request timeout - backend did not respond in time';
      } else if (error.message.includes('Failed to fetch')) {
        errorMessage = 'Network error - unable to reach backend. Check:\n1. Backend is running\n2. Network connectivity\n3. CORS configuration';
      } else {
        errorMessage = error.message;
      }
    }
    
    logRequestIssue(
      'toggleLiveTrading',
      `Live trading toggle failure: ${errorMessage}`,
      error,
      'error'
    );
    
    const enhancedError = new Error(`Failed to toggle LIVE_TRADING: ${errorMessage}`) as Error & { detail?: string; message?: string; status?: number };
    if (error instanceof Error && 'status' in error) {
      enhancedError.status = (error as Error & { status?: number }).status;
    }
    enhancedError.detail = errorMessage;
    enhancedError.message = errorMessage;
    throw enhancedError;
  }
}

// Dashboard Snapshot API (fast, cached)
export async function getDashboardSnapshot(): Promise<DashboardSnapshot> {
  const startTime = Date.now();
  try {
    const snapshot = await fetchAPI<DashboardSnapshot>('/dashboard/snapshot');
    const elapsed = Date.now() - startTime;
    // Only log if there's an issue or if it's slow
    if (elapsed > 1000 || snapshot?.stale || snapshot?.empty) {
      console.debug(`📸 Snapshot loaded in ${elapsed}ms (stale: ${snapshot?.stale}, empty: ${snapshot?.empty})`);
    }
    
    if (!snapshot) {
      console.warn('⚠️ getDashboardSnapshot: Received null/undefined snapshot');
      throw new Error('No snapshot data received');
    }
    
    return snapshot;
  } catch (error) {
    const errorMsg = error instanceof Error ? error.message : String(error);
    console.error('❌ getDashboardSnapshot: Error fetching snapshot:', errorMsg);
    logRequestIssue(
      'getDashboardSnapshot',
      `Dashboard snapshot fetch failure: ${errorMsg}`,
      error,
      'warn'
    );
    // Return empty snapshot on error
    return {
      data: {
        balances: [],
        fast_signals: [],
        slow_signals: [],
        open_orders: [],
        last_sync: null,
        partial: true,
        errors: [`FETCH_FAILED: ${errorMsg}`],
        bot_status: {
          is_running: true,
          status: 'running',
          reason: 'Status unavailable (checking...)'
        }
      },
      last_updated_at: null,
      stale_seconds: null,
      stale: true,
      empty: true
    };
  }
}

// Unified Dashboard State API (legacy - kept for debug/internal use)
export async function getDashboardState(): Promise<DashboardState> {
  const startTime = Date.now();
  try {
    const data = await fetchAPI<DashboardState>('/dashboard/state');
    const elapsed = Date.now() - startTime;
    // Only log if there's an issue or if it's very slow
    if (elapsed > 60000 || data?.errors?.length) {
      console.warn(`⚠️ Dashboard state loaded in ${elapsed}ms (errors: ${data?.errors?.length || 0})`);
    }
    
    // Log sample balance for debugging
    if (data?.balances && data.balances.length > 0) {
      console.log('📊 Sample balance:', data.balances[0]);
    }
    
    if (!data) {
      console.warn('⚠️ getDashboardState: Received null/undefined data, returning empty state');
      return {
        balances: [],
        fast_signals: [],
        slow_signals: [],
        open_orders: [],
        last_sync: null,
        bot_status: {
          is_running: false,
          status: 'stopped',
          reason: null
        }
      };
    }
    
    const normalizedBalances = Array.isArray(data.balances)
      ? data.balances
          .map(balance => normalizeDashboardBalance(balance as RawDashboardBalance))
          .filter((balance): balance is DashboardBalance => Boolean(balance))
      : [];

    const normalizedPortfolioAssets = normalizePortfolioAssets(data.portfolio?.assets as RawPortfolioAsset[] | undefined);
    const balancesUsdTotal = normalizedBalances.reduce(
      (sum, balance) => sum + coerceNumber(balance.usd_value ?? balance.market_value),
      0
    );
    const portfolioUsdTotal = sumAssetValues(normalizedPortfolioAssets);
    const balancesTotalFallback = balancesUsdTotal !== 0 ? balancesUsdTotal : undefined;
    const portfolioTotalFallback = portfolioUsdTotal !== 0 ? portfolioUsdTotal : undefined;
    const totalUsdValue = data.total_usd_value ?? balancesTotalFallback ?? portfolioTotalFallback ?? 0;

    const normalizedPortfolio = (data.portfolio || normalizedPortfolioAssets.length > 0)
      ? {
          ...(data.portfolio ?? {}),
          assets: normalizedPortfolioAssets,
          total_value_usd: data.portfolio?.total_value_usd ?? portfolioTotalFallback ?? totalUsdValue,
        }
      : undefined;

    return {
      ...data,
      balances: normalizedBalances,
      total_usd_value: totalUsdValue,
      portfolio: normalizedPortfolio,
    };
  } catch (error) {
    const errorMsg = error instanceof Error ? error.message : String(error);
    console.error('❌ getDashboardState: Error fetching dashboard state:', errorMsg);
    logRequestIssue(
      'getDashboardState',
      `Dashboard state fetch failure: ${errorMsg}`,
      error,
      'error'  // Changed from 'warn' to 'error' to make it more visible
    );
    // Return empty state on error - but preserve last known bot status if available
    // Don't assume bot is stopped on transient errors
    return {
      balances: [],
      fast_signals: [],
      slow_signals: [],
      open_orders: [],
      last_sync: null,
      partial: true,
      errors: [`FETCH_FAILED: ${errorMsg}`],
      // Don't mark bot as stopped on transient errors - let frontend preserve last known status
      // The frontend should handle this gracefully and not show "Bot Detenido" immediately
      bot_status: {
        is_running: true,  // Assume running on error (optimistic) - frontend can check last_sync
        status: 'running',
        reason: 'Status unavailable (checking...)'
      }
    };
  }
}

// Monitoring API
export interface MonitoringSummary {
  active_alerts: number;
  active_total?: number;
  window_minutes?: number;
  generated_at_utc?: string;  // ISO timestamp with Z suffix
  backend_health: 'healthy' | 'degraded' | 'unhealthy' | 'error';
  last_sync_seconds: number | null;
  portfolio_state_duration: number;
  open_orders: number;
  balances: number;
  scheduler_ticks: number;
  errors: string[];
  last_backend_restart: number | null;
  backend_restart_status?: 'restarting' | 'restarted' | 'failed' | null;
  backend_restart_timestamp?: number | null;
  signals_last_calculated?: string | null;  // ISO timestamp when signals were last calculated
  alerts: Array<{
    type: string;
    symbol: string;
    message: string;
    timestamp: string;
    severity: string;
    alert_status?: string;
    status_label?: string;
    decision_type?: string;
    reason_code?: string;
    reason_message?: string;
    message_id?: number;
    order_intent_status?: string;
  }>;
  alert_counts?: {
    sent: number;
    blocked: number;
    failed: number;
  };
  active_signals_count?: number;  // NEW: Current signal state count (always === active_signals.length)
  active_signals?: Array<{  // NEW: Current signal state list (not events - see Active Alerts for events)
    symbol: string;  // Always present, non-empty
    decision: 'BUY' | 'SELL';  // Always "BUY" or "SELL" (never "WAIT")
    strategy_key?: string | null;  // Strategy identifier (e.g., "swing-conservative") or null
    last_price?: number | null;  // Last known price or null if unavailable
    timestamp: string;  // ISO timestamp (always present)
  }>;
}

export interface TelegramMessage {
  message: string;
  symbol: string | null;
  blocked: boolean;
  order_skipped: boolean;
  timestamp: string;
  throttle_status?: string | null;
  throttle_reason?: string | null;
  // Decision tracing fields (new)
  decision_type?: string | null;  // "SKIPPED" or "FAILED"
  reason_code?: string | null;  // Canonical reason code (e.g., "TRADE_DISABLED", "EXCHANGE_REJECTED")
  reason_message?: string | null;  // Human-readable reason message
  context_json?: Record<string, any> | null;  // Contextual data (prices, balances, thresholds, etc.)
  exchange_error_snippet?: string | null;  // Raw exchange error message for FAILED decisions
  correlation_id?: string | null;  // Correlation ID for tracing across logs
}

export interface TelegramMessagesResponse {
  messages: TelegramMessage[];
  total: number;
}

export interface SignalThrottleEntry {
  symbol: string;
  strategy_key: string;
  side: string;
  last_price: number | null;
  last_time: string | null;
  seconds_since_last: number | null;
  price_change_pct: number | null;
  emit_reason: string | null;
  telegram_message?: string | null;  // Full Telegram message
}

export async function getMonitoringSummary(forceRefresh: boolean = false): Promise<MonitoringSummary> {
  try {
    const queryParam = forceRefresh ? '?force_refresh=true' : '';
    // Add cache-busting to prevent stale data
    const data = await fetchAPI<MonitoringSummary>(`/monitoring/summary${queryParam}`, {
      cache: 'no-store',
      headers: {
        'Cache-Control': 'no-cache',
      },
    });
    return data;
  } catch (error) {
    const errorMsg = error instanceof Error ? error.message : String(error);
    console.error('❌ getMonitoringSummary: Error fetching monitoring summary:', errorMsg);
    logRequestIssue(
      'getMonitoringSummary',
      `Monitoring summary fetch failure: ${errorMsg}`,
      error,
      'warn'
    );
    return {
      active_alerts: 0,
      backend_health: 'error',
      last_sync_seconds: null,
      portfolio_state_duration: 0,
      open_orders: 0,
      balances: 0,
      scheduler_ticks: 0,
      errors: [errorMsg],
      last_backend_restart: null,
      backend_restart_status: null,
      backend_restart_timestamp: null,
      signals_last_calculated: null,
      alerts: []
    };
  }
}

export async function getTelegramMessages(): Promise<TelegramMessagesResponse> {
  try {
    const data = await fetchAPI<TelegramMessagesResponse>('/monitoring/telegram-messages');
    return data;
  } catch (error) {
    const errorMsg = error instanceof Error ? error.message : String(error);
    console.error('❌ getTelegramMessages: Error fetching Telegram messages:', errorMsg);
    return {
      messages: [],
      total: 0
    };
  }
}

export interface Workflow {
  id: string;
  name: string;
  description: string;
  automated: boolean;
  schedule: string;
  run_endpoint?: string | null;  // If null, workflow cannot be run manually
  last_execution?: string | null;
  last_status: string;
  last_report?: string | null;
  last_error?: string | null;
}

export interface WorkflowsResponse {
  workflows: Workflow[];
}

export async function getWorkflows(): Promise<WorkflowsResponse> {
  // Force real-time status (avoid stale browser cache)
  const cacheBust = `?_ts=${Date.now()}`;
  return fetchAPI<WorkflowsResponse>(`/monitoring/workflows${cacheBust}`, { cache: 'no-store' });
}

export async function getSignalThrottleState(limit = 200): Promise<SignalThrottleEntry[]> {
  try {
    const query = limit ? `?limit=${limit}` : '';
    const data = await fetchAPI<SignalThrottleEntry[]>(`/monitoring/signal-throttle${query}`);
    return Array.isArray(data) ? data : [];
  } catch (error) {
    const errorMsg = error instanceof Error ? error.message : String(error);
    console.error('❌ getSignalThrottleState: Error fetching throttle data:', errorMsg);
    return [];
  }
}

export interface RestartBackendResponse {
  ok: boolean;
  status: 'restarting' | 'restarted' | 'failed';
  message: string;
}

export async function restartBackend(): Promise<RestartBackendResponse> {
  try {
    const data = await fetchAPI<RestartBackendResponse>('/monitoring/backend/restart', {
      method: 'POST',
    });
    return data;
  } catch (error) {
    const errorMsg = error instanceof Error ? error.message : String(error);
    console.error('❌ restartBackend: Error restarting backend:', errorMsg);
    logRequestIssue(
      'restartBackend',
      `Backend restart failure: ${errorMsg}`,
      error,
      'error'
    );
    throw error;
  }
}

export interface SystemHealth {
  global_status: 'PASS' | 'WARN' | 'FAIL';
  timestamp: string;
  market_data: {
    status: 'PASS' | 'FAIL';
    fresh_symbols: number;
    stale_symbols: number;
    max_age_minutes: number | null;
  };
  market_updater: {
    status: 'PASS' | 'FAIL';
    is_running: boolean;
    last_heartbeat_age_minutes: number | null;
  };
  signal_monitor: {
    status: 'PASS' | 'FAIL';
    is_running: boolean;
    last_cycle_age_minutes: number | null;
  };
  telegram: {
    status: 'PASS' | 'FAIL';
    enabled: boolean;
    chat_id_set: boolean;
    last_send_ok: boolean | null;
  };
  trade_system: {
    status: 'PASS' | 'WARN' | 'FAIL';
    open_orders: number;
    max_open_orders: number | null;
    last_check_ok: boolean | null;
  };
}

export async function getSystemHealth(): Promise<SystemHealth> {
  const cacheBust = `?_ts=${Date.now()}`;
  return fetchAPI<SystemHealth>(`/health/system${cacheBust}`, { cache: 'no-store' });
}

export interface TestTelegramResponse {
  ok: boolean;
  error?: string;
}

/** Missing-secret recovery (GET /api/settings/secrets-status) */
export interface SecretMissingItem {
  id: string;
  env_var: string;
  blocked_service: string;
  why: string;
  ssm_parameter_name: string | null;
}

export interface AutomationReadinessPayload {
  applicable: boolean;
  overall?: 'ok' | 'action_required';
  missing?: SecretMissingItem[];
  note?: string;
}

export interface SecretsStatusResponse {
  overall: 'ok' | 'action_required';
  missing: SecretMissingItem[];
  skipped_count: number;
  context: {
    atp_trading_only: boolean;
    environment: string;
    aws: boolean;
    github_legacy_pat_active: boolean;
  };
  /** While ATP_TRADING_ONLY=1: secrets still needed before switching to automation. Omitted by older backends. */
  automation_readiness?: AutomationReadinessPayload;
}

export async function getSecretsStatus(adminKey: string): Promise<SecretsStatusResponse> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (adminKey.trim()) {
    headers['X-Admin-Key'] = adminKey.trim();
  }
  const res = await fetch(`${DEFAULT_API_URL}/api/settings/secrets-status`, {
    method: 'GET',
    headers,
    cache: 'no-store',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || `HTTP ${res.status}`);
  }
  return res.json() as Promise<SecretsStatusResponse>;
}

export interface SecretIntakeResponse {
  status: string;
  env_var: string;
  persisted_to: string[];
  ssm: { status: string; parameter: string | null; detail: string | null };
  container_restart_required: boolean;
  process_env_unchanged_until_restart: boolean;
  message: string;
  recovery?: {
    auto_restart_available: boolean;
    apply_recovery_path: string;
    allowed_target: string;
  };
}

export interface RecoveryStatusPayload {
  auto_restart_enabled: boolean;
  compose_project_configured: boolean;
  recovery_runnable: boolean;
  allowed_target: string;
}

export async function getRecoveryStatus(adminKey: string): Promise<RecoveryStatusPayload> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (adminKey.trim()) {
    headers['X-Admin-Key'] = adminKey.trim();
  }
  const res = await fetch(`${DEFAULT_API_URL}/api/settings/recovery-status`, {
    method: 'GET',
    headers,
    cache: 'no-store',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || `HTTP ${res.status}`);
  }
  return res.json() as Promise<RecoveryStatusPayload>;
}

export interface ApplyRecoveryResponse {
  status: string;
  target: string;
  message: string;
}

export async function applyBackendRecovery(adminKey: string): Promise<ApplyRecoveryResponse> {
  const res = await fetch(`${DEFAULT_API_URL}/api/settings/apply-recovery`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Admin-Key': adminKey.trim(),
    },
    body: JSON.stringify({ target: 'backend-aws' }),
    cache: 'no-store',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || `HTTP ${res.status}`);
  }
  return res.json() as Promise<ApplyRecoveryResponse>;
}

export async function submitSecretIntake(
  adminKey: string,
  envVar: string,
  value: string,
  persistSsm: boolean = true
): Promise<SecretIntakeResponse> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Admin-Key': adminKey.trim(),
  };
  const res = await fetch(`${DEFAULT_API_URL}/api/settings/secrets-intake`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ env_var: envVar, value, persist_ssm: persistSsm }),
    cache: 'no-store',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || `HTTP ${res.status}`);
  }
  return res.json() as Promise<SecretIntakeResponse>;
}

export async function testTelegram(adminKey: string): Promise<TestTelegramResponse> {
  try {
    const response = await fetch(`${DEFAULT_API_URL}/api/admin/test-telegram`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Admin-Key': adminKey,
      },
      cache: 'no-store',
    });

    if (response.status === 401) {
      return { ok: false, error: 'unauthorized' };
    }

    if (response.status === 429) {
      const data = await response.json();
      return { ok: false, error: data.detail || 'rate_limited' };
    }

    if (!response.ok) {
      const data = await response.json();
      return { ok: false, error: data.error || data.detail || 'unknown_error' };
    }

    const data = await response.json();
    return data;
  } catch (error) {
    const errorMsg = error instanceof Error ? error.message : String(error);
    console.error('❌ testTelegram: Error:', errorMsg);
    return { ok: false, error: errorMsg };
  }
}
