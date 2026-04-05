/**
 * Custom hook for trading configuration state management
 * Extracted from page.tsx for better organization
 */

import { useState, useCallback, useEffect } from 'react';
import { getTradingConfig, getDataSourcesStatus, TradingConfig, DataSourceStatus } from '@/app/api';
import { logger } from '@/utils/logger';

export interface UseTradingConfigReturn {
  tradingConfig: TradingConfig | null;
  dataSourceStatus: DataSourceStatus | null;
  fetchTradingConfig: () => Promise<void>;
  fetchDataSourceStatus: () => Promise<void>;
  setTradingConfig: (config: TradingConfig | null) => void;
}

export function useTradingConfig(): UseTradingConfigReturn {
  const [tradingConfig, setTradingConfig] = useState<TradingConfig | null>(null);
  const [dataSourceStatus, setDataSourceStatus] = useState<DataSourceStatus | null>(null);

  const fetchTradingConfig = useCallback(async () => {
    try {
      logger.info('🔄 Fetching trading config...');
      const config = await getTradingConfig();
      if (config) {
        setTradingConfig(config);
        logger.info('✅ Backend config loaded - initial load complete');
      }
    } catch (err) {
      logger.logHandledError(
        'fetchTradingConfig',
        'Failed to fetch trading config; using cached values',
        err,
        'warn'
      );
    }
  }, []);

  const fetchDataSourceStatus = useCallback(async () => {
    try {
      const status = await getDataSourcesStatus();
      setDataSourceStatus(status);
    } catch (err) {
      logger.logHandledError(
        'fetchDataSourceStatus',
        'Failed to fetch data source status; will retry on next refresh',
        err,
        'warn'
      );
    }
  }, []);

  useEffect(() => {
    fetchTradingConfig();
    fetchDataSourceStatus();
  }, [fetchTradingConfig, fetchDataSourceStatus]);

  return {
    tradingConfig,
    dataSourceStatus,
    fetchTradingConfig,
    fetchDataSourceStatus,
    setTradingConfig,
  };
}



