import { getApiUrl } from '@/lib/environment';

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
  alert_enabled?: boolean;  // Enable automatic alerts and order creation
  buy_alert_enabled?: boolean;  // Enable BUY alerts specifically
  sell_alert_enabled?: boolean;  // Enable SELL alerts specifically
  sl_tp_mode?: string;
  min_price_change_pct?: number | null;
  sl_percentage?: number | null;
  tp_percentage?: number | null;
  sl_price?: number;
  tp_price?: number;
  strategy_key?: string | null;
  strategy_preset?: string | null;
  strategy_risk?: string | null;
  order_status?: string;
  price?: number;
  rsi?: number;
  ma50?: number;
  ma200?: number;
  ema10?: number;
  atr?: number;
  res_up?: number;
  res_down?: number;
  signals?: TradingSignals;
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
  create_time: number;
  update_time: number;
  imported_at?: number | null; // Timestamp when order was imported from CSV
  cumulative_quantity?: string | null;
  cumulative_value?: string | null;
  avg_price?: string | null;
  trigger_condition?: string | null; // Trigger condition for stop/limit orders
  filled_quantity?: string | null; // Filled quantity for executed orders
  filled_price?: string | null; // Filled price for executed orders
  order_role?: string;  // Order role (STOP_LOSS, TAKE_PROFIT, etc.)
  parent_order_id?: string | null;
  has_linked_tp?: boolean | null;
  has_linked_sl?: boolean | null;
  is_orphan?: boolean;
  is_trigger?: boolean; // True if from get-trigger-orders / advanced trigger list
  trigger_price?: number | null; // Trigger price for TP/SL orders
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
  usd_value?: number;  // Alternative field from Crypto.com API
  updated_at: string;
  tp?: number;  // Take profit price
  sl?: number;  // Stop loss price
  // Per-coin unrealized P&L vs cost basis (from filled BUY orders).
  // When cost_basis_unknown is true, pnl fields are null and the UI renders "—".
  avg_buy_price?: number | null;
  pnl_pct?: number | null;  // (current_price - avg_buy_price) / avg_buy_price * 100
  net_profit_usd?: number | null;  // balance * (current_price - avg_buy_price)
  cost_basis_unknown?: boolean;
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
  ma10w?: number;  // 10-week moving average
  atr?: number;
  avg_volume?: number;
  volume_ratio?: number;
  current_volume?: number;
  volume_avg_periods?: number;  // Volume average periods
  // Resistance levels
  res_up?: number;
  res_down?: number;
  // Strategy-related fields
  strategy?: string;  // Strategy type (swing, scalp, etc.)
  strategy_state?: string;  // Strategy state
  strategy_key?: string | null;
  strategy_preset?: string | null;
  strategy_risk?: string | null;
  sl_price?: number;
  tp_price?: number;
  trade_enabled?: boolean;
  trade_on_margin?: boolean;
  trade_amount_usd?: number | null;
  sl_tp_mode?: string;
  sl_percentage?: number | null;
  tp_percentage?: number | null;
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
  currency?: string;  // Currency code
  coin?: string;  // Alternative to asset (used in some API responses)
  tp?: number;  // Take profit price
  sl?: number;  // Stop loss price
}

export interface DashboardSignal {
  symbol: string;
  preset: string | null;
  sl_profile: string | null;
  rsi: number | null;
  ma50: number | null;
  ma200: number | null;
  ema10: number | null;
  ma10w: number | null;
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

export interface OpenOrdersSyncMeta {
  source?: string;
  last_updated?: string | null;
  sync_status?: 'ok' | 'failed_auth' | 'missing_credentials' | 'api_error' | 'stale' | 'skipped';
  error_code?: number | null;
  error_message?: string | null;
  data_verified?: boolean;
}

export interface DashboardState {
  source?: string;  // "crypto.com" when using direct API values
  total_usd_value?: number;  // Total USD value from Crypto.com
  balances: DashboardBalance[];
  fast_signals: DashboardSignal[];
  slow_signals: DashboardSignal[];
  open_orders: DashboardOrder[];
  open_position_counts?: { [symbol: string]: number };
  open_orders_summary?: UnifiedOpenOrder[] | OpenOrdersSummary;
  open_orders_sync_status?: OpenOrdersSyncMeta['sync_status'];
  open_orders_data_verified?: boolean;
  last_sync: string | null;
  portfolio?: {
    assets?: PortfolioAsset[];
    total_value_usd?: number;
    total_assets_usd?: number;
    total_collateral_usd?: number;
    total_borrowed_usd?: number;
    portfolio_value_source?: string;
  };
  bot_status: {
    is_running: boolean;
    status: 'running' | 'stopped';
    reason: string | null;
  };
  errors?: string[];  // Optional errors array
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
  sl_percentage?: number | null;
  tp_percentage?: number | null;
  sl_price?: number;
  tp_price?: number;
  strategy_key?: string | null;
  strategy_preset?: string | null;
  strategy_risk?: string | null;
  alert_cooldown_minutes?: number | null;  // Alert cooldown in minutes (nullable)
  id?: number;  // Optional ID field
  message?: string;  // Optional message field
}

// Circuit breaker for signals endpoint
let signalsFailureCount = 0;
let signalsLastFailureTime = 0;
const MAX_FAILURES = 5;
const CIRCUIT_BREAKER_TIMEOUT = 30000; // 30 seconds
const ERROR_LOG_SUPPRESSION_MS = 30000; // Deduplicate identical errors within 30s

const errorLogTimestamps = new Map<string, number>();

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
    console.log('🌐 fetchAPI: Making request to:', fullUrl);
    console.log('🌐 API_URL:', apiUrl);
    console.log('🌐 endpoint:', endpoint);
    console.log('🌐 window.location.hostname:', typeof window !== 'undefined' ? window.location.hostname : 'server-side');
    
        // Create an AbortController for timeout
        // Signals, top-coins-data, dashboard/state, and orders/history endpoints can take longer due to multi-source price fetching or database queries
        let timeoutMs = 30000; // Default 30s
        if (endpoint.includes('/signals')) {
          timeoutMs = 15000; // 15s for signals (backend has 8s timeout, so 15s frontend timeout is safe)
        } else if (endpoint.includes('/market/top-coins-data')) {
          timeoutMs = 60000; // 60s for top-coins-data (increased to allow for database queries and external API delays)
        } else if (endpoint.includes('/dashboard/state')) {
          timeoutMs = 180000; // 180s (3 minutes) for dashboard/state - backend can take 50-70s, so we need generous timeout
        } else if (endpoint.includes('/orders/history')) {
          timeoutMs = 60000; // 60s for orders/history (database query with pagination)
        } else if (endpoint.includes('/test/simulate-alert')) {
          timeoutMs = 60000; // 60s for simulate-alert (needs to create order, may take time)
        } else if (endpoint.includes('/watchlist/') && endpoint.includes('/alert')) {
          timeoutMs = 15000; // 15s for watchlist alert updates (increased from 10s to allow for network delays)
        } else if (endpoint.includes('/market/top-coins/custom')) {
          timeoutMs = 30000; // 30s for adding custom coins (database operations)
        }
        const controller = new AbortController();
        const timeoutId = setTimeout(() => {
          console.warn(`⏰ Timeout activado para ${endpoint} después de ${timeoutMs}ms`);
          controller.abort();
        }, timeoutMs);
    
    console.log(`🔄 Iniciando fetch para ${endpoint} con timeout de ${timeoutMs}ms`);
    const fetchStartTime = Date.now();
    const response = await fetch(fullUrl, {
      ...options,
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': 'demo-key', // Add authentication header
        ...options?.headers,
      },
    });
    
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
          } else if (endpoint.includes('/dashboard/state')) {
            timeoutSeconds = 180; // 180s for dashboard/state (matches timeoutMs)
          } else if (endpoint.includes('/orders/history')) {
            timeoutSeconds = 60;
          } else if (endpoint.includes('/test/simulate-alert')) {
            timeoutSeconds = 60; // 60s for simulate-alert (matches timeoutMs)
          } else if (endpoint.includes('/watchlist/') && endpoint.includes('/alert')) {
            timeoutSeconds = 10; // 10s for watchlist alert updates (matches timeoutMs)
          } else if (endpoint.includes('/market/top-coins/custom')) {
            timeoutSeconds = 30; // 30s for adding custom coins (matches timeoutMs)
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
    return data || [];
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

export async function updateDashboardItem(id: number, item: Partial<WatchlistItem>): Promise<WatchlistItem> {
  const data = await fetchAPI<WatchlistItem>(`/dashboard/${id}`, {
    method: 'PUT',
    body: JSON.stringify(item),
  });
  return data;
}

// Save coin settings by symbol
// Finds the watchlist item by symbol and updates it with the provided settings
function symbolMatchesWatchlistItem(requested: string, itemSymbol: string): boolean {
  const normalized = requested.toUpperCase();
  const item = itemSymbol.toUpperCase();
  if (item === normalized) return true;
  if (normalized.endsWith('_USD') && item === normalized.replace('_USD', '_USDT')) return true;
  if (normalized.endsWith('_USDT') && item === normalized.replace('_USDT', '_USD')) return true;
  return false;
}

function selectCanonicalWatchlistItem(items: WatchlistItem[]): WatchlistItem | undefined {
  if (items.length === 0) return undefined;
  if (items.length === 1) return items[0];

  const nonDeleted = items.filter(item => !item.is_deleted);
  const candidates = nonDeleted.length > 0 ? nonDeleted : items;

  return [...candidates].sort((a, b) => {
    const aAlert = a.alert_enabled ? 0 : 1;
    const bAlert = b.alert_enabled ? 0 : 1;
    if (aAlert !== bAlert) return aAlert - bAlert;

    const aTime = a.updated_at || a.created_at || '';
    const bTime = b.updated_at || b.created_at || '';
    const aTimestamp = aTime ? new Date(aTime).getTime() : 0;
    const bTimestamp = bTime ? new Date(bTime).getTime() : 0;
    if (aTimestamp !== bTimestamp) return bTimestamp - aTimestamp;

    return (b.id || 0) - (a.id || 0);
  })[0];
}

export async function saveCoinSettings(symbol: string, settings: Partial<CoinSettings>): Promise<CoinSettings> {
  try {
    const normalizedSymbol = symbol.toUpperCase();
    const dashboard = await getDashboard();
    const matchingItems = dashboard.filter(item =>
      symbolMatchesWatchlistItem(normalizedSymbol, item.symbol || '')
    );
    const item = selectCanonicalWatchlistItem(matchingItems);
    
    if (!item) {
      throw new Error(`Watchlist item not found for symbol: ${symbol}`);
    }
    
    // Convert CoinSettings to WatchlistItem format (handle null values and type mismatches)
    const watchlistUpdate: Partial<WatchlistItem> = {};
    
    // Map only valid WatchlistItem fields
    if (settings.symbol !== undefined) watchlistUpdate.symbol = settings.symbol;
    if (settings.exchange !== undefined) watchlistUpdate.exchange = settings.exchange;
    if (settings.trade_enabled !== undefined) watchlistUpdate.trade_enabled = settings.trade_enabled;
    if (settings.trade_amount_usd !== undefined && settings.trade_amount_usd !== null) {
      watchlistUpdate.trade_amount_usd = settings.trade_amount_usd;
    } else if (settings.trade_amount_usd === null) {
      watchlistUpdate.trade_amount_usd = undefined;
    }
    if (settings.trade_on_margin !== undefined) watchlistUpdate.trade_on_margin = settings.trade_on_margin;
    if (settings.alert_enabled !== undefined) watchlistUpdate.alert_enabled = settings.alert_enabled;
    if (settings.buy_alert_enabled !== undefined) watchlistUpdate.buy_alert_enabled = settings.buy_alert_enabled;
    if (settings.sell_alert_enabled !== undefined) watchlistUpdate.sell_alert_enabled = settings.sell_alert_enabled;
    if (settings.sl_tp_mode !== undefined) watchlistUpdate.sl_tp_mode = settings.sl_tp_mode;
    if (settings.min_price_change_pct !== undefined) watchlistUpdate.min_price_change_pct = settings.min_price_change_pct;
    if (settings.sl_percentage !== undefined) watchlistUpdate.sl_percentage = settings.sl_percentage;
    if (settings.tp_percentage !== undefined) watchlistUpdate.tp_percentage = settings.tp_percentage;
    if (settings.sl_price !== undefined) watchlistUpdate.stop_loss = settings.sl_price;
    if (settings.tp_price !== undefined) watchlistUpdate.take_profit = settings.tp_price;
    
    // Update the item using the existing updateDashboardItem function
    const updated = await updateDashboardItem(item.id, watchlistUpdate);
    
    // Return the updated settings in CoinSettings format
    return {
      symbol: updated.symbol,
      exchange: updated.exchange,
      trade_enabled: updated.trade_enabled,
      trade_amount_usd: updated.trade_amount_usd,
      trade_on_margin: updated.trade_on_margin,
      alert_enabled: updated.alert_enabled,
      buy_alert_enabled: updated.buy_alert_enabled,
      sell_alert_enabled: updated.sell_alert_enabled,
      sl_tp_mode: updated.sl_tp_mode,
      min_price_change_pct: updated.min_price_change_pct,
      sl_percentage: updated.sl_percentage,
      tp_percentage: updated.tp_percentage,
      sl_price: updated.stop_loss,
      tp_price: updated.take_profit,
      strategy_key: updated.strategy_key,
      strategy_preset: updated.strategy_preset,
      strategy_risk: updated.strategy_risk,
    };
  } catch (error) {
    logRequestIssue(
      `saveCoinSettings:${symbol}`,
      'Handled coin settings save failure',
      error,
      'warn'
    );
    throw error;
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
export async function getOpenOrders(): Promise<{ orders: OpenOrder[]; count: number } & OpenOrdersSyncMeta> {
  try {
    const data = await fetchAPI<{ orders?: OpenOrder[]; count?: number } & OpenOrdersSyncMeta>('/orders/open');
    return {
      orders: data.orders || [],
      count: data.count || 0,
      source: data.source,
      last_updated: data.last_updated ?? null,
      sync_status: data.sync_status,
      error_code: data.error_code,
      error_message: data.error_message,
      data_verified: data.data_verified,
    };
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

export async function getOrderHistory(
  limit: number = 100,
  offset: number = 0,
  sync: boolean = false
): Promise<{
  orders: OpenOrder[];
  count: number;
  total?: number;
  has_more?: boolean;
}> {
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
export async function getPortfolio(): Promise<{ assets: PortfolioAsset[], total_value_usd: number }> {
  try {
    // Use /dashboard/state endpoint which uses PostgreSQL with up-to-date portfolio data
    // instead of /assets which uses outdated SQLite database
    const data = await fetchAPI<{ portfolio?: { assets?: PortfolioAsset[]; total_value_usd?: number } }>('/dashboard/state');
    const portfolio = data.portfolio || {};
    return { 
      assets: portfolio.assets || [], 
      total_value_usd: portfolio.total_value_usd || 0 
    };
  } catch (error) {
    logRequestIssue(
      'getPortfolio',
      'Handled portfolio fetch failure (returning empty data)',
      error,
      'warn'
    );
    return { assets: [], total_value_usd: 0 };
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
  volume_24h?: number;
  current_volume?: number;
  volume_avg_periods?: number;  // Volume average periods
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
  strategy?: string;  // Strategy type
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

export interface TradingConfig {
  presets?: Record<string, TradingPreset>;
  coins?: Record<string, CoinConfig>;
  trading_limits?: {
    maxOpenOrdersTotal?: number;
    maxOpenOrdersPerCoin?: number;
  };
  strategy_rules?: Record<string, unknown>;
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

export interface SaveTradingConfigResponse {
  ok: boolean;
  config?: TradingConfig;  // Optional: backend returns normalized config that was saved
}

export async function saveTradingConfig(config: TradingConfig): Promise<SaveTradingConfigResponse> {
  try {
    const data = await fetchAPI<SaveTradingConfigResponse>('/config', {
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
export async function updateWatchlistAlert(symbol: string, alertEnabled: boolean): Promise<{ ok: boolean; symbol: string; alert_enabled: boolean }> {
  try {
    const data = await fetchAPI<{ ok: boolean; symbol: string; alert_enabled: boolean }>(`/watchlist/${symbol}/alert`, {
      method: 'PUT',
      body: JSON.stringify({ alert_enabled: alertEnabled })
    });
    return data;
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

// Update buy_alert_enabled for watchlist item
export async function updateBuyAlert(symbol: string, buyAlertEnabled: boolean): Promise<{ ok: boolean; symbol: string; buy_alert_enabled: boolean; alert_enabled: boolean; message: string }> {
  try {
    const data = await fetchAPI<{ ok: boolean; symbol: string; buy_alert_enabled: boolean; alert_enabled: boolean; message: string }>(`/watchlist/${symbol}/buy-alert`, {
      method: 'PUT',
      body: JSON.stringify({ buy_alert_enabled: buyAlertEnabled })
    });
    return data;
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

// Update sell_alert_enabled for watchlist item
export async function updateSellAlert(symbol: string, sellAlertEnabled: boolean): Promise<{ ok: boolean; symbol: string; sell_alert_enabled: boolean; alert_enabled: boolean; message: string }> {
  try {
    const data = await fetchAPI<{ ok: boolean; symbol: string; sell_alert_enabled: boolean; alert_enabled: boolean; message: string }>(`/watchlist/${symbol}/sell-alert`, {
      method: 'PUT',
      body: JSON.stringify({ sell_alert_enabled: sellAlertEnabled })
    });
    return data;
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
    
    // Include trade_enabled if provided
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

export async function fixBackendHealth(): Promise<{ ok: boolean; message?: string; error?: string }> {
  try {
    const data = await fetchAPI<{ ok: boolean; message?: string; error?: string }>('/health/fix', {
      method: 'POST',
    });
    return data;
  } catch (error) {
    logRequestIssue(
      'fixBackendHealth',
      'Failed to fix backend health',
      error,
      'error'
    );
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
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
        'x-api-key': 'demo-key',
      },
      body: JSON.stringify({ enabled }),
      signal: controller.signal,
    });
    
    clearTimeout(timeoutId);
    
    if (!response.ok) {
      // Read body ONCE as text, then try to parse JSON
      const raw = await response.text();
      let parsed: unknown = null;
      try {
        parsed = raw ? JSON.parse(raw) : null;
      } catch {
        parsed = null;
      }
      let errorDetail: string | undefined;
      if (parsed && typeof parsed === 'object' && parsed !== null) {
        const parsedObj = parsed as { error?: string; detail?: string; message?: string };
        errorDetail = parsedObj.error || parsedObj.detail || parsedObj.message;
      }
      errorDetail = errorDetail || raw || `HTTP error! status: ${response.status}`;
      const error = new Error(`Network error for /trading/live-toggle: ${errorDetail}`) as Error & { status?: number };
      error.status = response.status;
      throw error;
    }
    
    // Success path: read once as text, then parse safely
    const raw = await response.text();
    let data: unknown = null;
    try {
      data = raw ? JSON.parse(raw) : null;
    } catch {
      data = { success: false, error: 'invalid JSON from server' };
    }
    console.log('✅ toggleLiveTrading: Success:', data);
    return data as LiveTradingStatus;
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

// Unified Dashboard State API
export async function getDashboardState(): Promise<DashboardState> {
  try {
    console.log('🔍 getDashboardState: Calling /dashboard/state endpoint...');
    const data = await fetchAPI<DashboardState>('/dashboard/state');
    console.log('✅ getDashboardState: Received response:', {
      source: data?.source,
      balancesCount: data?.balances?.length || 0,
      totalUsd: data?.total_usd_value,
      hasPortfolio: !!data?.portfolio,
      portfolioAssetsCount: data?.portfolio?.assets?.length || 0
    });
    
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
    
    return data;
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

// Note: UnifiedOpenOrder interface is defined later (around line 1718) with the complete backend type

export interface OpenPosition {
  symbol: string;
  baseOrderId: string;
  baseSide: 'BUY' | 'SELL';
  baseQuantity: number;
  basePrice: number | null;
  baseTotal: number | null;
  baseCreatedAt: string;
  netOpenQuantity: number;
  positionQuantity: number;
  tpCount: number;
  slCount: number;
  tpPrice: number | null;
  slPrice: number | null;
  tpProfit: number | null;
  slProfit: number | null;
  childOrders: Array<{
    orderId: string;
    side: 'BUY' | 'SELL';
    type: 'TAKE_PROFIT' | 'STOP_LOSS' | 'SELL';
    quantity: number;
    price: number | null;
    createdAt: string;
  }>;
}

// Note: ExpectedTPSummary, ExpectedTPDetails, TelegramMessage, and StrategyDecision interfaces
// are defined later (around line 1600+) with proper implementations that match the API

// Dashboard Snapshot API
export interface DashboardSnapshot {
  data: DashboardState;
  last_updated_at: string | null;
  stale_seconds: number | null;
  stale: boolean;
  empty?: boolean;
}

export async function getDashboardSnapshot(): Promise<DashboardSnapshot> {
  try {
    const data = await fetchAPI<DashboardSnapshot>('/dashboard/snapshot');
    return data;
  } catch (error) {
    logRequestIssue(
      'getDashboardSnapshot',
      'Handled dashboard snapshot fetch failure',
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
        bot_status: {
          is_running: false,
          status: 'stopped',
          reason: null
        }
      },
      last_updated_at: null,
      stale_seconds: null,
      stale: true,
      empty: true
    };
  }
}

// Open Orders Summary API
export interface OpenOrdersSummary extends OpenOrdersSyncMeta {
  orders: UnifiedOpenOrder[];
  last_updated: string | null;
  count: number;
}

export async function getOpenOrdersSummary(): Promise<OpenOrdersSummary> {
  try {
    const data = await fetchAPI<OpenOrdersSummary>('/dashboard/open-orders-summary');
    return data;
  } catch (error) {
    logRequestIssue(
      'getOpenOrdersSummary',
      'Handled open orders summary fetch failure',
      error,
      'warn'
    );
    return { orders: [], last_updated: null, count: 0 };
  }
}

// Convert dashboard balances to portfolio assets
export function dashboardBalancesToPortfolioAssets(balances: DashboardBalance[]): PortfolioAsset[] {
  return balances
    .filter(balance => {
      if (!balance || !(balance.asset || balance.currency || balance.coin)) return false;
      const amount = balance.balance ?? balance.total ?? 0;
      return amount != 0;
    })
    .map(balance => {
      const asset = balance.asset || balance.currency || balance.coin || '';
      const balanceAmount = balance.balance ?? balance.total ?? 0;
      // Prioritize usd_value, then market_value, then 0
      // Don't filter by > 0 - preserve all values including 0
      const usdValue = (balance.usd_value !== undefined && balance.usd_value !== null)
        ? balance.usd_value
        : ((balance.market_value !== undefined && balance.market_value !== null)
            ? balance.market_value
            : 0);
      return {
        coin: asset,
        balance: balanceAmount,
        available_qty: balance.free || 0,
        reserved_qty: balance.locked || 0,
        haircut: 0,
        value_usd: usdValue,
        updated_at: new Date().toISOString()
      };
    });
}

// Expected Take Profit API
export interface ExpectedTPSummaryItem {
  symbol: string;
  position_side?: 'LONG' | 'SHORT';
  net_qty: number;
  position_value: number;
  actual_position_value?: number | null; // Value at buy price (cost basis); null when cost basis unknown
  covered_qty: number;
  uncovered_qty: number;
  total_expected_profit: number | null; // null when cost basis is unknown (current-price fallback)
  current_price?: number;
  coverage_ratio?: number;
  cost_basis_unknown?: boolean; // true when buy price is the current-price fallback (no real BUY orders)
  orphaned_protection_only?: boolean; // true when SL/TP remain but portfolio balance <= 0
}

export interface ExpectedTPSummary {
  summary: ExpectedTPSummaryItem[];
  total_symbols: number;
  last_updated: string | null;
}

export async function getExpectedTakeProfitSummary(): Promise<ExpectedTPSummary> {
  try {
    const data = await fetchAPI<ExpectedTPSummary>('/dashboard/expected-take-profit');
    return data;
  } catch (error) {
    logRequestIssue(
      'getExpectedTakeProfitSummary',
      'Handled expected take profit summary fetch failure',
      error,
      'warn'
    );
    return { summary: [], total_symbols: 0, last_updated: null };
  }
}

// Legacy interface - kept for reference but not used
// export interface ExpectedTPDetailsLot {
//   lot_id: string;
//   quantity: number;
//   entry_price: number;
//   tp_price: number;
//   expected_profit: number;
//   order_id?: string;
// }

export interface ExpectedTPMatchedLot {
  symbol: string;
  buy_order_id: string;
  buy_order_ids?: string[]; // For grouped entries
  buy_order_count?: number; // For grouped entries
  buy_time: string | null;
  buy_price: number | null; // null when cost basis is unknown (current-price fallback)
  lot_qty: number;
  tp_order_id: string;
  tp_time: string | null;
  tp_price: number;
  tp_qty: number;
  tp_status: string;
  match_origin: string;
  expected_profit: number | null; // null when cost basis is unknown
  expected_profit_pct: number | null; // null when cost basis is unknown
  cost_basis_unknown?: boolean; // true when buy price is the current-price fallback
  is_grouped?: boolean; // For grouped entries
}

export interface ExpectedTPProtectionOrder {
  order_id: string;
  price: number | null;
  qty: number;
  remaining_qty: number;
  status: string;
  /** Always positive for take-profit rows */
  expected_amount_usd: number | null;
  /** Always positive for take-profit rows */
  expected_amount_pct: number | null;
}

export interface ExpectedTPStopLossOrder extends ExpectedTPProtectionOrder {
  /** Always negative for stop-loss rows */
  expected_amount_usd: number | null;
  /** Always negative for stop-loss rows */
  expected_amount_pct: number | null;
}

export interface ExpectedTPEntryOrder {
  order_id: string | null;
  symbol?: string;
  side: 'BUY' | 'SELL';
  entry_price: number | null;
  qty: number;
  entry_time: string | null;
  cost_basis_unknown?: boolean;
  match_origin?: string | null;
  take_profits: ExpectedTPProtectionOrder[];
  stop_loss: ExpectedTPStopLossOrder | null;
}

export interface ExpectedTPDetails {
  symbol: string;
  position_side?: 'LONG' | 'SHORT';
  net_qty: number;
  position_value: number;
  actual_position_value?: number | null;
  covered_qty: number;
  uncovered_qty: number;
  total_expected_profit: number | null; // null when cost basis is unknown
  matched_lots: ExpectedTPMatchedLot[]; // Backend returns 'matched_lots', not 'lots'
  entry_orders?: ExpectedTPEntryOrder[];
  current_price?: number;
  has_uncovered?: boolean;
  cost_basis_unknown?: boolean; // true when buy price is the current-price fallback
  uncovered_entry?: {
    symbol: string;
    uncovered_qty: number;
    label: string;
  };
  orphaned_protection_only?: boolean;
}

export async function getExpectedTakeProfitDetails(symbol: string): Promise<ExpectedTPDetails> {
  try {
    const data = await fetchAPI<ExpectedTPDetails>(`/dashboard/expected-take-profit/${symbol}`);
    return data;
  } catch (error) {
    logRequestIssue(
      `getExpectedTakeProfitDetails:${symbol}`,
      'Handled expected take profit details fetch failure',
      error,
      'warn'
    );
    throw error;
  }
}

// Telegram Messages API
export interface TelegramMessage {
  message: string;
  symbol: string | null;
  blocked: boolean;
  order_skipped: boolean;
  timestamp: string;
  throttle_status?: string | null;
  throttle_reason?: string | null;
}

export interface TelegramMessagesResponse {
  messages: TelegramMessage[];
  total: number;
}

export async function getTelegramMessages(): Promise<TelegramMessagesResponse> {
  try {
    const data = await fetchAPI<TelegramMessagesResponse>('/monitoring/telegram-messages');
    return data;
  } catch (error) {
    logRequestIssue(
      'getTelegramMessages',
      'Handled telegram messages fetch failure',
      error,
      'warn'
    );
    return { messages: [], total: 0 };
  }
}

// Unified Open Order type (from backend)
export interface UnifiedOpenOrder {
  order_id: string;
  symbol: string;
  side: string;
  order_type: string;
  status: string;
  price: number | null;
  trigger_price: number | null;
  quantity: number;
  is_trigger: boolean;
  trigger_type: string | null;
  trigger_condition: string | null;
  client_oid: string | null;
  created_at: string | null;
  updated_at: string | null;
  source: string;
  metadata?: Record<string, unknown>;
}

// Note: OpenPosition interface is defined earlier (around line 1469) with the structure
// used by transformOrdersToPositions function

// Strategy Decision type - re-exported from @/lib/api for consistency
export type { StrategyDecision } from '@/lib/api';

// Agent Operations Visibility API
export interface AgentStatus {
  scheduler_running: boolean;
  automation_enabled: boolean;
  last_scheduler_cycle: string;
  scheduler_interval_s: number;
  pending_notion_tasks: number;
  tasks_in_investigation: number;
  tasks_in_patch_phase: number;
  tasks_awaiting_deploy: number;
  tasks_deploying: number;
  pending_approvals: number;
}

export interface AgentOpsRecovery {
  ok: boolean;
  recovery_actions: Array<{
    timestamp: string;
    event_type: string;
    task_id: string | null;
    task_title: string | null;
    details: Record<string, unknown>;
  }>;
  count: number;
  error?: string;
}

export interface AgentOpsFailedInvestigations {
  ok: boolean;
  failed_investigations: Array<{
    timestamp: string;
    event_type: string;
    task_id: string | null;
    task_title: string | null;
    details: Record<string, unknown>;
  }>;
  count: number;
  error?: string;
}

export interface AgentOpsActiveTasks {
  ok: boolean;
  patching: Array<{ id?: string | null; task?: string | null; status?: string | null; priority?: string | null }>;
  deploying: Array<{ id?: string | null; task?: string | null; status?: string | null; priority?: string | null }>;
  awaiting_deploy_approval: Array<{ id?: string | null; task?: string | null; status?: string | null; priority?: string | null }>;
  error?: string;
}

export interface AgentOpsSmokeChecks {
  ok: boolean;
  smoke_checks: Array<{
    timestamp: string;
    event_type: string;
    task_id: string | null;
    task_title: string | null;
    details: Record<string, unknown>;
  }>;
  count: number;
  error?: string;
}

export interface AgentOpsDeployTracker {
  ok: boolean;
  recent_deploys: Array<{ task_id: string; triggered_at: string; triggered_by: string }>;
  last_deploy_task_id: string;
  error?: string;
}

export interface AgentOpsCursorBridgeEvents {
  ok: boolean;
  cursor_bridge_events: Array<{
    timestamp: string;
    event_type: string;
    task_id: string | null;
    task_title: string | null;
    details: Record<string, unknown>;
  }>;
  count: number;
  error?: string;
}

export async function getAgentStatus(): Promise<AgentStatus> {
  try {
    return await fetchAPI<AgentStatus>('/agent/status');
  } catch (error) {
    logRequestIssue('getAgentStatus', 'Agent status fetch failed', error, 'warn');
    return {
      scheduler_running: false,
      automation_enabled: false,
      last_scheduler_cycle: '',
      scheduler_interval_s: 300,
      pending_notion_tasks: -1,
      tasks_in_investigation: -1,
      tasks_in_patch_phase: -1,
      tasks_awaiting_deploy: -1,
      tasks_deploying: -1,
      pending_approvals: -1,
    };
  }
}

export async function getAgentOpsRecovery(limit = 20): Promise<AgentOpsRecovery> {
  try {
    return await fetchAPI<AgentOpsRecovery>(`/agent/ops/recovery?limit=${limit}`);
  } catch (error) {
    logRequestIssue('getAgentOpsRecovery', 'Recovery fetch failed', error, 'warn');
    return { ok: false, recovery_actions: [], count: 0 };
  }
}

export async function getAgentOpsFailedInvestigations(limit = 20): Promise<AgentOpsFailedInvestigations> {
  try {
    return await fetchAPI<AgentOpsFailedInvestigations>(`/agent/ops/failed-investigations?limit=${limit}`);
  } catch (error) {
    logRequestIssue('getAgentOpsFailedInvestigations', 'Failed investigations fetch failed', error, 'warn');
    return { ok: false, failed_investigations: [], count: 0 };
  }
}

export async function getAgentOpsActiveTasks(): Promise<AgentOpsActiveTasks> {
  try {
    return await fetchAPI<AgentOpsActiveTasks>('/agent/ops/active-tasks');
  } catch (error) {
    logRequestIssue('getAgentOpsActiveTasks', 'Active tasks fetch failed', error, 'warn');
    return {
      ok: false,
      patching: [],
      deploying: [],
      awaiting_deploy_approval: [],
    };
  }
}

export async function getAgentOpsSmokeChecks(limit = 20): Promise<AgentOpsSmokeChecks> {
  try {
    return await fetchAPI<AgentOpsSmokeChecks>(`/agent/ops/smoke-checks?limit=${limit}`);
  } catch (error) {
    logRequestIssue('getAgentOpsSmokeChecks', 'Smoke checks fetch failed', error, 'warn');
    return { ok: false, smoke_checks: [], count: 0 };
  }
}

export async function getAgentOpsDeployTracker(limit = 10): Promise<AgentOpsDeployTracker> {
  try {
    return await fetchAPI<AgentOpsDeployTracker>(`/agent/ops/deploy-tracker?limit=${limit}`);
  } catch (error) {
    logRequestIssue('getAgentOpsDeployTracker', 'Deploy tracker fetch failed', error, 'warn');
    return { ok: false, recent_deploys: [], last_deploy_task_id: '' };
  }
}

export async function getAgentOpsCursorBridgeEvents(limit = 15): Promise<AgentOpsCursorBridgeEvents> {
  try {
    return await fetchAPI<AgentOpsCursorBridgeEvents>(`/agent/ops/cursor-bridge-events?limit=${limit}`);
  } catch (error) {
    logRequestIssue('getAgentOpsCursorBridgeEvents', 'Cursor bridge events fetch failed', error, 'warn');
    return { ok: false, cursor_bridge_events: [], count: 0 };
  }
}

export interface AgentOpsCursorBridgeDiagnostics {
  ok: boolean;
  enabled?: boolean;
  cursor_cli_path?: string;
  cursor_cli_found?: boolean;
  staging_root?: string;
  staging_root_writable?: boolean;
  staging_dir_count?: number;
  max_staging_dirs?: number;
  handoff_dir_exists?: boolean;
  github_token_set?: boolean;
  ready?: boolean;
  error?: string;
}

export async function getAgentOpsCursorBridgeDiagnostics(): Promise<AgentOpsCursorBridgeDiagnostics> {
  try {
    return await fetchAPI<AgentOpsCursorBridgeDiagnostics>('/agent/cursor-bridge/diagnostics');
  } catch (error) {
    logRequestIssue('getAgentOpsCursorBridgeDiagnostics', 'Cursor bridge diagnostics fetch failed', error, 'warn');
    return { ok: false, error: String(error) };
  }
}

// --- Jarvis Phase 3 task execution ---

export interface JarvisExecutionStep {
  id: string;
  action: string;
  tool: string;
  description: string;
  safety_level?: string;
  estimated_cost_usd?: number;
}

export interface JarvisExecutionPlan {
  steps: JarvisExecutionStep[];
  total_estimated_cost_usd?: number;
  overall_safety?: string;
  objective_summary?: string;
}

export interface JarvisExecutionTaskSummary {
  task_id: string;
  objective: string;
  status: string;
  priority?: string;
  approval_status?: string;
  estimated_cost_usd?: number;
  actual_cost_usd?: number;
  created_at?: string | null;
  completed_at?: string | null;
}

export interface JarvisExecutionLogEntry {
  log_id: string;
  agent: string;
  tool: string;
  input_summary?: string;
  output_summary?: string;
  duration_ms?: number;
  timestamp?: string;
}

export interface JarvisArtifactRecord {
  artifact_id: string;
  name: string;
  format: string;
  step_id?: string | null;
  preview?: string;
}

export interface JarvisValidationCheck {
  label: string;
  passed: boolean;
}

export interface JarvisValidationOutcome {
  task_type?: string;
  passed?: boolean;
  final_status?: string;
  checks?: JarvisValidationCheck[];
  explanation?: string;
  completion_report?: {
    summary?: string;
    evidence?: string;
    conclusion?: string;
    next_action?: string;
  };
}

export interface JarvisExecutionTaskDetail {
  task_id: string;
  objective: string;
  status: string;
  plan?: JarvisExecutionPlan | Record<string, unknown>;
  artifacts?: JarvisArtifactRecord[];
  approval_required?: boolean;
  approval_status?: string;
  estimated_cost_usd?: number;
  actual_cost_usd?: number;
  current_step?: string | null;
  execution_log?: JarvisExecutionLogEntry[];
  final_answer?: string;
  error?: string | null;
  review?: {
    validation?: JarvisValidationOutcome;
    [key: string]: unknown;
  };
}

export async function submitJarvisExecutionTask(body: {
  objective: string;
  priority?: string;
  approval_mode?: string;
  dry_run?: boolean;
}): Promise<JarvisExecutionTaskDetail> {
  return fetchAPI<JarvisExecutionTaskDetail>('/jarvis/tasks/submit', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export async function listJarvisExecutionTasks(limit = 20): Promise<{ tasks: JarvisExecutionTaskSummary[] }> {
  return fetchAPI<{ tasks: JarvisExecutionTaskSummary[] }>(`/jarvis/tasks/execution?limit=${limit}`);
}

export async function getJarvisExecutionTask(taskId: string): Promise<JarvisExecutionTaskDetail> {
  return fetchAPI<JarvisExecutionTaskDetail>(`/jarvis/tasks/execution/${taskId}`);
}

export async function approveJarvisTask(
  taskId: string,
  body: { actor_id?: string; comment?: string } = {},
): Promise<JarvisExecutionTaskDetail> {
  return fetchAPI<JarvisExecutionTaskDetail>(`/jarvis/tasks/${taskId}/approve`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export async function rejectJarvisTask(
  taskId: string,
  body: { actor_id?: string; comment?: string } = {},
): Promise<JarvisExecutionTaskDetail> {
  return fetchAPI<JarvisExecutionTaskDetail>(`/jarvis/tasks/${taskId}/reject`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

// --- Phase 4A: Production diagnostic investigations ---

export interface JarvisInvestigationEvidence {
  source: string;
  reference: string;
  detail: string;
  confidence: string;
  evidence_type?: string;
  artifact_id?: string;
  content_url?: string;
  mime_type?: string;
}

export interface JarvisInvestigationRankedCause {
  cause: string;
  score: number;
  supporting_evidence?: string[];
  explanation?: string;
}

export interface JarvisInvestigationSummary {
  investigation_id: string;
  objective: string;
  status: string;
  root_cause?: string | null;
  confidence: number;
  evidence_count: number;
  recommended_fix?: string | null;
  category?: string;
  created_at?: string | null;
}

export interface JarvisInvestigationDetail {
  investigation_id: string;
  objective: string;
  category: string;
  template_id: string;
  status: string;
  summary: string;
  evidence: JarvisInvestigationEvidence[];
  evidence_count: number;
  root_cause: string | null;
  confidence: number;
  ranked_causes: JarvisInvestigationRankedCause[];
  impact: string;
  recommended_fix: string;
  verification_steps: string[];
  next_action: string;
  proposal_task_id?: string | null;
  proposal_status?: string | null;
  created_at?: string | null;
}

export interface JarvisFixTemplateCandidate {
  fix_template_id: string;
  match: string;
  target_files?: string[];
  test_paths?: string[];
  strategy?: string;
  no_fix_required?: boolean;
}

export interface JarvisProposalEligibility {
  eligible: boolean;
  reasons: string[];
  confidence: number;
  fix_template_candidates: JarvisFixTemplateCandidate[];
  existing_proposal_task_id: string | null;
}

export interface JarvisProposalTaskDetail extends JarvisExecutionTaskDetail {
  workflow_type?: string;
  source_investigation_id?: string | null;
  fix_template_id?: string | null;
  sandbox_summary?: Record<string, unknown>;
}

export interface JarvisInvestigationImageAttachment {
  filename: string;
  content_base64: string;
  caption?: string;
  content_type?: string;
}

export interface JarvisInvestigationPreset {
  id: string;
  label: string;
  objective: string;
}

export async function runJarvisInvestigation(
  objective: string,
  attachments?: JarvisInvestigationImageAttachment[],
): Promise<JarvisInvestigationDetail> {
  return fetchAPI<JarvisInvestigationDetail>('/jarvis/investigations/run', {
    method: 'POST',
    body: JSON.stringify({
      objective,
      attachments: attachments ?? [],
    }),
  });
}

export async function listJarvisInvestigations(
  limit = 20,
  q = '',
): Promise<{ investigations: JarvisInvestigationSummary[] }> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (q) params.set('q', q);
  return fetchAPI<{ investigations: JarvisInvestigationSummary[] }>(
    `/jarvis/investigations?${params.toString()}`,
  );
}

export async function getJarvisInvestigation(
  investigationId: string,
): Promise<JarvisInvestigationDetail> {
  return fetchAPI<JarvisInvestigationDetail>(`/jarvis/investigations/${investigationId}`);
}

export async function listJarvisInvestigationPresets(): Promise<{ presets: JarvisInvestigationPreset[] }> {
  return fetchAPI<{ presets: JarvisInvestigationPreset[] }>('/jarvis/investigations/presets');
}

export interface JarvisScheduledInvestigationSchedule {
  schedule_id: string;
  template_id: string;
  title: string;
  objective: string;
  category: string;
  enabled: boolean;
  next_run_at: string | null;
  last_run_at: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface JarvisScheduledInvestigationTask {
  task_id: string;
  schedule_id: string;
  template_id: string;
  objective: string;
  status: string;
  investigation_id: string | null;
  result_summary: string | null;
  error_message: string | null;
  scheduled_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface JarvisScheduledInvestigationsResponse {
  scheduler: Record<string, unknown>;
  schedules: JarvisScheduledInvestigationSchedule[];
  tasks: JarvisScheduledInvestigationTask[];
}

export interface JarvisScheduledInvestigationReport {
  period_hours: number;
  since: string;
  generated_at: string;
  task_counts: Record<string, number>;
  success_rate_pct: number;
  failure_rate_pct: number;
  average_runtime_ms: number;
  schedules: JarvisScheduledInvestigationSchedule[];
  recent_tasks: JarvisScheduledInvestigationTask[];
}

export async function getJarvisScheduledInvestigations(
  limit = 50,
): Promise<JarvisScheduledInvestigationsResponse> {
  return fetchAPI<JarvisScheduledInvestigationsResponse>(
    `/jarvis/investigations/scheduled?limit=${limit}`,
  );
}

export async function getJarvisScheduledInvestigationReport(
  hours = 24,
): Promise<JarvisScheduledInvestigationReport> {
  return fetchAPI<JarvisScheduledInvestigationReport>(
    `/jarvis/investigations/scheduled/report?hours=${hours}`,
  );
}

// --- Phase 6B: Jarvis autonomous alerting ---

export interface JarvisAlertSummary {
  alert_id: string;
  created_at: string;
  updated_at: string;
  severity: string;
  source: string;
  investigation_id: string | null;
  title: string;
  summary: string;
  evidence_count: number;
  status: string;
  fingerprint: string;
  occurrence_count: number;
  first_seen: string;
  last_seen: string;
}

export interface JarvisAlertsResponse {
  alerts: JarvisAlertSummary[];
  alerting: Record<string, unknown>;
}

export interface JarvisDailyReportSummary {
  id: number;
  report_id: string;
  report_date: string;
  generated_at: string;
  summary: Record<string, unknown>;
}

export interface JarvisDailyReportsResponse {
  reports: JarvisDailyReportSummary[];
  alerting: Record<string, unknown>;
}

export async function getJarvisAlerts(limit = 100): Promise<JarvisAlertsResponse> {
  return fetchAPI<JarvisAlertsResponse>(`/jarvis/alerts?limit=${limit}`);
}

export async function getJarvisAlert(alertId: string): Promise<JarvisAlertSummary & { evidence: unknown[] }> {
  return fetchAPI(`/jarvis/alerts/${alertId}`);
}

export async function acknowledgeJarvisAlert(alertId: string): Promise<JarvisAlertSummary & { evidence: unknown[] }> {
  return fetchAPI(`/jarvis/alerts/${alertId}/acknowledge`, { method: 'POST' });
}

export async function resolveJarvisAlert(alertId: string): Promise<JarvisAlertSummary & { evidence: unknown[] }> {
  return fetchAPI(`/jarvis/alerts/${alertId}/resolve`, { method: 'POST' });
}

export async function getJarvisDailyReports(limit = 30): Promise<JarvisDailyReportsResponse> {
  return fetchAPI<JarvisDailyReportsResponse>(`/jarvis/reports?limit=${limit}`);
}

export async function getJarvisDailyReport(reportId: string): Promise<JarvisDailyReportSummary> {
  return fetchAPI<JarvisDailyReportSummary>(`/jarvis/reports/${reportId}`);
}

export async function getProposalEligibility(
  investigationId: string,
): Promise<JarvisProposalEligibility> {
  return fetchAPI<JarvisProposalEligibility>(`/jarvis/proposals/eligibility/${investigationId}`);
}

export async function proposePatchFromInvestigation(
  investigationId: string,
): Promise<JarvisProposalTaskDetail> {
  return fetchAPI<JarvisProposalTaskDetail>(
    `/jarvis/investigations/${investigationId}/propose-patch`,
    { method: 'POST' },
  );
}

// --- Phase 4C: Jarvis investigation quality analytics ---

export interface JarvisAnalyticsInvestigationMetrics {
  total_investigations: number;
  completed: number;
  resolved: number;
  insufficient_evidence: number;
  partial_failure: number;
  failed: number;
  running: number;
  average_duration_ms: number;
  median_duration_ms: number;
  success_rate_pct: number;
  failure_rate_pct: number;
  insufficient_evidence_rate_pct: number;
  false_positives: number;
  tool_errors_inferred: number;
}

export interface JarvisAnalyticsQualityScore {
  overall_score: number;
  last_7_days: number;
  last_30_days: number;
  formula: Record<string, number>;
}

export interface JarvisAnalyticsOverview {
  investigations: JarvisAnalyticsInvestigationMetrics;
  quality_score: JarvisAnalyticsQualityScore;
  period_rates: Record<string, { completion_rate_pct: number; resolution_rate_pct: number; false_positive_rate_pct: number }>;
  trends: {
    last_7_days: Array<Record<string, string | number>>;
    last_30_days: Array<Record<string, string | number>>;
    quality_score_daily: Array<{ date: string; quality_score: number }>;
  };
  read_only: boolean;
}

export interface JarvisAnalyticsTemplateRow {
  template_id: string;
  investigations: number;
  completed: number;
  failed: number;
  insufficient_evidence: number;
  completion_rate_pct: number;
  failure_rate_pct: number;
  insufficient_evidence_rate_pct: number;
  average_confidence: number;
}

export interface JarvisAnalyticsToolRow {
  tool: string;
  executions: number;
  successes: number;
  failures: number;
  success_rate_pct: number;
  failure_rate_pct: number;
  average_duration_ms: number;
  common_errors: Array<{ message: string; count: number }>;
}

export interface JarvisAnalyticsProposals {
  proposals: {
    proposals_generated: number;
    no_fix_required: number;
    waiting_for_approval: number;
    approved: number;
    rejected: number;
    failed: number;
    proposing: number;
    useful_proposals: number;
    useful_rate_pct: number;
  };
  proposal_tasks: number;
  read_only: boolean;
}

export interface JarvisAnalyticsRootCauses {
  most_common_root_causes: Array<{ root_cause: string; occurrences: number; key: string }>;
  recurring_incidents: Array<{ root_cause: string; occurrences: number; key: string }>;
  resolved_incidents: Array<{ investigation_id?: string; objective?: string; root_cause: string; status?: string; confidence: number; created_at?: string }>;
  active_incidents: Array<{ investigation_id?: string; objective?: string; root_cause: string; status?: string; confidence: number; created_at?: string }>;
  unique_root_causes: number;
  read_only: boolean;
}

export async function getJarvisAnalyticsOverview(): Promise<JarvisAnalyticsOverview> {
  return fetchAPI<JarvisAnalyticsOverview>('/jarvis/analytics/overview');
}

export async function getJarvisAnalyticsTemplates(): Promise<{ templates: JarvisAnalyticsTemplateRow[]; count: number }> {
  return fetchAPI<{ templates: JarvisAnalyticsTemplateRow[]; count: number }>('/jarvis/analytics/templates');
}

export async function getJarvisAnalyticsTools(): Promise<{ tools: JarvisAnalyticsToolRow[]; count: number; noisiest_tools: JarvisAnalyticsToolRow[] }> {
  return fetchAPI<{ tools: JarvisAnalyticsToolRow[]; count: number; noisiest_tools: JarvisAnalyticsToolRow[] }>('/jarvis/analytics/tools');
}

export async function getJarvisAnalyticsProposals(): Promise<JarvisAnalyticsProposals> {
  return fetchAPI<JarvisAnalyticsProposals>('/jarvis/analytics/proposals');
}

export async function getJarvisAnalyticsRootCauses(): Promise<JarvisAnalyticsRootCauses> {
  return fetchAPI<JarvisAnalyticsRootCauses>('/jarvis/analytics/root-causes');
}

// --- Phase 4D: Jarvis self-improvement recommendation engine ---

export interface JarvisImprovementRecommendation {
  id: string;
  category: string;
  priority: 'high' | 'medium' | 'low';
  priority_score: number;
  title: string;
  recommendation: string;
  reason: string;
  evidence: string[];
  expected_benefit: string;
  impact: string;
  frequency: number;
  confidence: number;
}

export interface JarvisImprovementRecommendations {
  recommendations: JarvisImprovementRecommendation[];
  backlog: JarvisImprovementRecommendation[];
  by_priority: Record<string, JarvisImprovementRecommendation[]>;
  counts: Record<string, number>;
  read_only: boolean;
}

export interface JarvisImprovementTemplateGap {
  gap_type: string;
  template_id?: string;
  category?: string;
  investigations: number;
  severity: string;
  insufficient_evidence?: number;
  insufficient_evidence_rate_pct?: number;
  generic_rate_pct?: number;
  failure_rate_pct?: number;
  top_keywords?: string[];
  templates_used?: Record<string, number>;
}

export interface JarvisImprovementTemplates {
  gaps: JarvisImprovementTemplateGap[];
  recommendations: JarvisImprovementRecommendation[];
  summary: Record<string, unknown>;
  template_metrics: JarvisAnalyticsTemplateRow[];
  read_only: boolean;
}

export interface JarvisImprovementToolEffectiveness {
  tool: string;
  category: string;
  assessment_display: string;
  executions: number;
  successes: number;
  failures: number;
  success_rate_pct: number;
  useful_outcomes: number;
  investigations_using: number;
  utility_ratio: number;
  useful_findings?: number;
  false_positive_contribution?: number;
  workflow_usage_rate?: number | null;
  successful_completion_rate?: number | null;
  failure_association_rate?: number | null;
  average_duration_ms: number;
  assessment: string;
}

export interface JarvisImprovementTools {
  tools: JarvisImprovementToolEffectiveness[];
  low_utility_tools: JarvisImprovementToolEffectiveness[];
  high_value_tools: JarvisImprovementToolEffectiveness[];
  recommendations: JarvisImprovementRecommendation[];
  summary: Record<string, unknown>;
  read_only: boolean;
}

export interface JarvisImprovementTrends {
  quality_scores: Record<string, number | string>;
  false_positives: Record<string, number>;
  period_rates: Record<string, Record<string, number>>;
  recurring_incidents: Array<{ root_cause: string; occurrences: number; key: string }>;
  open_orders_share_pct: number;
  quality_score_daily: Array<{ date: string; quality_score: number }>;
  recommendations: JarvisImprovementRecommendation[];
  read_only: boolean;
}

export async function getJarvisImprovementRecommendations(): Promise<JarvisImprovementRecommendations> {
  return fetchAPI<JarvisImprovementRecommendations>('/jarvis/improvement/recommendations');
}

export async function getJarvisImprovementTemplates(): Promise<JarvisImprovementTemplates> {
  return fetchAPI<JarvisImprovementTemplates>('/jarvis/improvement/templates');
}

export async function getJarvisImprovementTools(): Promise<JarvisImprovementTools> {
  return fetchAPI<JarvisImprovementTools>('/jarvis/improvement/tools');
}

export async function getJarvisImprovementTrends(): Promise<JarvisImprovementTrends> {
  return fetchAPI<JarvisImprovementTrends>('/jarvis/improvement/trends');
}

export interface JarvisImprovementQuality {
  quality_score: number;
  recommendation_count: number;
  high_priority_count: number;
  suppressed_recommendations: number;
  duplicate_recommendations: number;
  evidence_coverage: number;
  read_only: boolean;
}

export async function getJarvisImprovementQuality(): Promise<JarvisImprovementQuality> {
  return fetchAPI<JarvisImprovementQuality>('/jarvis/improvement/quality');
}

