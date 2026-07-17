/**
 * Global Settings Modal — strategy-agnostic trading guardrails.
 */

import React, { useEffect, useState } from 'react';
import type { TradingLimits } from '@/types/dashboard';
import { DEFAULT_TRADING_LIMITS } from '@/utils/tradingConfigUtils';
import { logger } from '@/utils/logger';

interface GlobalSettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  tradingLimits: TradingLimits;
  onSave: (updatedLimits: TradingLimits) => Promise<void>;
}

export default function GlobalSettingsModal({
  isOpen,
  onClose,
  tradingLimits,
  onSave,
}: GlobalSettingsModalProps) {
  const [limitsData, setLimitsData] = useState<TradingLimits>(tradingLimits);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    setLimitsData(tradingLimits);
    setSaveError(null);
    setSaveSuccess(false);
  }, [isOpen, tradingLimits]);

  if (!isOpen) return null;

  const handleLimitsChange = (
    field: keyof TradingLimits,
    value: string,
    minValue: number
  ) => {
    const numValue = value === '' ? undefined : parseFloat(value);
    if (
      value === '' ||
      (numValue !== undefined && !isNaN(numValue) && numValue >= minValue)
    ) {
      setLimitsData((prev) => ({
        ...prev,
        [field]: numValue ?? DEFAULT_TRADING_LIMITS[field],
      }));
    }
    setSaveError(null);
    setSaveSuccess(false);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSaving(true);
    setSaveError(null);
    setSaveSuccess(false);

    try {
      await onSave(limitsData);
      setSaveSuccess(true);
      setTimeout(() => {
        setSaveSuccess(false);
        onClose();
      }, 1500);
    } catch (error) {
      logger.error('Failed to save global settings:', error);
      setSaveError(error instanceof Error ? error.message : 'Failed to save settings');
    } finally {
      setIsSaving(false);
    }
  };

  const handleCancel = () => {
    setLimitsData(tradingLimits);
    setSaveError(null);
    setSaveSuccess(false);
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white dark:bg-slate-800 rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto m-4">
        <div className="p-6">
          <div className="flex justify-between items-start mb-6 gap-4">
            <div>
              <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
                Global Settings
              </h2>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Guardrails that apply to all coins, independent of strategy preset.
              </p>
            </div>
            <button
              type="button"
              onClick={handleCancel}
              className="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 shrink-0"
            >
              ✕
            </button>
          </div>

          <form onSubmit={handleSubmit}>
            <div className="mb-6">
              <h3 className="text-lg font-semibold text-gray-800 dark:text-gray-200 mb-4">
                Open order limits
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label
                    htmlFor="settings-max-open-orders-total"
                    className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1"
                  >
                    Max open positions (global)
                  </label>
                  <input
                    id="settings-max-open-orders-total"
                    type="number"
                    min="0"
                    step="1"
                    value={limitsData.maxOpenOrdersTotal}
                    onChange={(e) =>
                      handleLimitsChange('maxOpenOrdersTotal', e.target.value, 0)
                    }
                    className="w-full px-3 py-2 border border-gray-300 rounded-md dark:bg-slate-700 dark:border-slate-600 dark:text-white"
                  />
                  <p className="text-xs text-gray-500 mt-1">
                    TRADE BLOCKED when total open positions reach this limit (Portfolio watermark).
                  </p>
                </div>
                <div>
                  <label
                    htmlFor="settings-max-open-orders-per-coin"
                    className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1"
                  >
                    Max open positions per coin
                  </label>
                  <input
                    id="settings-max-open-orders-per-coin"
                    type="number"
                    min="1"
                    step="1"
                    value={limitsData.maxOpenOrdersPerCoin}
                    onChange={(e) =>
                      handleLimitsChange('maxOpenOrdersPerCoin', e.target.value, 1)
                    }
                    className="w-full px-3 py-2 border border-gray-300 rounded-md dark:bg-slate-700 dark:border-slate-600 dark:text-white"
                  />
                  <p className="text-xs text-gray-500 mt-1">
                    Signal Monitor per-symbol cap (Watchlist watermark).
                  </p>
                </div>
              </div>
            </div>

            <div className="mb-6 border-t pt-4">
              <h3 className="text-lg font-semibold text-gray-800 dark:text-gray-200 mb-4">
                Order throttling &amp; size
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label
                    htmlFor="settings-max-usd-per-order"
                    className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1"
                  >
                    Max USD per order
                  </label>
                  <input
                    id="settings-max-usd-per-order"
                    type="number"
                    min="0.01"
                    step="0.01"
                    value={limitsData.maxUsdPerOrder}
                    onChange={(e) =>
                      handleLimitsChange('maxUsdPerOrder', e.target.value, 0.01)
                    }
                    className="w-full px-3 py-2 border border-gray-300 rounded-md dark:bg-slate-700 dark:border-slate-600 dark:text-white"
                  />
                </div>
                <div>
                  <label
                    htmlFor="settings-min-seconds-between-orders"
                    className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1"
                  >
                    Min seconds between orders
                  </label>
                  <input
                    id="settings-min-seconds-between-orders"
                    type="number"
                    min="0"
                    step="1"
                    value={limitsData.minSecondsBetweenOrders}
                    onChange={(e) =>
                      handleLimitsChange('minSecondsBetweenOrders', e.target.value, 0)
                    }
                    className="w-full px-3 py-2 border border-gray-300 rounded-md dark:bg-slate-700 dark:border-slate-600 dark:text-white"
                  />
                </div>
                <div className="sm:col-span-2">
                  <label
                    htmlFor="settings-max-orders-per-symbol-per-day"
                    className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1"
                  >
                    Max orders per coin per day (global default)
                  </label>
                  <input
                    id="settings-max-orders-per-symbol-per-day"
                    type="number"
                    min="0"
                    step="1"
                    value={limitsData.maxOrdersPerSymbolPerDay}
                    onChange={(e) =>
                      handleLimitsChange('maxOrdersPerSymbolPerDay', e.target.value, 0)
                    }
                    className="w-full px-3 py-2 border border-gray-300 rounded-md dark:bg-slate-700 dark:border-slate-600 dark:text-white"
                  />
                  <p className="text-xs text-gray-500 mt-1">
                    Strategy presets can override this per coin; this is the fallback default.
                  </p>
                </div>
              </div>
            </div>

            {saveError && (
              <div className="mb-4 p-3 bg-red-100 border border-red-400 text-red-700 rounded">
                {saveError}
              </div>
            )}

            {saveSuccess && (
              <div className="mb-4 p-3 bg-green-100 border border-green-400 text-green-700 rounded">
                Settings saved successfully!
              </div>
            )}

            <div className="flex justify-end gap-3 pt-4 border-t">
              <button
                type="button"
                onClick={handleCancel}
                className="px-4 py-2 text-gray-700 bg-gray-200 rounded-md hover:bg-gray-300 dark:bg-slate-600 dark:text-gray-200 dark:hover:bg-slate-500"
                disabled={isSaving}
              >
                Cancel
              </button>
              <button
                type="submit"
                className="px-4 py-2 text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed"
                disabled={isSaving}
              >
                {isSaving ? 'Saving...' : 'Save Settings'}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
