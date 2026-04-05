/**
 * Custom hook for trading signals state management
 * Extracted from page.tsx for better organization
 */

import { useState, useCallback } from 'react';
import { getTradingSignals, TradingSignals } from '@/app/api';
import { logger } from '@/utils/logger';

export interface UseSignalsReturn {
  signals: Record<string, TradingSignals | null>;
  fetchSignals: (symbol: string) => Promise<TradingSignals | null>;
  setSignals: (signals: Record<string, TradingSignals | null> | ((prev: Record<string, TradingSignals | null>) => Record<string, TradingSignals | null>)) => void;
}

export function useSignals(): UseSignalsReturn {
  const [signals, setSignals] = useState<Record<string, TradingSignals | null>>({});

  const fetchSignals = useCallback(async (symbol: string): Promise<TradingSignals | null> => {
    try {
      logger.debug(`🔄 Fetching signals for ${symbol}...`);
      const signal = await getTradingSignals(symbol);
      if (signal) {
        setSignals(prev => ({ ...prev, [symbol]: signal }));
        return signal;
      }
      return null;
    } catch (err) {
      logger.logHandledError(
        `fetchSignals:${symbol}`,
        `Failed to fetch signals for ${symbol}; will retry`,
        err,
        'warn'
      );
      return null;
    }
  }, []);

  return {
    signals,
    fetchSignals,
    setSignals,
  };
}



