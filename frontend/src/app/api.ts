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
  updated_at: string;
  tp?: number;  // Take profit price
  sl?: number;  // Stop loss price
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

export interface DashboardState {
  source?: string;  // "crypto.com" when using direct API values
  total_usd_value?: number;  // Total USD value from Crypto.com
  balances: DashboardBalance[];
  fast_signals: DashboardSignal[];
  slow_signals: DashboardSignal[];
  open_orders: DashboardOrder[];
  open_position_counts?: { [symbol: string]: number };
  open_orders_summary?: UnifiedOpenOrder[];  // Open orders summary
  last_sync: string | null;
  portfolio?: {
    assets?: PortfolioAsset[];
    total_value_usd?: number;
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
export async function saveCoinSettings(symbol: string, settings: Partial<CoinSettings>): Promise<CoinSettings> {
  try {
    // Get dashboard to find the item by symbol
    const dashboard = await getDashboard();
    const item = dashboard.find(item => item.symbol === symbol.toUpperCase());
    
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

export async function getOrderHistory(
  limit: number = 100,
  offset: number = 0,
  sync: boolean = false
): Promise<{ 
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

/** Safe fallback when snapshot is missing or API returns null/invalid `data` (avoids client TypeError on `.data.balances`). */
function emptyDashboardSnapshotResponse(): DashboardSnapshot {
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

export async function getDashboardSnapshot(): Promise<DashboardSnapshot> {
  try {
    const snapshot = await fetchAPI<DashboardSnapshot>('/dashboard/snapshot');
    if (!snapshot?.data) {
      logRequestIssue(
        'getDashboardSnapshot',
        'Snapshot response missing data — using empty fallback',
        new Error('snapshot.data is null or undefined'),
        'warn'
      );
      return emptyDashboardSnapshotResponse();
    }
    return snapshot;
  } catch (error) {
    logRequestIssue(
      'getDashboardSnapshot',
      'Handled dashboard snapshot fetch failure',
      error,
      'warn'
    );
    return emptyDashboardSnapshotResponse();
  }
}

// Open Orders Summary API
export interface OpenOrdersSummary {
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
    .filter(balance => balance && (balance.asset || balance.currency || balance.coin) && (balance.balance || balance.total || 0) > 0)
    .map(balance => {
      const asset = balance.asset || balance.currency || balance.coin || '';
      const balanceAmount = balance.balance || balance.total || 0;
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
  net_qty: number;
  position_value: number;
  actual_position_value?: number; // Value at buy price (cost basis)
  covered_qty: number;
  uncovered_qty: number;
  total_expected_profit: number;
  current_price?: number;
  coverage_ratio?: number;
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
  position_value: number;
  actual_position_value?: number;
  covered_qty: number;
  uncovered_qty: number;
  total_expected_profit: number;
  matched_lots: ExpectedTPMatchedLot[]; // Backend returns 'matched_lots', not 'lots'
  current_price?: number;
  has_uncovered?: boolean;
  uncovered_entry?: {
    symbol: string;
    uncovered_qty: number;
    label: string;
  };
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
