/**
 * Custom hook for watchlist state management
 * Extracted from page.tsx for better organization
 */

import { useState, useCallback, useEffect } from 'react';
import { 
  getDashboard, 
  getTopCoins,
  WatchlistItem, 
  TopCoin 
} from '@/app/api';
import { logger } from '@/utils/logger';
import { normalizeSymbolKey } from '@/utils/formatting';

export interface UseWatchlistReturn {
  watchlistItems: WatchlistItem[];
  topCoins: TopCoin[];
  topCoinsLoading: boolean;
  topCoinsError: string | null;
  lastTopCoinsFetchAt: Date | null;
  coinTradeStatus: Record<string, boolean>;
  coinAmounts: Record<string, string>;
  coinSLPercent: Record<string, string>;
  coinTPPercent: Record<string, string>;
  coinBuyAlertStatus: Record<string, boolean>;
  coinSellAlertStatus: Record<string, boolean>;
  coinAlertStatus: Record<string, boolean>;
  fetchTopCoins: (preserveLocalChanges?: boolean, filterTradeYes?: boolean) => Promise<void>;
  setTopCoins: (coins: TopCoin[]) => void;
  setCoinTradeStatus: (status: Record<string, boolean> | ((prev: Record<string, boolean>) => Record<string, boolean>)) => void;
  setCoinAmounts: (amounts: Record<string, string> | ((prev: Record<string, string>) => Record<string, string>)) => void;
  setCoinSLPercent: (percent: Record<string, string> | ((prev: Record<string, string>) => Record<string, string>)) => void;
  setCoinTPPercent: (percent: Record<string, string> | ((prev: Record<string, string>) => Record<string, string>)) => void;
  setCoinBuyAlertStatus: (status: Record<string, boolean> | ((prev: Record<string, boolean>) => Record<string, boolean>)) => void;
  setCoinSellAlertStatus: (status: Record<string, boolean> | ((prev: Record<string, boolean>) => Record<string, boolean>)) => void;
  setCoinAlertStatus: (status: Record<string, boolean> | ((prev: Record<string, boolean>) => Record<string, boolean>)) => void;
}

export function useWatchlist(): UseWatchlistReturn {
  const [watchlistItems, setWatchlistItems] = useState<WatchlistItem[]>([]);
  const [topCoins, setTopCoins] = useState<TopCoin[]>([]);
  const [topCoinsLoading, setTopCoinsLoading] = useState(true);
  const [topCoinsError, setTopCoinsError] = useState<string | null>(null);
  const [lastTopCoinsFetchAt, setLastTopCoinsFetchAt] = useState<Date | null>(null);
  const [coinTradeStatus, setCoinTradeStatus] = useState<Record<string, boolean>>({});
  const [coinAmounts, setCoinAmounts] = useState<Record<string, string>>({});
  const [coinSLPercent, setCoinSLPercent] = useState<Record<string, string>>({});
  const [coinTPPercent, setCoinTPPercent] = useState<Record<string, string>>({});
  const [coinBuyAlertStatus, setCoinBuyAlertStatus] = useState<Record<string, boolean>>({});
  const [coinSellAlertStatus, setCoinSellAlertStatus] = useState<Record<string, boolean>>({});
  const [coinAlertStatus, setCoinAlertStatus] = useState<Record<string, boolean>>({});

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
      
      // Update coinTradeStatus from backend data
      const backendTradeStatus: Record<string, boolean> = {};
      fetchedCoins.forEach(coin => {
        if (coin.instrument_name && coin.trade_enabled !== undefined && coin.trade_enabled !== null) {
          backendTradeStatus[normalizeSymbolKey(coin.instrument_name)] = coin.trade_enabled;
        }
      });
      if (Object.keys(backendTradeStatus).length > 0) {
        setCoinTradeStatus(prev => ({ ...prev, ...backendTradeStatus }));
      }
      
      if (filterTradeYes !== undefined) {
        // Use backendTradeStatus for filtering since it's the fresh data from backend
        const filteredCoins = fetchedCoins.filter(coin => {
          const symbolKey = normalizeSymbolKey(coin.instrument_name);
          const isTradeYes = backendTradeStatus[symbolKey] === true;
          return filterTradeYes ? isTradeYes : !isTradeYes;
        });
        logger.info(`📊 Filtered to ${filterType}: ${filteredCoins.length} coins`);
        fetchedCoins = filteredCoins;
      }
      
      setTopCoins(fetchedCoins);
      setLastTopCoinsFetchAt(new Date());
      setTopCoinsError(null);
    } catch (err) {
      logger.error('Failed to fetch top coins:', err);
      const errorMessage = err instanceof Error ? err.message : 'Unknown error';
      setTopCoinsError(errorMessage);
      setLastTopCoinsFetchAt(new Date());
    } finally {
      if (!preserveLocalChanges) {
        setTopCoinsLoading(false);
      }
    }
  }, []);

  // Load watchlist items and top coins on mount
  useEffect(() => {
    const loadData = async () => {
      try {
        const items = await getDashboard();
        setWatchlistItems(items);
      } catch (err) {
        logger.error('Failed to load watchlist:', err);
      }
      // Fetch top coins on mount
      try {
        await fetchTopCoins(false);
      } catch (err) {
        logger.error('Failed to fetch top coins on mount:', err);
      }
    };
    loadData();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return {
    watchlistItems,
    topCoins,
    topCoinsLoading,
    topCoinsError,
    lastTopCoinsFetchAt,
    coinTradeStatus,
    coinAmounts,
    coinSLPercent,
    coinTPPercent,
    coinBuyAlertStatus,
    coinSellAlertStatus,
    coinAlertStatus,
    fetchTopCoins,
    setTopCoins,
    setCoinTradeStatus,
    setCoinAmounts,
    setCoinSLPercent,
    setCoinTPPercent,
    setCoinBuyAlertStatus,
    setCoinSellAlertStatus,
    setCoinAlertStatus,
  };
}



