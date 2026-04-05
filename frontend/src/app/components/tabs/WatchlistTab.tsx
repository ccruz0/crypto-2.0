/**
 * Watchlist Tab Component
 * Complete implementation with full table functionality
 */

import React, { useState, useMemo, useCallback, useEffect } from 'react';
import { TopCoin, TradingSignals, saveCoinSettings, updateWatchlistAlert, updateBuyAlert, updateSellAlert, StrategyDecision, TradingConfig } from '@/app/api';
import { formatDateTime, formatNumber, normalizeSymbolKey } from '@/utils/formatting';
import { logger } from '@/utils/logger';
import { useWatchlist } from '@/hooks/useWatchlist';

interface WatchlistTabProps {
  botStatus: { is_running: boolean; status: 'running' | 'stopped'; reason: string | null; live_trading_enabled?: boolean; mode?: 'LIVE' | 'DRY_RUN'; kill_switch_on?: boolean } | null;
  togglingLiveTrading: boolean;
  isUpdating: boolean;
  topCoinsLoading: boolean;
  portfolioLoading: boolean;
  dataSourceStatus: Record<string, { available: boolean; priority: number; response_time: number | null; last_check: string | null }> | null;
  fastQueueRateLimited: boolean;
  onToggleLiveTrading: () => Promise<void>;
  // Pass data from parent component
  topCoins?: TopCoin[];
  signals?: Record<string, TradingSignals | null>;
  coinTradeStatus?: Record<string, boolean>;
  coinMarginStatus?: Record<string, boolean>;
  coinAmounts?: Record<string, string>;
  coinSLPercent?: Record<string, string>;
  coinTPPercent?: Record<string, string>;
  coinBuyAlertStatus?: Record<string, boolean>;
  coinSellAlertStatus?: Record<string, boolean>;
  coinAlertStatus?: Record<string, boolean>;
  watchlistFilter?: string;
  onWatchlistFilterChange?: (filter: string) => void;
  tradingConfig?: TradingConfig | null;
  coinPresets?: Record<string, string>;
  onCoinPresetChange?: (symbol: string, preset: string) => void;
  onAmountSaved?: (symbol: string) => void; // Callback to mark amount as recently saved
  onCoinUpdated?: (symbol: string, updates: Partial<TopCoin>) => void; // Callback to update coin in parent's topCoins array
}

type SortField = 'symbol' | 'last_price' | 'rsi' | 'ema10' | 'ma50' | 'ma200' | 'volume' | 'amount_usd';
type SortDirection = 'asc' | 'desc';

export default function WatchlistTab({
  botStatus,
  togglingLiveTrading,
  isUpdating,
  topCoinsLoading,
  portfolioLoading,
  dataSourceStatus,
  fastQueueRateLimited,
  onToggleLiveTrading,
  topCoins: parentTopCoins,
  signals: parentSignals,
  coinTradeStatus: parentCoinTradeStatus,
  coinMarginStatus: parentCoinMarginStatus,
  coinAmounts: parentCoinAmounts,
  coinSLPercent: parentCoinSLPercent,
  coinTPPercent: parentCoinTPPercent,
  coinBuyAlertStatus: parentCoinBuyAlertStatus,
  coinSellAlertStatus: parentCoinSellAlertStatus,
  coinAlertStatus: parentCoinAlertStatus,
  watchlistFilter: parentWatchlistFilter,
  onWatchlistFilterChange,
  tradingConfig: parentTradingConfig,
  coinPresets: parentCoinPresets,
  onCoinPresetChange,
  onAmountSaved,
  onCoinUpdated,
}: WatchlistTabProps) {
  const {
    topCoins: hookTopCoins,
    topCoinsLoading: watchlistLoading,
    lastTopCoinsFetchAt,
    coinTradeStatus: hookCoinTradeStatus,
    coinAmounts: hookCoinAmounts,
    coinSLPercent: hookCoinSLPercent,
    coinTPPercent: hookCoinTPPercent,
    coinBuyAlertStatus: hookCoinBuyAlertStatus,
    coinSellAlertStatus: hookCoinSellAlertStatus,
    coinAlertStatus: hookCoinAlertStatus,
    setCoinTradeStatus,
    setCoinAmounts,
    setCoinSLPercent,
    setCoinTPPercent,
    setCoinBuyAlertStatus,
    setCoinSellAlertStatus,
    setCoinAlertStatus,
  } = useWatchlist();

  // Use parent data if provided, otherwise use hook data
  const topCoins = parentTopCoins || hookTopCoins;
  const signals = parentSignals || {};
  const coinTradeStatus = parentCoinTradeStatus || hookCoinTradeStatus;
  const coinAmounts = parentCoinAmounts || hookCoinAmounts;
  const coinSLPercent = parentCoinSLPercent || hookCoinSLPercent;
  const coinTPPercent = parentCoinTPPercent || hookCoinTPPercent;
  const coinBuyAlertStatus = parentCoinBuyAlertStatus || hookCoinBuyAlertStatus;
  const coinSellAlertStatus = parentCoinSellAlertStatus || hookCoinSellAlertStatus;
  const coinAlertStatus = parentCoinAlertStatus || hookCoinAlertStatus;

  const [watchlistFilter, setWatchlistFilter] = useState(parentWatchlistFilter || '');
  const [sortField, setSortField] = useState<SortField | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc');
  const [updatingCoins, setUpdatingCoins] = useState<Set<string>>(new Set());
  const [editingAmount, setEditingAmount] = useState<Record<string, string>>({});
  const [editingSLPercent, setEditingSLPercent] = useState<Record<string, string>>({});
  const [editingTPPercent, setEditingTPPercent] = useState<Record<string, string>>({});
  
  // Initialize margin status from parent or use empty object
  const [localCoinMarginStatus, setLocalCoinMarginStatus] = useState<Record<string, boolean>>(parentCoinMarginStatus || {});
  
  // Initialize coin presets from parent or use empty object
  const [localCoinPresets, setLocalCoinPresets] = useState<Record<string, string>>(parentCoinPresets || {});
  
  // Sync with parent when it changes
  useEffect(() => {
    if (parentCoinPresets) {
      setLocalCoinPresets(parentCoinPresets);
    }
  }, [parentCoinPresets]);
  
  // Sync with parent when it changes
  useEffect(() => {
    if (parentCoinMarginStatus) {
      setLocalCoinMarginStatus(parentCoinMarginStatus);
    }
  }, [parentCoinMarginStatus]);
  
  const coinMarginStatus = parentCoinMarginStatus || localCoinMarginStatus;

  // Filter coins
  const filteredCoins = useMemo(() => {
    if (!topCoins || topCoins.length === 0) return [];
    
    let filtered = topCoins;
    
    // Apply search filter
    if (watchlistFilter.trim()) {
      const filterUpper = watchlistFilter.trim().toUpperCase();
      filtered = filtered.filter(coin => 
        coin?.instrument_name.toUpperCase().includes(filterUpper)
      );
    }
    
    return filtered;
  }, [topCoins, watchlistFilter]);

  // Sort coins
  const sortedCoins = useMemo(() => {
    if (!sortField) return filteredCoins;
    
    const sorted = [...filteredCoins].sort((a, b) => {
      let aValue: number | string = 0;
      let bValue: number | string = 0;
      
      switch (sortField) {
        case 'symbol':
          aValue = a.instrument_name || '';
          bValue = b.instrument_name || '';
          break;
        case 'last_price':
          aValue = a.current_price || 0;
          bValue = b.current_price || 0;
          break;
        case 'rsi':
          aValue = signals[a.instrument_name]?.rsi || 0;
          bValue = signals[b.instrument_name]?.rsi || 0;
          break;
        case 'ema10':
          aValue = signals[a.instrument_name]?.ema10 || 0;
          bValue = signals[b.instrument_name]?.ema10 || 0;
          break;
        case 'ma50':
          aValue = signals[a.instrument_name]?.ma50 || 0;
          bValue = signals[b.instrument_name]?.ma50 || 0;
          break;
        case 'ma200':
          aValue = signals[a.instrument_name]?.ma200 || 0;
          bValue = signals[b.instrument_name]?.ma200 || 0;
          break;
        case 'volume':
          aValue = signals[a.instrument_name]?.volume_ratio || 0;
          bValue = signals[b.instrument_name]?.volume_ratio || 0;
          break;
        case 'amount_usd':
          aValue = parseFloat(coinAmounts[normalizeSymbolKey(a.instrument_name)] || '0');
          bValue = parseFloat(coinAmounts[normalizeSymbolKey(b.instrument_name)] || '0');
          break;
      }
      
      if (typeof aValue === 'string' && typeof bValue === 'string') {
        return sortDirection === 'asc' 
          ? aValue.localeCompare(bValue)
          : bValue.localeCompare(aValue);
      }
      
      return sortDirection === 'asc'
        ? (aValue as number) - (bValue as number)
        : (bValue as number) - (aValue as number);
    });
    
    return sorted;
  }, [filteredCoins, sortField, sortDirection, signals, coinAmounts]);

  const handleSort = useCallback((field: SortField) => {
    if (sortField === field) {
      setSortDirection(prev => prev === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDirection('asc');
    }
  }, [sortField]);

  const handleFilterChange = useCallback((value: string) => {
    setWatchlistFilter(value);
    if (onWatchlistFilterChange) {
      onWatchlistFilterChange(value);
    }
  }, [onWatchlistFilterChange]);

  const handleTradeToggle = useCallback(async (symbol: string) => {
    const symbolKey = normalizeSymbolKey(symbol);
    const currentStatus = coinTradeStatus[symbolKey] || false;
    const newStatus = !currentStatus;
    
    setUpdatingCoins(prev => new Set(prev).add(symbol));
    
    try {
      // Optimistic update - update both hook state and parent state if parent props are provided
      setCoinTradeStatus(prev => ({ ...prev, [symbolKey]: newStatus }));
      
      // If parent props are provided, also update parent immediately for instant UI feedback
      if (parentCoinTradeStatus !== undefined && onCoinUpdated) {
        onCoinUpdated(symbol, { trade_enabled: newStatus });
      }
      
      // Save to backend
      const result = await saveCoinSettings(symbol, {
        trade_enabled: newStatus,
      });
      
      // Update parent's topCoins array and state with backend response
      if (onCoinUpdated && result) {
        onCoinUpdated(symbol, {
          trade_enabled: result.trade_enabled,
          strategy_key: result.strategy_key,
          strategy_preset: result.strategy_preset,
          strategy_risk: result.strategy_risk,
          sl_price: result.sl_price,
          tp_price: result.tp_price,
        });
      }
      
      logger.info(`✅ Trade status updated for ${symbol}: ${newStatus}`);
    } catch (err: unknown) {
      logger.error(`Failed to update trade status for ${symbol}:`, err);
      // Revert optimistic update
      setCoinTradeStatus(prev => ({ ...prev, [symbolKey]: currentStatus }));
      // Also revert parent if we updated it
      if (parentCoinTradeStatus !== undefined && onCoinUpdated) {
        onCoinUpdated(symbol, { trade_enabled: currentStatus });
      }
      // Show error to user with more details
      const errorMessage = err instanceof Error ? err.message : (typeof err === 'string' ? err : String(err)) || 'Unknown error';
      const errorDetails = errorMessage.includes('Failed to fetch') 
        ? 'Error de conexión. Verifica tu conexión a internet.'
        : errorMessage.length > 100 
        ? 'Error del servidor. Por favor, intenta de nuevo.'
        : errorMessage;
      alert(`Error al actualizar el estado de trade para ${symbol}.\n\n${errorDetails}\n\nPor favor, intenta de nuevo.`);
    } finally {
      setUpdatingCoins(prev => {
        const next = new Set(prev);
        next.delete(symbol);
        return next;
      });
    }
  }, [coinTradeStatus, setCoinTradeStatus, onCoinUpdated, parentCoinTradeStatus]);

  const handleAlertToggle = useCallback(async (symbol: string, alertType: 'master' | 'buy' | 'sell') => {
    const symbolKey = normalizeSymbolKey(symbol);
    setUpdatingCoins(prev => new Set(prev).add(symbol));
    
    // Store previous state for rollback
    let previousStatus: boolean;
    let previousStateSetter: ((prev: Record<string, boolean>) => Record<string, boolean>) | null = null;
    
    try {
      if (alertType === 'master') {
        previousStatus = coinAlertStatus[symbolKey] || false;
        const newStatus = !previousStatus;
        
        // Optimistic update
        setCoinAlertStatus(prev => ({ ...prev, [symbolKey]: newStatus }));
        previousStateSetter = (prev: Record<string, boolean>) => ({ ...prev, [symbolKey]: previousStatus });
        
        const result = await updateWatchlistAlert(symbol, newStatus);
        logger.info(`✅ Master alert status updated for ${symbol}: ${newStatus}`, result);
        
        // Sync with response if available
        if (result?.alert_enabled !== undefined) {
          setCoinAlertStatus(prev => ({ ...prev, [symbolKey]: result.alert_enabled }));
        }
        
        // Update parent's topCoins array with backend response
        if (onCoinUpdated) {
          onCoinUpdated(symbol, {
            alert_enabled: result.alert_enabled,
          });
        }
      } else if (alertType === 'buy') {
        previousStatus = coinBuyAlertStatus[symbolKey] || false;
        const newStatus = !previousStatus;
        
        // Optimistic update
        setCoinBuyAlertStatus(prev => ({ ...prev, [symbolKey]: newStatus }));
        previousStateSetter = (prev: Record<string, boolean>) => ({ ...prev, [symbolKey]: previousStatus });
        
        const result = await updateBuyAlert(symbol, newStatus);
        logger.info(`✅ Buy alert status updated for ${symbol}: ${newStatus}`, result);
        
        // Sync with response if available
        if (result?.buy_alert_enabled !== undefined) {
          setCoinBuyAlertStatus(prev => ({ ...prev, [symbolKey]: result.buy_alert_enabled }));
        }
        
        // Update parent's topCoins array with backend response
        if (onCoinUpdated) {
          onCoinUpdated(symbol, {
            buy_alert_enabled: result.buy_alert_enabled,
            alert_enabled: result.alert_enabled,
          });
        }
      } else if (alertType === 'sell') {
        previousStatus = coinSellAlertStatus[symbolKey] || false;
        const newStatus = !previousStatus;
        
        // Optimistic update
        setCoinSellAlertStatus(prev => ({ ...prev, [symbolKey]: newStatus }));
        previousStateSetter = (prev: Record<string, boolean>) => ({ ...prev, [symbolKey]: previousStatus });
        
        const result = await updateSellAlert(symbol, newStatus);
        logger.info(`✅ Sell alert status updated for ${symbol}: ${newStatus}`, result);
        
        // Sync with response if available
        if (result?.sell_alert_enabled !== undefined) {
          setCoinSellAlertStatus(prev => ({ ...prev, [symbolKey]: result.sell_alert_enabled }));
        }
        
        // Update parent's topCoins array with backend response
        if (onCoinUpdated) {
          onCoinUpdated(symbol, {
            sell_alert_enabled: result.sell_alert_enabled,
            alert_enabled: result.alert_enabled,
          });
        }
      }
    } catch (err) {
      logger.error(`Failed to update ${alertType} alert for ${symbol}:`, err);
      // Revert optimistic update
      if (previousStateSetter) {
        if (alertType === 'master') {
          setCoinAlertStatus(previousStateSetter);
        } else if (alertType === 'buy') {
          setCoinBuyAlertStatus(previousStateSetter);
        } else if (alertType === 'sell') {
          setCoinSellAlertStatus(previousStateSetter);
        }
      }
      // Show error to user
      alert(`Error al actualizar la alerta ${alertType} para ${symbol}. Por favor, intenta de nuevo.`);
    } finally {
      setUpdatingCoins(prev => {
        const next = new Set(prev);
        next.delete(symbol);
        return next;
      });
    }
  }, [coinAlertStatus, coinBuyAlertStatus, coinSellAlertStatus, setCoinAlertStatus, setCoinBuyAlertStatus, setCoinSellAlertStatus, onCoinUpdated]);

  const handleMarginToggle = useCallback(async (symbol: string) => {
    const symbolKey = normalizeSymbolKey(symbol);
    const currentStatus = coinMarginStatus[symbolKey] || false;
    const newStatus = !currentStatus;
    
    setUpdatingCoins(prev => new Set(prev).add(symbol));
    
    try {
      // Optimistic update - update local state
      setLocalCoinMarginStatus(prev => ({ ...prev, [symbolKey]: newStatus }));
      
      // If parent props are provided, also update parent immediately for instant UI feedback
      if (parentCoinMarginStatus !== undefined && onCoinUpdated) {
        onCoinUpdated(symbol, { trade_on_margin: newStatus });
      }
      
      // Save to backend
      const result = await saveCoinSettings(symbol, {
        trade_on_margin: newStatus,
      });
      
      logger.info(`✅ Margin status updated for ${symbol}: ${newStatus}`, result);
      
      // Sync with response if available
      if (result?.trade_on_margin !== undefined) {
        setLocalCoinMarginStatus(prev => ({ ...prev, [symbolKey]: Boolean(result.trade_on_margin) }));
      }
      
      // Update parent's topCoins array and state with backend response
      if (onCoinUpdated && result) {
        onCoinUpdated(symbol, {
          trade_on_margin: result.trade_on_margin,
          strategy_key: result.strategy_key,
          strategy_preset: result.strategy_preset,
          strategy_risk: result.strategy_risk,
          sl_price: result.sl_price,
          tp_price: result.tp_price,
        });
      }
    } catch (err: unknown) {
      logger.error(`Failed to update margin status for ${symbol}:`, err);
      // Revert optimistic update
      setLocalCoinMarginStatus(prev => ({ ...prev, [symbolKey]: currentStatus }));
      // Also revert parent if we updated it
      if (parentCoinMarginStatus !== undefined && onCoinUpdated) {
        onCoinUpdated(symbol, { trade_on_margin: currentStatus });
      }
      // Show error to user with more details
      const errorMessage = err instanceof Error ? err.message : (typeof err === 'string' ? err : String(err)) || 'Unknown error';
      const errorDetails = errorMessage.includes('Failed to fetch') 
        ? 'Error de conexión. Verifica tu conexión a internet.'
        : errorMessage.length > 100 
        ? 'Error del servidor. Por favor, intenta de nuevo.'
        : errorMessage;
      alert(`Error al actualizar el estado de margen para ${symbol}.\n\n${errorDetails}\n\nPor favor, intenta de nuevo.`);
    } finally {
      setUpdatingCoins(prev => {
        const next = new Set(prev);
        next.delete(symbol);
        return next;
      });
    }
  }, [coinMarginStatus, onCoinUpdated, parentCoinMarginStatus]);

  const handleAmountSave = useCallback(async (symbol: string, value: string) => {
    const symbolKey = normalizeSymbolKey(symbol);
    setUpdatingCoins(prev => new Set(prev).add(symbol));
    
    // Store previous value for rollback
    const previousValue = coinAmounts[symbolKey];
    
    try {
      const numValue = parseFloat(value);
      if (isNaN(numValue) || numValue < 0) {
        logger.warn(`Invalid amount value for ${symbol}: ${value}`);
        return;
      }
      
      // Optimistic update
      setCoinAmounts(prev => ({ ...prev, [symbolKey]: value }));
      
      // Save to backend
      const result = await saveCoinSettings(symbol, {
        trade_amount_usd: numValue,
      });
      
      logger.info(`✅ Amount updated for ${symbol}: $${value}`);
      
      // Sync with response if available
      if (result?.trade_amount_usd !== undefined && result.trade_amount_usd !== null) {
        const savedValue = result.trade_amount_usd.toString();
        setCoinAmounts(prev => ({ ...prev, [symbolKey]: savedValue }));
        // Mark as recently saved to prevent overwriting with stale backend data
        if (onAmountSaved) {
          onAmountSaved(symbolKey);
        }
        // Update localStorage to keep it in sync with backend
        try {
          const currentAmounts = JSON.parse(localStorage.getItem('watchlist_amounts') || '{}');
          currentAmounts[symbolKey] = savedValue;
          localStorage.setItem('watchlist_amounts', JSON.stringify(currentAmounts));
          logger.info(`✅ Updated localStorage for ${symbolKey}: ${savedValue}`);
        } catch (err) {
          logger.warn(`Failed to update localStorage for ${symbolKey}:`, err);
        }
      }
      
      // Update parent's topCoins array with backend response
      if (onCoinUpdated && result) {
        onCoinUpdated(symbol, {
          trade_amount_usd: result.trade_amount_usd,
          strategy_key: result.strategy_key,
          strategy_preset: result.strategy_preset,
          strategy_risk: result.strategy_risk,
          sl_price: result.sl_price,
          tp_price: result.tp_price,
        });
      }
    } catch (err) {
      logger.error(`Failed to update amount for ${symbol}:`, err);
      // Revert optimistic update to previous value
      setCoinAmounts(prev => {
        const updated = { ...prev };
        if (previousValue !== undefined) {
          updated[symbolKey] = previousValue;
        } else {
          delete updated[symbolKey];
        }
        return updated;
      });
      // Show error to user
      alert(`Error al actualizar el monto USD para ${symbol}. Por favor, intenta de nuevo.`);
    } finally {
      setUpdatingCoins(prev => {
        const next = new Set(prev);
        next.delete(symbol);
        return next;
      });
      setEditingAmount(prev => {
        const updated = { ...prev };
        delete updated[symbol];
        return updated;
      });
    }
  }, [coinAmounts, setCoinAmounts]);

  const handleSLPercentSave = useCallback(async (symbol: string, value: string) => {
    const symbolKey = normalizeSymbolKey(symbol);
    setUpdatingCoins(prev => new Set(prev).add(symbol));
    
    try {
      const numValue = value === '' ? null : parseFloat(value);
      if (value !== '' && (isNaN(numValue!) || numValue! < 0)) {
        logger.warn(`Invalid SL% value for ${symbol}: ${value}`);
        return;
      }
      
      // Optimistic update
      setCoinSLPercent(prev => ({ ...prev, [symbolKey]: value }));
      
      // Save to backend
      const result = await saveCoinSettings(symbol, {
        sl_percentage: numValue,
      });
      
      logger.info(`✅ SL% updated for ${symbol}: ${value || 'null'}`);
      
      // Update parent's topCoins array with backend response (includes updated SL/TP prices)
      if (onCoinUpdated && result) {
        onCoinUpdated(symbol, {
          sl_percentage: result.sl_percentage,
          sl_price: result.sl_price,
          tp_price: result.tp_price,
          strategy_key: result.strategy_key,
          strategy_preset: result.strategy_preset,
          strategy_risk: result.strategy_risk,
        });
      }
    } catch (err) {
      logger.error(`Failed to update SL% for ${symbol}:`, err);
    } finally {
      setUpdatingCoins(prev => {
        const next = new Set(prev);
        next.delete(symbol);
        return next;
      });
      setEditingSLPercent(prev => {
        const updated = { ...prev };
        delete updated[symbol];
        return updated;
      });
    }
  }, [setCoinSLPercent]);

  const handleTPPercentSave = useCallback(async (symbol: string, value: string) => {
    const symbolKey = normalizeSymbolKey(symbol);
    setUpdatingCoins(prev => new Set(prev).add(symbol));
    
    try {
      const numValue = value === '' ? null : parseFloat(value);
      if (value !== '' && (isNaN(numValue!) || numValue! < 0)) {
        logger.warn(`Invalid TP% value for ${symbol}: ${value}`);
        return;
      }
      
      // Optimistic update
      setCoinTPPercent(prev => ({ ...prev, [symbolKey]: value }));
      
      // Save to backend
      const result = await saveCoinSettings(symbol, {
        tp_percentage: numValue,
      });
      
      logger.info(`✅ TP% updated for ${symbol}: ${value || 'null'}`);
      
      // Update parent's topCoins array with backend response (includes updated SL/TP prices)
      if (onCoinUpdated && result) {
        onCoinUpdated(symbol, {
          tp_percentage: result.tp_percentage,
          sl_price: result.sl_price,
          tp_price: result.tp_price,
          strategy_key: result.strategy_key,
          strategy_preset: result.strategy_preset,
          strategy_risk: result.strategy_risk,
        });
      }
    } catch (err) {
      logger.error(`Failed to update TP% for ${symbol}:`, err);
    } finally {
      setUpdatingCoins(prev => {
        const next = new Set(prev);
        next.delete(symbol);
        return next;
      });
      setEditingTPPercent(prev => {
        const updated = { ...prev };
        delete updated[symbol];
        return updated;
      });
    }
  }, [setCoinTPPercent]);

  // Handler for changing coin strategy
  const handleStrategyChange = useCallback(async (symbol: string, strategyKey: string) => {
    const symbolKey = normalizeSymbolKey(symbol);
    setUpdatingCoins(prev => new Set(prev).add(symbol));
    
    try {
      // Parse strategy key (e.g., "swing-conservative" -> preset="swing", risk="conservative")
      const parts = strategyKey.split('-');
      const preset = parts[0] || 'swing';
      const risk = parts[1] || 'conservative';
      
      // CRITICAL: Update WatchlistItem.sl_tp_mode ONLY (single source of truth)
      // trading_config.json is a preset catalog only, NOT state - do NOT write to it
      // The backend's resolve_strategy_profile reads preset from trading_config.json (catalog)
      // and risk from WatchlistItem.sl_tp_mode (state)
      const result = await saveCoinSettings(symbol, {
        sl_tp_mode: risk,  // Update risk mode in WatchlistItem (DB is source of truth)
      });
      
      // REGRESSION GUARD: Verify API response contains updated strategy_key
      // This ensures UI state matches DB state
      if (result?.strategy_key && result.strategy_key !== strategyKey) {
        logger.warn(`[STRATEGY_MISMATCH] Strategy update mismatch for ${symbol}: requested=${strategyKey}, API=${result.strategy_key}. Backend resolved different strategy.`);
      }
      
      // Clear local state - UI will use API response as truth
      // Do NOT update localCoinPresets - it's a legacy fallback only
      setLocalCoinPresets(prev => {
        const updated = { ...prev };
        delete updated[symbolKey];  // Remove to force using API values
        return updated;
      });
      
      // Notify parent if callback provided (for backward compatibility)
      if (onCoinPresetChange) {
        onCoinPresetChange(symbol, strategyKey);
      }
      
      // CRITICAL: Update parent's topCoins array with backend response (includes updated SL/TP prices)
      // This ensures UI immediately reflects the new strategy and its calculated SL/TP values
      if (onCoinUpdated && result) {
        onCoinUpdated(symbol, {
          strategy_key: result.strategy_key || strategyKey,
          strategy_preset: result.strategy_preset,
          strategy_risk: result.strategy_risk || risk,
          sl_tp_mode: result.sl_tp_mode || risk,
          sl_price: result.sl_price,
          tp_price: result.tp_price,
          sl_percentage: result.sl_percentage,
          tp_percentage: result.tp_percentage,
        });
      }
      
      logger.info(`✅ Strategy updated for ${symbol}: ${strategyKey} (sl_tp_mode=${risk}). DB is source of truth.`);
      
    } catch (err) {
      logger.error(`Failed to update strategy for ${symbol}:`, err);
      // Revert on error (clear local state)
      setLocalCoinPresets(prev => {
        const updated = { ...prev };
        delete updated[symbolKey];
        return updated;
      });
      // Show error to user
      alert(`Error al actualizar la estrategia para ${symbol}. Por favor, intenta de nuevo.`);
    } finally {
      setUpdatingCoins(prev => {
        const next = new Set(prev);
        next.delete(symbol);
        return next;
      });
    }
  }, [onCoinPresetChange]);

  // Available strategy options
  const strategyOptions = [
    { value: 'swing-conservative', label: 'Swing Conservadora' },
    { value: 'swing-aggressive', label: 'Swing Agresiva' },
    { value: 'intraday-conservative', label: 'Intradia Conservadora' },
    { value: 'intraday-aggressive', label: 'Intradia Agresiva' },
    { value: 'scalp-conservative', label: 'Scalp Conservadora' },
    { value: 'scalp-aggressive', label: 'Scalp Agresiva' },
  ];

  // Helper function to build crypto page URL for a symbol
  const getCryptoPageUrl = useCallback((symbol: string | undefined): string => {
    if (!symbol) return '#';
    // Link to Binance trading page for the trading pair
    // Format: https://www.binance.com/en/trade/{SYMBOL_WITHOUT_UNDERSCORE}
    // For example: ETC_USDT -> https://www.binance.com/en/trade/ETCUSDT
    const symbolForUrl = symbol.replace(/_/g, '');
    return `https://www.binance.com/en/trade/${symbolForUrl}`;
  }, []);

  // Helper function to format strategy name
  const formatStrategyName = useCallback((strategy?: string | null): string => {
    if (!strategy || typeof strategy !== 'string') return 'No strategy';
    // Format: "swing-conservative" -> "Swing Conservadora"
    const parts = strategy.split('-');
    const presetMap: Record<string, string> = {
      'swing': 'Swing',
      'intraday': 'Intradia',
      'scalp': 'Scalp'
    };
    const riskMap: Record<string, string> = {
      'conservative': 'Conservadora',
      'aggressive': 'Agresiva'
    };
    const preset = presetMap[parts[0]?.toLowerCase()] || parts[0] || 'Unknown';
    const risk = riskMap[parts[1]?.toLowerCase()] || parts[1] || '';
    return risk ? `${preset} ${risk}` : preset;
  }, []);

  // Helper function to determine if buy criteria are met
  const isBuyCriteriaMet = useCallback((signal: TradingSignals | null | undefined): boolean => {
    if (!signal) return false;
    // Check if buy signal is true
    return signal.signals?.buy === true;
  }, []);

  // Helper function to determine if sell criteria are met
  const isSellCriteriaMet = useCallback((signal: TradingSignals | null | undefined): boolean => {
    if (!signal) return false;
    // Check if sell signal is true
    return signal.signals?.sell === true;
  }, []);

  // Helper function to get strategy for a coin
  // CRITICAL: Uses API strategy_key as single source of truth (from WatchlistItem)
  const getCoinStrategy = useCallback((coin: TopCoin, signal: TradingSignals | null | undefined): string | undefined => {
    const symbolKey = normalizeSymbolKey(coin?.instrument_name);
    
    // PRIORITY 1: API strategy_key (single source of truth from WatchlistItem)
    // This ensures dropdown and tooltip always match what's in the database
    if (coin?.strategy_key) {
      return coin.strategy_key;
    }
    
    // PRIORITY 2: Construct from API strategy_preset + strategy_risk
    if (coin?.strategy_preset && coin?.strategy_risk) {
      return `${coin.strategy_preset}-${coin.strategy_risk}`;
    }
    
    // FALLBACK: Legacy sources (for backward compatibility during migration)
    if (localCoinPresets[symbolKey]) {
      return localCoinPresets[symbolKey];
    }
    if (coin?.strategy) {
      return coin.strategy;
    }
    if (signal?.strategy) {
      return signal.strategy;
    }
    if (parentTradingConfig?.coins?.[symbolKey]?.preset) {
      return parentTradingConfig.coins[symbolKey].preset;
    }
    
    // Default to swing-conservative if no strategy is set
    return 'swing-conservative';
  }, [localCoinPresets, parentTradingConfig]);

  // Helper function to build strategy tooltip
  // CRITICAL: Uses same source as dropdown (getCoinStrategy) to ensure consistency
  const buildStrategyTooltip = useCallback((coin: TopCoin, signal: TradingSignals | null | undefined): string => {
    // Use same function as dropdown to ensure dropdown and tooltip cannot disagree
    const strategy = getCoinStrategy(coin, signal);
    const strategyName = formatStrategyName(strategy);
    const lines: string[] = [];
    
    // REGRESSION GUARD: Verify strategy matches API (dev/test warning)
    if (coin?.strategy_key && coin.strategy_key !== strategy) {
      logger.warn(`[STRATEGY_MISMATCH] Tooltip strategy mismatch for ${coin?.instrument_name}: API=${coin.strategy_key}, computed=${strategy}. UI using fallback instead of API.`);
    }
    
    // REGRESSION GUARD: Warn if API strategy_key is null but UI shows a strategy
    if (!coin?.strategy_key && strategy && strategy !== 'swing-conservative') {
      logger.warn(`[STRATEGY_MISMATCH] API strategy_key is null for ${coin?.instrument_name} but UI shows strategy=${strategy}. UI using fallback/default.`);
    }
    
    lines.push(`📊 Estrategia: ${strategyName}`);
    
    if (signal) {
      lines.push('');
      lines.push('📈 Indicadores:');
      if (signal.rsi !== undefined) lines.push(`  • RSI: ${signal.rsi.toFixed(2)}`);
      if (signal.ema10 !== undefined) lines.push(`  • EMA10: $${formatNumber(signal.ema10, coin?.instrument_name)}`);
      if (signal.ma50 !== undefined) lines.push(`  • MA50: $${formatNumber(signal.ma50, coin?.instrument_name)}`);
      if (signal.ma200 !== undefined) lines.push(`  • MA200: $${formatNumber(signal.ma200, coin?.instrument_name)}`);
      if (signal.volume_ratio !== undefined) lines.push(`  • Volume Ratio: ${signal.volume_ratio.toFixed(2)}x`);
      
      lines.push('');
      lines.push('🎯 Señales:');
      lines.push(`  • BUY: ${signal.signals?.buy ? '✓' : '✗'}`);
      lines.push(`  • SELL: ${signal.signals?.sell ? '✓' : '✗'}`);
      
      if (signal.rationale && signal.rationale.length > 0) {
        lines.push('');
        lines.push('💡 Razón:');
        signal.rationale.forEach(r => lines.push(`  • ${r}`));
      }
    }
    
    return lines.join('\n');
  }, [formatStrategyName]);

  // Helper function to build trade button tooltip with all indicators
  // CRITICAL: Uses same source as dropdown (getCoinStrategy) to ensure consistency
  const buildTradeTooltip = useCallback((coin: TopCoin, signal: TradingSignals | null | undefined): string => {
    // Use same function as dropdown to ensure dropdown and tooltip cannot disagree
    const strategy = getCoinStrategy(coin, signal);
    const strategyName = formatStrategyName(strategy);
    const lines: string[] = [];
    lines.push(`📊 Estrategia: ${strategyName}`);
    lines.push('');
    lines.push('📈 Indicadores y Estado:');
    
    if (signal) {
      // RSI - check if below buy threshold (typically 40)
      const rsiOk = signal.rsi !== undefined && signal.rsi < 40;
      lines.push(`  • RSI: ${signal.rsi !== undefined ? signal.rsi.toFixed(2) : 'N/A'} ${rsiOk ? '✓' : '✗'}`);
      
      // EMA10 - always shown
      lines.push(`  • EMA10: ${signal.ema10 !== undefined ? `$${formatNumber(signal.ema10, coin?.instrument_name)}` : 'N/A'} ✓`);
      
      // MA50 - check if MA50 > EMA10
      const ma50Ok = signal.ma50 !== undefined && signal.ema10 !== undefined && signal.ma50 > signal.ema10;
      lines.push(`  • MA50: ${signal.ma50 !== undefined ? `$${formatNumber(signal.ma50, coin?.instrument_name)}` : 'N/A'} ${ma50Ok ? '✓' : '✗'}`);
      if (signal.ma50 !== undefined && signal.ema10 !== undefined) {
        lines.push(`    (MA50 ${signal.ma50 > signal.ema10 ? '>' : '<'} EMA10)`);
      }
      
      // MA200 - check if Price > MA200
      const ma200Ok = coin?.current_price !== undefined && signal.ma200 !== undefined && coin.current_price > signal.ma200;
      lines.push(`  • MA200: ${signal.ma200 !== undefined ? `$${formatNumber(signal.ma200, coin?.instrument_name)}` : 'N/A'} ${ma200Ok ? '✓' : '✗'}`);
      if (coin?.current_price !== undefined && signal.ma200 !== undefined) {
        lines.push(`    (Precio ${coin.current_price > signal.ma200 ? '>' : '<'} MA200)`);
      }
      
      // Volume Ratio
      const volumeOk = signal.volume_ratio !== undefined && signal.volume_ratio >= 0.5;
      lines.push(`  • Volume Ratio: ${signal.volume_ratio !== undefined ? `${signal.volume_ratio.toFixed(2)}x` : 'N/A'} ${volumeOk ? '✓' : '✗'}`);
      
      lines.push('');
      lines.push('🎯 Señales del Backend:');
      lines.push(`  • BUY: ${signal.signals?.buy ? '✓' : '✗'}`);
      lines.push(`  • SELL: ${signal.signals?.sell ? '✓' : '✗'}`);
      
      if (signal.rationale && signal.rationale.length > 0) {
        lines.push('');
        lines.push('💡 Razón:');
        signal.rationale.forEach(r => lines.push(`  • ${r}`));
      }
    } else {
      lines.push('  • Datos no disponibles');
    }
    
    return lines.join('\n');
  }, [formatStrategyName]);

  // Helper function to get indicator color class based on criteria
  const getIndicatorColorClass = useCallback((
    indicatorType: 'rsi' | 'ema10' | 'ma50' | 'ma200',
    signal: TradingSignals | null | undefined,
    coin: TopCoin
  ): string => {
    if (!signal) return 'text-gray-400';
    
    const isBuy = isBuyCriteriaMet(signal);
    const isSell = isSellCriteriaMet(signal);
    
    switch (indicatorType) {
      case 'rsi':
        // RSI should be low for buy, high for sell
        if (isBuy && signal.rsi !== undefined && signal.rsi < 40) return 'text-green-600 font-semibold';
        if (isSell && signal.rsi !== undefined && signal.rsi > 60) return 'text-red-600 font-semibold';
        return 'text-gray-600';
      case 'ema10':
        // EMA10 is always shown (neutral for now, can be enhanced)
        return isBuy ? 'text-green-600' : isSell ? 'text-red-600' : 'text-gray-600';
      case 'ma50':
        // MA50 > EMA10 for buy
        if (isBuy && signal.ma50 !== undefined && signal.ema10 !== undefined && signal.ma50 > signal.ema10) {
          return 'text-green-600 font-semibold';
        }
        return 'text-gray-600';
      case 'ma200':
        // Price > MA200 for buy
        if (isBuy && coin?.current_price !== undefined && signal.ma200 !== undefined && coin.current_price > signal.ma200) {
          return 'text-green-600 font-semibold';
        }
        return 'text-gray-600';
      default:
        return 'text-gray-600';
    }
  }, [isBuyCriteriaMet, isSellCriteriaMet]);

  // Helper function to calculate SL/TP percentage from prices
  const calculateSLTPPercent = useCallback((price: number | undefined, slPrice: number | undefined, tpPrice: number | undefined): { slPercent: number | null, tpPercent: number | null } => {
    if (!price || price <= 0) {
      return { slPercent: null, tpPercent: null };
    }
    
    let slPercent: number | null = null;
    let tpPercent: number | null = null;
    
    if (slPrice && slPrice > 0) {
      // SL is below current price, so percentage is negative
      slPercent = ((slPrice - price) / price) * 100;
    }
    
    if (tpPrice && tpPrice > 0) {
      // TP is above current price, so percentage is positive
      tpPercent = ((tpPrice - price) / price) * 100;
    }
    
    return { slPercent, tpPercent };
  }, []);

  // Helper function to get displayed SL/TP percentage (manual or calculated)
  const getDisplayedSLTP = useCallback((coin: TopCoin, symbolKey: string): { slPercent: string | null, tpPercent: string | null } => {
    // First, check for manual percentages
    const manualSL = coinSLPercent[symbolKey];
    const manualTP = coinTPPercent[symbolKey];
    
    if (manualSL || manualTP) {
      return {
        slPercent: manualSL || null,
        tpPercent: manualTP || null,
      };
    }
    
    // If no manual percentages, calculate from prices
    const currentPrice = coin?.current_price;
    const slPrice = coin?.sl_price;
    const tpPrice = coin?.tp_price;
    
    if (currentPrice && (slPrice || tpPrice)) {
      const calculated = calculateSLTPPercent(currentPrice, slPrice, tpPrice);
      return {
        slPercent: calculated.slPercent !== null ? calculated.slPercent.toFixed(2) : null,
        tpPercent: calculated.tpPercent !== null ? calculated.tpPercent.toFixed(2) : null,
      };
    }
    
    return { slPercent: null, tpPercent: null };
  }, [coinSLPercent, coinTPPercent, calculateSLTPPercent]);

  // Helper function to build SL/TP tooltip
  const buildSLTPTooltip = useCallback((coin: TopCoin, signal: TradingSignals | null | undefined): string => {
    const strategy = getCoinStrategy(coin, signal);
    const strategyName = formatStrategyName(strategy);
    const lines: string[] = [];
    lines.push(`📊 Estrategia: ${strategyName}`);
    lines.push('');
    
    const symbolKey = normalizeSymbolKey(coin?.instrument_name);
    const slPercent = coinSLPercent[symbolKey];
    const tpPercent = coinTPPercent[symbolKey];
    
    // Show manual SL/TP if set, otherwise show calculated from strategy
    if (slPercent) {
      lines.push(`🛑 Stop Loss (manual): ${slPercent}%`);
    } else if (coin?.sl_price && coin?.current_price) {
      const calculated = calculateSLTPPercent(coin.current_price, coin.sl_price, undefined);
      if (calculated.slPercent !== null) {
        lines.push(`🛑 Stop Loss (calculated): ${calculated.slPercent.toFixed(2)}%`);
        lines.push(`   Price: $${formatNumber(coin.sl_price, coin?.instrument_name)}`);
      }
    } else if (signal?.stop_loss_take_profit?.stop_loss) {
      const sl = signal.stop_loss_take_profit.stop_loss;
      lines.push(`🛑 Stop Loss:`);
      lines.push(`  • Conservadora: ${sl.conservative.percentage.toFixed(2)}%`);
      lines.push(`  • Agresiva: ${sl.aggressive.percentage.toFixed(2)}%`);
    }
    
    if (tpPercent) {
      lines.push(`🎯 Take Profit (manual): ${tpPercent}%`);
    } else if (coin?.tp_price && coin?.current_price) {
      const calculated = calculateSLTPPercent(coin.current_price, undefined, coin.tp_price);
      if (calculated.tpPercent !== null) {
        lines.push(`🎯 Take Profit (calculated): ${calculated.tpPercent.toFixed(2)}%`);
        lines.push(`   Price: $${formatNumber(coin.tp_price, coin?.instrument_name)}`);
      }
    } else if (signal?.stop_loss_take_profit?.take_profit) {
      const tp = signal.stop_loss_take_profit.take_profit;
      lines.push(`🎯 Take Profit:`);
      lines.push(`  • Conservadora: ${tp.conservative.percentage.toFixed(2)}%`);
      lines.push(`  • Agresiva: ${tp.aggressive.percentage.toFixed(2)}%`);
    }
    
    if (signal) {
      lines.push('');
      lines.push('📈 Indicadores actuales:');
      if (signal.rsi !== undefined) lines.push(`  • RSI: ${signal.rsi.toFixed(2)}`);
      if (signal.ema10 !== undefined) lines.push(`  • EMA10: $${formatNumber(signal.ema10, coin?.instrument_name)}`);
      if (signal.ma50 !== undefined) lines.push(`  • MA50: $${formatNumber(signal.ma50, coin?.instrument_name)}`);
      if (signal.ma200 !== undefined) lines.push(`  • MA200: $${formatNumber(signal.ma200, coin?.instrument_name)}`);
    }
    
    return lines.join('\n');
  }, [formatStrategyName, coinSLPercent, coinTPPercent, calculateSLTPPercent]);

  const SortableHeader: React.FC<{ field: SortField; children: React.ReactNode }> = ({ field, children }) => (
    <th
      className="px-4 py-2 text-left cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-800"
      onClick={() => handleSort(field)}
    >
      <div className="flex items-center gap-2">
        {children}
        {sortField === field && (
          <span>{sortDirection === 'asc' ? '↑' : '↓'}</span>
        )}
      </div>
    </th>
  );

  if (watchlistLoading && topCoins.length === 0) {
    return <div>Loading watchlist...</div>;
  }

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <div className="flex items-center gap-3">
          <h2 className="text-xl font-semibold">Watchlist</h2>
          {lastTopCoinsFetchAt && (
            <div className="text-xs text-gray-500">
              🕐 {formatDateTime(lastTopCoinsFetchAt)}
            </div>
          )}
          {botStatus && (
            <>
              <div className={`px-3 py-1 rounded-full text-xs font-semibold ${
                botStatus.is_running 
                  ? 'bg-green-100 text-green-700' 
                  : 'bg-red-100 text-red-700'
              }`} title={botStatus.reason || undefined}>
                {botStatus.is_running ? '🟢 Bot Activo' : '🔴 Bot Detenido'}
              </div>
              {botStatus.kill_switch_on && (
                <div className="px-3 py-1 rounded-full text-xs font-semibold bg-red-600 text-white" title="Kill Switch is ON - All trading is disabled">
                  🛑 KILL SWITCH ON
                </div>
              )}
              <button
                onClick={onToggleLiveTrading}
                disabled={togglingLiveTrading || isUpdating || topCoinsLoading || portfolioLoading}
                className={`px-3 py-1 rounded-full text-xs font-semibold transition-colors ${
                  botStatus.live_trading_enabled
                    ? 'bg-green-600 text-white hover:bg-green-700'
                    : 'bg-gray-400 text-white hover:bg-gray-500'
                }`}
              >
                {togglingLiveTrading ? '⏳' : botStatus.live_trading_enabled ? '🟢 LIVE' : '🔴 DRY RUN'}
              </button>
            </>
          )}
        </div>
      </div>

      {/* Filter */}
      <div className="mb-4">
        <input
          type="text"
          placeholder="Filter by symbol..."
          value={watchlistFilter}
          onChange={(e) => handleFilterChange(e.target.value)}
          className="px-4 py-2 border border-gray-300 rounded-md w-full max-w-md"
        />
      </div>

      {sortedCoins.length === 0 ? (
        <div className="text-center py-12">
          <div className="text-gray-500 text-lg mb-2">No watchlist data available</div>
          <div className="text-gray-400 text-sm">The watchlist will appear here once data is loaded.</div>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700">
            <thead className="bg-gray-50 dark:bg-gray-900">
              <tr>
                <SortableHeader field="symbol">Symbol</SortableHeader>
                <th className="px-4 py-2 text-left">Strategy</th>
                <SortableHeader field="last_price">Price</SortableHeader>
                <SortableHeader field="rsi">RSI</SortableHeader>
                <SortableHeader field="ema10">EMA10</SortableHeader>
                <SortableHeader field="ma50">MA50</SortableHeader>
                <SortableHeader field="ma200">MA200</SortableHeader>
                <SortableHeader field="volume">Volume</SortableHeader>
                <SortableHeader field="amount_usd">Amount USD</SortableHeader>
                <th className="px-4 py-2 text-left">SL%</th>
                <th className="px-4 py-2 text-left">TP%</th>
                <th className="px-4 py-2 text-left">Trade</th>
                <th className="px-4 py-2 text-left">Margin</th>
                <th className="px-4 py-2 text-left">Alerts</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
              {sortedCoins.map((coin) => {
                const symbolKey = normalizeSymbolKey(coin?.instrument_name);
                const signal = signals[coin?.instrument_name];
                const tradeEnabled = coinTradeStatus[symbolKey] || false;
                const masterAlertEnabled = coinAlertStatus[symbolKey] || false;
                const buyAlertEnabled = coinBuyAlertStatus[symbolKey] || false;
                const sellAlertEnabled = coinSellAlertStatus[symbolKey] || false;
                const isCoinUpdating = updatingCoins.has(coin?.instrument_name);
                
                // Determine if buy or sell criteria are met
                const buyCriteriaMet = isBuyCriteriaMet(signal);
                const sellCriteriaMet = isSellCriteriaMet(signal);
                
                // Get symbol color class based on criteria
                const symbolColorClass = buyCriteriaMet 
                  ? 'text-green-600 font-bold' 
                  : sellCriteriaMet 
                    ? 'text-red-600 font-bold' 
                    : 'font-medium';
                
                return (
                  <tr key={coin?.instrument_name} className="hover:bg-gray-50 dark:hover:bg-gray-700">
                    <td 
                      className={`px-4 py-2 ${symbolColorClass}`}
                      title={buildStrategyTooltip(coin, signal)}
                    >
                      <a
                        href={getCryptoPageUrl(coin?.instrument_name)}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="hover:underline cursor-pointer"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {coin?.instrument_name}
                      </a>
                    </td>
                    <td className="px-4 py-2">
                      {(() => {
                        const rawStrategy = getCoinStrategy(coin, signal);
                        const dropdownStrategy = rawStrategy || 'swing-conservative';
                        const tooltipStrategy = rawStrategy || 'swing-conservative';  // Apply same fallback for comparison
                        
                        // REGRESSION GUARD: Verify dropdown and tooltip use same strategy
                        // Both use the same fallback to ensure fair comparison
                        if (dropdownStrategy !== tooltipStrategy) {
                          logger.error(`[STRATEGY_MISMATCH] Dropdown and tooltip disagree for ${coin?.instrument_name}: dropdown=${dropdownStrategy}, tooltip=${tooltipStrategy}. This should never happen.`);
                        }
                        
                        return (
                          <select
                            value={dropdownStrategy}
                            onChange={(e) => handleStrategyChange(coin?.instrument_name, e.target.value)}
                            disabled={isCoinUpdating}
                            className="px-2 py-1 text-xs border border-gray-300 rounded bg-white dark:bg-gray-700 dark:border-gray-600 dark:text-white disabled:opacity-50"
                            title={`Select strategy for this coin (current: ${formatStrategyName(dropdownStrategy)})`}
                          >
                            {strategyOptions.map(option => (
                              <option key={option.value} value={option.value}>
                                {option.label}
                              </option>
                            ))}
                          </select>
                        );
                      })()}
                    </td>
                    <td className="px-4 py-2">${formatNumber(coin?.current_price, coin?.instrument_name)}</td>
                    <td className={`px-4 py-2 ${getIndicatorColorClass('rsi', signal, coin)}`}>
                      {signal?.rsi ? signal.rsi.toFixed(2) : '-'}
                    </td>
                    <td className={`px-4 py-2 ${getIndicatorColorClass('ema10', signal, coin)}`}>
                      {signal?.ema10 ? formatNumber(signal.ema10, coin?.instrument_name) : '-'}
                    </td>
                    <td className={`px-4 py-2 ${getIndicatorColorClass('ma50', signal, coin)}`}>
                      {signal?.ma50 ? formatNumber(signal.ma50, coin?.instrument_name) : '-'}
                    </td>
                    <td className={`px-4 py-2 ${getIndicatorColorClass('ma200', signal, coin)}`}>
                      {signal?.ma200 ? formatNumber(signal.ma200, coin?.instrument_name) : '-'}
                    </td>
                    <td className="px-4 py-2">
                      {signal?.volume_ratio ? `${signal.volume_ratio.toFixed(2)}x` : '-'}
                    </td>
                    <td className="px-4 py-2">
                      {editingAmount[coin?.instrument_name] !== undefined ? (
                        <input
                          type="number"
                          step="0.01"
                          min="0"
                          value={editingAmount[coin?.instrument_name]}
                          onChange={(e) => setEditingAmount(prev => ({ ...prev, [coin?.instrument_name]: e.target.value }))}
                          onBlur={() => {
                            const value = editingAmount[coin?.instrument_name];
                            if (value !== undefined) {
                              handleAmountSave(coin?.instrument_name, value);
                            }
                          }}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                              const value = editingAmount[coin?.instrument_name];
                              if (value !== undefined) {
                                handleAmountSave(coin?.instrument_name, value);
                              }
                            } else if (e.key === 'Escape') {
                              setEditingAmount(prev => {
                                const updated = { ...prev };
                                delete updated[coin?.instrument_name];
                                return updated;
                              });
                            }
                          }}
                          aria-label={`Trade amount in USD for ${coin?.instrument_name}`}
                          className="w-20 px-2 py-1 border border-gray-300 rounded text-sm"
                          autoFocus
                        />
                      ) : (
                        <span
                          onClick={() => setEditingAmount(prev => ({ ...prev, [coin?.instrument_name]: coinAmounts[symbolKey] || '' }))}
                          className="cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 px-2 py-1 rounded border border-transparent hover:border-gray-300"
                          title="Click to edit Amount USD"
                        >
                          {coinAmounts[symbolKey] ? `$${coinAmounts[symbolKey]}` : '-'}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2">
                      {editingSLPercent[coin?.instrument_name] !== undefined ? (
                        <input
                          type="number"
                          step="0.01"
                          min="0"
                          value={editingSLPercent[coin?.instrument_name]}
                          onChange={(e) => setEditingSLPercent(prev => ({ ...prev, [coin?.instrument_name]: e.target.value }))}
                          onBlur={() => {
                            const value = editingSLPercent[coin?.instrument_name];
                            if (value !== undefined) {
                              handleSLPercentSave(coin?.instrument_name, value);
                            }
                          }}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                              const value = editingSLPercent[coin?.instrument_name];
                              if (value !== undefined) {
                                handleSLPercentSave(coin?.instrument_name, value);
                              }
                            } else if (e.key === 'Escape') {
                              setEditingSLPercent(prev => {
                                const updated = { ...prev };
                                delete updated[coin?.instrument_name];
                                return updated;
                              });
                            }
                          }}
                          className="w-16 px-2 py-1 border border-gray-300 rounded text-sm"
                          autoFocus
                          placeholder="%"
                        />
                      ) : (
                        <span
                          onClick={() => {
                            const displayed = getDisplayedSLTP(coin, symbolKey);
                            setEditingSLPercent(prev => ({ ...prev, [coin?.instrument_name]: displayed.slPercent || coinSLPercent[symbolKey] || '' }));
                          }}
                          className="cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 px-2 py-1 rounded border border-transparent hover:border-gray-300 cursor-help"
                          title={buildSLTPTooltip(coin, signal)}
                        >
                          {(() => {
                            const displayed = getDisplayedSLTP(coin, symbolKey);
                            return displayed.slPercent ? `${displayed.slPercent}%` : '-';
                          })()}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2">
                      {editingTPPercent[coin?.instrument_name] !== undefined ? (
                        <input
                          type="number"
                          step="0.01"
                          min="0"
                          value={editingTPPercent[coin?.instrument_name]}
                          onChange={(e) => setEditingTPPercent(prev => ({ ...prev, [coin?.instrument_name]: e.target.value }))}
                          onBlur={() => {
                            const value = editingTPPercent[coin?.instrument_name];
                            if (value !== undefined) {
                              handleTPPercentSave(coin?.instrument_name, value);
                            }
                          }}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                              const value = editingTPPercent[coin?.instrument_name];
                              if (value !== undefined) {
                                handleTPPercentSave(coin?.instrument_name, value);
                              }
                            } else if (e.key === 'Escape') {
                              setEditingTPPercent(prev => {
                                const updated = { ...prev };
                                delete updated[coin?.instrument_name];
                                return updated;
                              });
                            }
                          }}
                          className="w-16 px-2 py-1 border border-gray-300 rounded text-sm"
                          autoFocus
                          placeholder="%"
                        />
                      ) : (
                        <span
                          onClick={() => {
                            const displayed = getDisplayedSLTP(coin, symbolKey);
                            setEditingTPPercent(prev => ({ ...prev, [coin?.instrument_name]: displayed.tpPercent || coinTPPercent[symbolKey] || '' }));
                          }}
                          className="cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 px-2 py-1 rounded border border-transparent hover:border-gray-300 cursor-help"
                          title={buildSLTPTooltip(coin, signal)}
                        >
                          {(() => {
                            const displayed = getDisplayedSLTP(coin, symbolKey);
                            return displayed.tpPercent ? `${displayed.tpPercent}%` : '-';
                          })()}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2">
                      <button
                        onClick={() => handleTradeToggle(coin?.instrument_name)}
                        disabled={isCoinUpdating}
                        className={`px-3 py-1 rounded text-xs font-semibold transition-colors cursor-help ${
                          tradeEnabled
                            ? 'bg-green-500 text-white hover:bg-green-600'
                            : 'bg-red-500 text-white hover:bg-red-600'
                        } disabled:opacity-50`}
                        title={buildTradeTooltip(coin, signal)}
                      >
                        {isCoinUpdating ? '...' : tradeEnabled ? 'YES' : 'NO'}
                      </button>
                    </td>
                    <td className="px-4 py-2">
                      <button
                        onClick={() => handleMarginToggle(coin?.instrument_name)}
                        disabled={isCoinUpdating}
                        className={`px-3 py-1 rounded text-xs font-semibold transition-colors ${
                          coinMarginStatus[symbolKey]
                            ? 'bg-green-500 text-white hover:bg-green-600'
                            : 'bg-red-500 text-white hover:bg-red-600'
                        } disabled:opacity-50`}
                      >
                        {isCoinUpdating ? '...' : coinMarginStatus[symbolKey] ? 'YES' : 'NO'}
                      </button>
                    </td>
                    <td className="px-4 py-2">
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            if (!isCoinUpdating && coin?.instrument_name) {
                              handleAlertToggle(coin.instrument_name, 'master');
                            }
                          }}
                          disabled={isCoinUpdating || !coin?.instrument_name}
                          className={`px-2 py-1 rounded text-xs transition-colors ${
                            masterAlertEnabled
                              ? 'bg-blue-500 text-white hover:bg-blue-600'
                              : 'bg-gray-300 text-gray-700 hover:bg-gray-400'
                          } disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer`}
                          title="Master Alert"
                        >
                          M
                        </button>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            if (!isCoinUpdating && coin?.instrument_name) {
                              handleAlertToggle(coin.instrument_name, 'buy');
                            }
                          }}
                          disabled={isCoinUpdating || !coin?.instrument_name}
                          className={`px-2 py-1 rounded text-xs transition-colors ${
                            buyAlertEnabled
                              ? 'bg-green-500 text-white hover:bg-green-600'
                              : 'bg-gray-300 text-gray-700 hover:bg-gray-400'
                          } disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer`}
                          title="Buy Alert"
                        >
                          B
                        </button>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            if (!isCoinUpdating && coin?.instrument_name) {
                              handleAlertToggle(coin.instrument_name, 'sell');
                            }
                          }}
                          disabled={isCoinUpdating || !coin?.instrument_name}
                          className={`px-2 py-1 rounded text-xs transition-colors ${
                            sellAlertEnabled
                              ? 'bg-red-500 text-white hover:bg-red-600'
                              : 'bg-gray-300 text-gray-700 hover:bg-gray-400'
                          } disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer`}
                          title="Sell Alert"
                        >
                          S
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      
      <div className="mt-4 text-sm text-gray-500">
        Showing {sortedCoins.length} of {topCoins.length} coins
      </div>
    </div>
  );
}
