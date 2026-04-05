/**
 * Strategy Configuration Modal Component
 * Allows editing of strategy rules including new trend-change gating parameters
 */

import React, { useState, useEffect } from 'react';
import { saveTradingConfig, TradingConfig } from '@/app/api';
import type { StrategyRules, Preset, RiskMode } from '@/types/dashboard';
import { logger } from '@/utils/logger';

interface StrategyConfigModalProps {
  isOpen: boolean;
  onClose: () => void;
  preset: Preset;
  riskMode: RiskMode;
  rules: StrategyRules;
  onSave: (preset: Preset, riskMode: RiskMode, updatedRules: StrategyRules) => void;
}

export default function StrategyConfigModal({
  isOpen,
  onClose,
  preset,
  riskMode,
  rules,
  onSave,
}: StrategyConfigModalProps) {
  const [formData, setFormData] = useState<StrategyRules>(rules);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Update form data when props change
  useEffect(() => {
    setFormData(rules);
    setSaveError(null);
    setSaveSuccess(false);
  }, [rules, preset, riskMode]);

  if (!isOpen) return null;

  const handleInputChange = (field: string, value: unknown) => {
    setFormData((prev) => {
      const newData = { ...prev };
      const keys = field.split('.');
      let current: Record<string, unknown> = newData as Record<string, unknown>;

      for (let i = 0; i < keys.length - 1; i++) {
        const key = keys[i];
        const nextValue = current[key];
        if (!nextValue || typeof nextValue !== 'object' || Array.isArray(nextValue)) {
          current[key] = {};
        }
        current = current[key] as Record<string, unknown>;
      }

      current[keys[keys.length - 1]] = value;
      return newData;
    });
    setSaveError(null);
    setSaveSuccess(false);
  };

  const handleCheckboxChange = (field: string, checked: boolean) => {
    handleInputChange(field, checked);
  };

  const handleNumberChange = (field: string, value: string | null) => {
    const normalizedValue = value ?? '';
    const numValue = normalizedValue === '' ? undefined : parseFloat(normalizedValue);
    if (normalizedValue === '' || (!isNaN(numValue!) && numValue! >= 0)) {
      handleInputChange(field, numValue);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSaving(true);
    setSaveError(null);
    setSaveSuccess(false);

    try {
      // Call the onSave callback with updated rules
      onSave(preset, riskMode, formData);
      
      // Optionally save to backend
      // Note: The backend expects TradingConfig format, which might differ
      // For now, we'll rely on the parent component to handle backend saving
      
      setSaveSuccess(true);
      setTimeout(() => {
        setSaveSuccess(false);
        onClose();
      }, 1500);
    } catch (error) {
      logger.error('Failed to save strategy config:', error);
      setSaveError(error instanceof Error ? error.message : 'Failed to save configuration');
    } finally {
      setIsSaving(false);
    }
  };

  const handleCancel = () => {
    setFormData(rules); // Reset to original
    setSaveError(null);
    setSaveSuccess(false);
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white dark:bg-slate-800 rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] overflow-y-auto m-4">
        <div className="p-6">
          {/* Header */}
          <div className="flex justify-between items-center mb-6">
            <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
              Strategy Configuration: {preset} - {riskMode}
            </h2>
            <button
              onClick={handleCancel}
              className="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
            >
              ✕
            </button>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit}>
            {/* Basic Parameters Section */}
            <div className="mb-6">
              <h3 className="text-lg font-semibold mb-4 text-gray-800 dark:text-gray-200">
                Basic Parameters
              </h3>
              
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label
                    htmlFor="strategy-rsi-buy-below"
                    className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1"
                  >
                    RSI Buy Below
                  </label>
                  <input
                    id="strategy-rsi-buy-below"
                    type="number"
                    min="1"
                    max="100"
                    value={formData.rsi?.buyBelow ?? ''}
                    onChange={(e) => handleNumberChange('rsi.buyBelow', e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md dark:bg-slate-700 dark:border-slate-600 dark:text-white"
                  />
                </div>
                
                <div>
                  <label
                    htmlFor="strategy-rsi-sell-above"
                    className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1"
                  >
                    RSI Sell Above
                  </label>
                  <input
                    id="strategy-rsi-sell-above"
                    type="number"
                    min="1"
                    max="100"
                    value={formData.rsi?.sellAbove ?? ''}
                    onChange={(e) => handleNumberChange('rsi.sellAbove', e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md dark:bg-slate-700 dark:border-slate-600 dark:text-white"
                  />
                </div>
                
                <div>
                  <label
                    htmlFor="strategy-volume-min-ratio"
                    className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1"
                  >
                    Volume Min Ratio
                  </label>
                  <input
                    id="strategy-volume-min-ratio"
                    type="number"
                    min="0"
                    max="10"
                    step="0.1"
                    value={formData.volumeMinRatio ?? ''}
                    onChange={(e) => handleNumberChange('volumeMinRatio', e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md dark:bg-slate-700 dark:border-slate-600 dark:text-white"
                  />
                  <p className="text-xs text-gray-500 mt-1">Minimum volume ratio (e.g., 1.0 = 1x average)</p>
                </div>
                
                <div>
                  <label
                    htmlFor="strategy-min-price-change-pct"
                    className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1"
                  >
                    Min Price Change %
                  </label>
                  <input
                    id="strategy-min-price-change-pct"
                    type="number"
                    min="0"
                    max="100"
                    step="0.1"
                    value={formData.minPriceChangePct ?? ''}
                    onChange={(e) => handleNumberChange('minPriceChangePct', e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md dark:bg-slate-700 dark:border-slate-600 dark:text-white"
                  />
                </div>

                <div>
                  <label
                    htmlFor="strategy-max-orders-per-symbol-per-day"
                    className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1"
                  >
                    Max Orders Per Symbol / Day
                  </label>
                  <input
                    id="strategy-max-orders-per-symbol-per-day"
                    type="number"
                    min="0"
                    step="1"
                    value={formData.maxOrdersPerSymbolPerDay ?? ''}
                    onChange={(e) => handleNumberChange('maxOrdersPerSymbolPerDay', e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md dark:bg-slate-700 dark:border-slate-600 dark:text-white"
                  />
                  <p className="text-xs text-gray-500 mt-1">Leave empty to use global default</p>
                </div>
              </div>
            </div>

            {/* Trend Filters Section */}
            <div className="mb-6 border-t pt-4">
              <h3 className="text-lg font-semibold mb-4 text-gray-800 dark:text-gray-200">
                Trend Filters
              </h3>
              
              <div className="space-y-3">
                <label className="flex items-center">
                  <input
                    type="checkbox"
                    checked={formData.trendFilters?.require_price_above_ma200 ?? false}
                    onChange={(e) => handleCheckboxChange('trendFilters.require_price_above_ma200', e.target.checked)}
                    className="mr-2"
                  />
                  <span className="text-sm text-gray-700 dark:text-gray-300">
                    Require price above MA200
                  </span>
                </label>
                <p className="text-xs text-gray-500 ml-6">Only allow entries when price is above MA200</p>
                
                <label className="flex items-center">
                  <input
                    type="checkbox"
                    checked={formData.trendFilters?.require_ema10_above_ma50 ?? false}
                    onChange={(e) => handleCheckboxChange('trendFilters.require_ema10_above_ma50', e.target.checked)}
                    className="mr-2"
                  />
                  <span className="text-sm text-gray-700 dark:text-gray-300">
                    Require EMA10 above MA50
                  </span>
                </label>
                <p className="text-xs text-gray-500 ml-6">Only allow entries when EMA10 is above MA50</p>
              </div>
            </div>

            {/* RSI Confirmation Section */}
            <div className="mb-6 border-t pt-4">
              <h3 className="text-lg font-semibold mb-4 text-gray-800 dark:text-gray-200">
                RSI Confirmation
              </h3>
              
              <div className="space-y-3">
                <label className="flex items-center">
                  <input
                    type="checkbox"
                    checked={formData.rsiConfirmation?.require_rsi_cross_up ?? false}
                    onChange={(e) => handleCheckboxChange('rsiConfirmation.require_rsi_cross_up', e.target.checked)}
                    className="mr-2"
                  />
                  <span className="text-sm text-gray-700 dark:text-gray-300">
                    Require RSI cross-up
                  </span>
                </label>
                <p className="text-xs text-gray-500 ml-6">Require RSI to cross up above the level before allowing entry</p>
                
                <div className="ml-6">
                  <label
                    htmlFor="strategy-rsi-cross-level"
                    className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1"
                  >
                    RSI Cross Level
                  </label>
                  <input
                    id="strategy-rsi-cross-level"
                    type="number"
                    min="1"
                    max="100"
                    value={formData.rsiConfirmation?.rsi_cross_level ?? ''}
                    onChange={(e) => handleNumberChange('rsiConfirmation.rsi_cross_level', e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md dark:bg-slate-700 dark:border-slate-600 dark:text-white"
                    disabled={!formData.rsiConfirmation?.require_rsi_cross_up}
                  />
                  <p className="text-xs text-gray-500 mt-1">RSI must cross above this level to allow entry</p>
                </div>
              </div>
            </div>

            {/* Candle Confirmation Section */}
            <div className="mb-6 border-t pt-4">
              <h3 className="text-lg font-semibold mb-4 text-gray-800 dark:text-gray-200">
                Candle Confirmation
              </h3>
              
              <div className="space-y-3">
                <label className="flex items-center">
                  <input
                    type="checkbox"
                    checked={formData.candleConfirmation?.require_close_above_ema10 ?? false}
                    onChange={(e) => handleCheckboxChange('candleConfirmation.require_close_above_ema10', e.target.checked)}
                    className="mr-2"
                  />
                  <span className="text-sm text-gray-700 dark:text-gray-300">
                    Require close above EMA10
                  </span>
                </label>
                <p className="text-xs text-gray-500 ml-6">Require close price to be above EMA10</p>
                
                <div className="ml-6">
                  <label
                    htmlFor="strategy-rsi-rising-n-candles"
                    className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1"
                  >
                    RSI Rising N Candles
                  </label>
                  <input
                    id="strategy-rsi-rising-n-candles"
                    type="number"
                    min="0"
                    max="10"
                    value={formData.candleConfirmation?.require_rsi_rising_n_candles ?? ''}
                    onChange={(e) => handleNumberChange('candleConfirmation.require_rsi_rising_n_candles', e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md dark:bg-slate-700 dark:border-slate-600 dark:text-white"
                  />
                  <p className="text-xs text-gray-500 mt-1">Require RSI to be rising for N candles (0 = disabled)</p>
                </div>
              </div>
            </div>

            {/* ATR Configuration Section */}
            <div className="mb-6 border-t pt-4">
              <h3 className="text-lg font-semibold mb-4 text-gray-800 dark:text-gray-200">
                ATR Stop Loss Configuration
              </h3>
              
              <div className="grid grid-cols-3 gap-4">
                <div>
                  <label
                    htmlFor="strategy-atr-period"
                    className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1"
                  >
                    ATR Period
                  </label>
                  <input
                    id="strategy-atr-period"
                    type="number"
                    min="5"
                    max="50"
                    value={formData.atr?.period ?? ''}
                    onChange={(e) => handleNumberChange('atr.period', e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md dark:bg-slate-700 dark:border-slate-600 dark:text-white"
                  />
                </div>
                
                <div>
                  <label
                    htmlFor="strategy-atr-multiplier-sl"
                    className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1"
                  >
                    ATR Multiplier (SL)
                  </label>
                  <input
                    id="strategy-atr-multiplier-sl"
                    type="number"
                    min="0.5"
                    max="5"
                    step="0.1"
                    value={formData.atr?.multiplier_sl ?? ''}
                    onChange={(e) => handleNumberChange('atr.multiplier_sl', e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md dark:bg-slate-700 dark:border-slate-600 dark:text-white"
                  />
                  <p className="text-xs text-gray-500 mt-1">Stop loss = entry - (ATR × multiplier)</p>
                </div>
                
                <div>
                  <label
                    htmlFor="strategy-atr-multiplier-tp"
                    className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1"
                  >
                    ATR Multiplier (TP) - Optional
                  </label>
                  <input
                    id="strategy-atr-multiplier-tp"
                    type="number"
                    min="0.5"
                    max="10"
                    step="0.1"
                    value={formData.atr?.multiplier_tp ?? ''}
                    onChange={(e) => handleNumberChange('atr.multiplier_tp', e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md dark:bg-slate-700 dark:border-slate-600 dark:text-white"
                    placeholder="Leave empty to use RR"
                  />
                  <p className="text-xs text-gray-500 mt-1">Optional: Leave empty to use Risk:Reward ratio</p>
                </div>
              </div>
            </div>

            {/* Stop Loss / Take Profit Section */}
            <div className="mb-6 border-t pt-4">
              <h3 className="text-lg font-semibold mb-4 text-gray-800 dark:text-gray-200">
                Stop Loss / Take Profit
              </h3>
              
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label
                    htmlFor="strategy-sl-fallback-pct"
                    className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1"
                  >
                    SL Fallback Percentage
                  </label>
                  <input
                    id="strategy-sl-fallback-pct"
                    type="number"
                    min="0"
                    max="20"
                    step="0.1"
                    value={formData.sl?.fallbackPct ?? ''}
                    onChange={(e) => handleNumberChange('sl.fallbackPct', e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md dark:bg-slate-700 dark:border-slate-600 dark:text-white"
                  />
                  <p className="text-xs text-gray-500 mt-1">Used when ATR is unavailable (default: 3%)</p>
                </div>
                
                <div>
                  <label
                    htmlFor="strategy-tp-rr"
                    className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1"
                  >
                    Risk:Reward Ratio
                  </label>
                  <input
                    id="strategy-tp-rr"
                    type="number"
                    min="0.5"
                    max="5"
                    step="0.1"
                    value={formData.tp?.rr ?? ''}
                    onChange={(e) => handleNumberChange('tp.rr', e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md dark:bg-slate-700 dark:border-slate-600 dark:text-white"
                  />
                  <p className="text-xs text-gray-500 mt-1">Take profit = entry + (SL distance × RR)</p>
                </div>
              </div>
            </div>

            {/* Moving Averages Section */}
            <div className="mb-6 border-t pt-4">
              <h3 className="text-lg font-semibold mb-4 text-gray-800 dark:text-gray-200">
                Moving Averages
              </h3>
              
              <div className="grid grid-cols-3 gap-4">
                <label className="flex items-center">
                  <input
                    type="checkbox"
                    checked={formData.maChecks?.ema10 ?? false}
                    onChange={(e) => handleCheckboxChange('maChecks.ema10', e.target.checked)}
                    className="mr-2"
                  />
                  <span className="text-sm text-gray-700 dark:text-gray-300">EMA10</span>
                </label>
                
                <label className="flex items-center">
                  <input
                    type="checkbox"
                    checked={formData.maChecks?.ma50 ?? false}
                    onChange={(e) => handleCheckboxChange('maChecks.ma50', e.target.checked)}
                    className="mr-2"
                  />
                  <span className="text-sm text-gray-700 dark:text-gray-300">MA50</span>
                </label>
                
                <label className="flex items-center">
                  <input
                    type="checkbox"
                    checked={formData.maChecks?.ma200 ?? false}
                    onChange={(e) => handleCheckboxChange('maChecks.ma200', e.target.checked)}
                    className="mr-2"
                  />
                  <span className="text-sm text-gray-700 dark:text-gray-300">MA200</span>
                </label>
              </div>
            </div>

            {/* Error/Success Messages */}
            {saveError && (
              <div className="mb-4 p-3 bg-red-100 border border-red-400 text-red-700 rounded">
                {saveError}
              </div>
            )}
            
            {saveSuccess && (
              <div className="mb-4 p-3 bg-green-100 border border-green-400 text-green-700 rounded">
                Configuration saved successfully!
              </div>
            )}

            {/* Buttons */}
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
                {isSaving ? 'Saving...' : 'Save Configuration'}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}

