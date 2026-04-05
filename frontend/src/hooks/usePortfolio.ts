/**
 * Custom hook for portfolio state management
 * Extracted from page.tsx for better organization
 */

import { useState, useCallback, useRef } from 'react';
import { 
  getDashboardState, 
  getDashboardSnapshot, 
  getTPSLOrderValues,
  DashboardState, 
  DashboardBalance, 
  PortfolioAsset 
} from '@/app/api';
import { getApiUrl } from '@/lib/environment';
import { logger } from '@/utils/logger';
import { dashboardBalancesToPortfolioAssets } from '@/app/api';

const PORTFOLIO_UNAVAILABLE_MESSAGE = 'Portfolio data unavailable from backend. Please check API /dashboard/state, then retry.';

interface Loan {
  borrowed_usd_value?: number;
  [key: string]: unknown;
}

interface BotStatus {
  is_running: boolean;
  status: 'running' | 'stopped';
  reason: string | null;
  live_trading_enabled?: boolean;
  mode?: 'LIVE' | 'DRY_RUN';
}

export interface UsePortfolioReturn {
  portfolio: { assets: PortfolioAsset[]; total_value_usd: number } | null;
  portfolioLoading: boolean;
  portfolioError: string | null;
  totalBorrowed: number;
  realBalances: DashboardBalance[];
  botStatus: BotStatus | null;
  snapshotStale: boolean;
  snapshotStaleSeconds: number | null;
  snapshotLastUpdated: Date | null;
  fetchPortfolio: (options?: { showLoader?: boolean; backgroundRefresh?: boolean }) => Promise<void>;
  setBotStatus: (status: BotStatus | null) => void;
}

export function usePortfolio(): UsePortfolioReturn {
  const [portfolio, setPortfolio] = useState<{ assets: PortfolioAsset[]; total_value_usd: number } | null>(null);
  const [totalBorrowed, setTotalBorrowed] = useState<number>(0);
  const [realBalances, setRealBalances] = useState<DashboardBalance[]>([]);
  const [portfolioLoading, setPortfolioLoading] = useState(true);
  const [portfolioError, setPortfolioError] = useState<string | null>(null);
  const [botStatus, setBotStatus] = useState<BotStatus | null>(null);
  const [snapshotStale, setSnapshotStale] = useState<boolean>(false);
  const [snapshotStaleSeconds, setSnapshotStaleSeconds] = useState<number | null>(null);
  const [snapshotLastUpdated, setSnapshotLastUpdated] = useState<Date | null>(null);

  // Helper function to update portfolio from dashboard state
  const updatePortfolioFromState = useCallback((dashboardState: DashboardState, source: string) => {
    try {
      // Expose latest dashboard state globally so helpers can access unified open_position_counts
      (window as Window & { __LAST_DASHBOARD_STATE__?: DashboardState }).__LAST_DASHBOARD_STATE__ = dashboardState;
    } catch {
      // Ignore if window is not available (e.g., during SSR)
    }
    
    // Set bot status
    if (dashboardState.bot_status) {
      if (dashboardState.bot_status.status === 'stopped' && 
          dashboardState.bot_status.reason === 'Status unavailable (checking...)') {
        // Transient error - don't update status
      } else {
        setBotStatus(dashboardState.bot_status);
      }
    }
    
    logger.info(`🔍 ${source} - dashboardState:`, {
      source: dashboardState.source,
      balancesCount: dashboardState.balances?.length || 0,
      totalUsd: dashboardState.total_usd_value,
      hasBalances: !!dashboardState.balances && dashboardState.balances.length > 0,
    });
    
    const dashboardFetchFailed = dashboardState.errors?.some(err => err?.startsWith('FETCH_FAILED')) ?? false;

    const fallbackToEmbeddedPortfolio = (reason?: string) => {
      const fallbackAssets = dashboardState.portfolio?.assets ?? [];
      const fallbackTotal =
        dashboardState.portfolio?.total_value_usd
        ?? dashboardState.total_usd_value
        ?? fallbackAssets.reduce((sum, asset) => sum + (asset.value_usd ?? 0), 0);
      logger.info(`📊 Falling back to embedded portfolio data (${fallbackAssets.length} assets, total=$${fallbackTotal.toFixed(2)})`);
      setPortfolio({ assets: fallbackAssets, total_value_usd: fallbackTotal });
      setPortfolioError(dashboardFetchFailed ? PORTFOLIO_UNAVAILABLE_MESSAGE : null);
    };

    // PREFER portfolio.assets (v4.0 format) - it's already in the correct format with usd_value
    if (dashboardState.portfolio?.assets && dashboardState.portfolio.assets.length > 0) {
      const portfolioAssets = dashboardState.portfolio.assets
        .filter(asset => asset && (asset.coin || asset.currency))
        .map(asset => ({
          ...asset,
          // Ensure value_usd is preserved (don't lose 0 values)
          value_usd: asset.value_usd ?? asset.usd_value ?? 0,
          updated_at: asset.updated_at ?? new Date().toISOString()
        }));

      if (portfolioAssets.length > 0) {
        const calculatedTotal = portfolioAssets.reduce((sum, asset) => sum + (asset.value_usd ?? 0), 0);
        const totalUsd = dashboardState.portfolio?.total_value_usd ?? calculatedTotal;
        
        const borrowedAmount = portfolioAssets
          .filter(asset => {
            const coin = (asset.coin || asset.currency || '').toUpperCase();
            return (coin === 'USD' || coin === 'USDT') && (asset.value_usd ?? 0) < 0;
          })
          .reduce((sum, asset) => sum + Math.abs(asset.value_usd ?? 0), 0);
        
        if (borrowedAmount > 0) {
          setTotalBorrowed(borrowedAmount);
        }

        logger.info(`✅ Processed ${portfolioAssets.length} assets from portfolio.assets`);
        logger.info(`📊 Total Portfolio Value (backend=${dashboardState.total_usd_value ?? 0}, portfolio.total=${dashboardState.portfolio?.total_value_usd ?? 0}, calculated=${calculatedTotal})`);

        setPortfolio({ assets: portfolioAssets, total_value_usd: totalUsd });
        setPortfolioError(dashboardFetchFailed ? PORTFOLIO_UNAVAILABLE_MESSAGE : null);
        
        // Also set realBalances for backward compatibility
        const normalizedBalances = dashboardState.balances?.filter(bal => bal?.asset) ?? [];
        setRealBalances(normalizedBalances);
        
        return true;
      }
    }

    // FALLBACK: Convert balances if portfolio.assets is not available
    if (dashboardState.balances && dashboardState.balances.length > 0) {
      const normalizedBalances = dashboardState.balances.filter(bal => bal?.asset);
      setRealBalances(normalizedBalances);

      const assetsWithValues = dashboardBalancesToPortfolioAssets(normalizedBalances)
        .filter(asset => asset && asset.coin)
        .map(asset => ({
          ...asset,
          updated_at: new Date().toISOString()
        }));

      if (assetsWithValues.length > 0) {
        const calculatedTotal = assetsWithValues.reduce((sum, asset) => sum + (asset.value_usd ?? 0), 0);
        const totalUsd = calculatedTotal;
        
        const borrowedAmount = assetsWithValues
          .filter(asset => {
            const coin = asset.coin?.toUpperCase() || '';
            return (coin === 'USD' || coin === 'USDT') && (asset.value_usd ?? 0) < 0;
          })
          .reduce((sum, asset) => sum + Math.abs(asset.value_usd ?? 0), 0);
        
        if (borrowedAmount > 0) {
          setTotalBorrowed(borrowedAmount);
        }

        logger.info(`✅ Processed ${assetsWithValues.length} assets from ${normalizedBalances.length} balances (fallback)`);
        logger.info(`📊 Total Portfolio Value (backend=${dashboardState.total_usd_value ?? 0}, calculated=${calculatedTotal})`);

        setPortfolio({ assets: assetsWithValues, total_value_usd: totalUsd });
        setPortfolioError(dashboardFetchFailed ? PORTFOLIO_UNAVAILABLE_MESSAGE : null);
        return true;
      } else {
        fallbackToEmbeddedPortfolio();
        return false;
      }
    } else {
      fallbackToEmbeddedPortfolio('⚠️ No balances or portfolio.assets in dashboardState, using embedded portfolio data');
      return false;
    }
  }, []);

  const fetchPortfolio = useCallback(async (options: { showLoader?: boolean; backgroundRefresh?: boolean } = {}) => {
    const { showLoader = false, backgroundRefresh = false } = options;
    if (showLoader) {
      setPortfolioLoading(true);
    }
    
    try {
      // STEP 1: Load snapshot FIRST (fast, cached)
      logger.info('📸 Loading dashboard snapshot (fast)...');
      let snapshotLoaded = false;
      try {
        const snapshot = await getDashboardSnapshot();
        const dashboardState = snapshot.data;
        
        setSnapshotStale(snapshot.stale);
        setSnapshotStaleSeconds(snapshot.stale_seconds);
        if (snapshot.last_updated_at) {
          setSnapshotLastUpdated(new Date(snapshot.last_updated_at));
        }
        
        if (!snapshot.empty && dashboardState.balances && dashboardState.balances.length > 0) {
          logger.info(`✅ Snapshot loaded with ${dashboardState.balances.length} balances - displaying immediately`);
          snapshotLoaded = updatePortfolioFromState(dashboardState, 'fetchPortfolio:snapshot');

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
              setTotalBorrowed(0);
            }
            
            try {
              const tpSlValues = await getTPSLOrderValues();
              // Store TP/SL values if needed
            } catch {
              // Silently handle TP/SL fetch errors
            }
          })();
        }
      } catch (snapshotErr) {
        logger.logHandledError(
          'fetchPortfolio:snapshot',
          'Failed to load snapshot - will try background refresh',
          snapshotErr,
          'warn'
        );
      }
      
      // STEP 2: Background refresh with full state
      if (!backgroundRefresh) {
        logger.info('🔄 Starting background refresh with full dashboard state...');
        (async () => {
          try {
            const dashboardState = await getDashboardState();
            logger.info('✅ Background refresh completed - updating portfolio with fresh data');
            updatePortfolioFromState(dashboardState, 'fetchPortfolio:background');
            
            try {
              const freshSnapshot = await getDashboardSnapshot();
              setSnapshotStale(freshSnapshot.stale);
              setSnapshotStaleSeconds(freshSnapshot.stale_seconds);
              if (freshSnapshot.last_updated_at) {
                setSnapshotLastUpdated(new Date(freshSnapshot.last_updated_at));
              }
            } catch (snapshotErr) {
              const errorMsg = snapshotErr instanceof Error ? snapshotErr.message : String(snapshotErr);
              if (!errorMsg.includes('Failed to fetch') && !errorMsg.includes('NetworkError')) {
                logger.debug('Background snapshot refresh error:', snapshotErr);
              }
            }
          } catch (refreshErr) {
            logger.logHandledError(
              'fetchPortfolio:background',
              'Background refresh failed - keeping snapshot data visible',
              refreshErr,
              'warn'
            );
            if (!snapshotLoaded) {
              setPortfolioError('Background refresh failed. Showing cached data if available.');
            }
          }
        })();
      }
    } catch (err) {
      logger.logHandledError(
        'fetchPortfolio',
        'Failed to fetch portfolio - keeping last known data visible',
        err,
        'warn'
      );
      setPortfolioError('Failed to load portfolio. Retrying in background...');
    } finally {
      setPortfolioLoading(false);
    }
  }, [updatePortfolioFromState]);

  return {
    portfolio,
    portfolioLoading,
    portfolioError,
    totalBorrowed,
    realBalances,
    botStatus,
    snapshotStale,
    snapshotStaleSeconds,
    snapshotLastUpdated,
    fetchPortfolio,
    setBotStatus,
  };
}




