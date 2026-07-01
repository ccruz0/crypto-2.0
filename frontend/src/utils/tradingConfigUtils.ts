/**
 * Helpers for trading config hydration and persistence.
 */

import type { Preset, PresetConfig, RiskMode, StrategyRules, TradingLimits } from '@/types/dashboard';

const PRESET_KEY_MAP: Record<string, Preset> = {
  swing: 'Swing',
  intraday: 'Intraday',
  scalp: 'Scalp',
};

export const DEFAULT_TRADING_LIMITS: TradingLimits = {
  maxOpenOrdersTotal: 5,
  maxOpenOrdersPerCoin: 1,
};

export function parseTradingLimits(raw: unknown): TradingLimits {
  if (!raw || typeof raw !== 'object') {
    return { ...DEFAULT_TRADING_LIMITS };
  }
  const limits = raw as Record<string, unknown>;
  const total = limits.maxOpenOrdersTotal;
  const perCoin = limits.maxOpenOrdersPerCoin;
  return {
    maxOpenOrdersTotal:
      typeof total === 'number' && total >= 0 ? total : DEFAULT_TRADING_LIMITS.maxOpenOrdersTotal,
    maxOpenOrdersPerCoin:
      typeof perCoin === 'number' && perCoin >= 1
        ? perCoin
        : DEFAULT_TRADING_LIMITS.maxOpenOrdersPerCoin,
  };
}

/**
 * Merge backend strategy_rules into frontend PresetConfig, preserving defaults for missing presets.
 */
export function strategyRulesToPresetConfig(
  strategyRules: Record<string, unknown> | undefined,
  defaults: PresetConfig
): PresetConfig {
  if (!strategyRules || typeof strategyRules !== 'object') {
    return defaults;
  }

  const result: PresetConfig = { ...defaults };

  for (const [presetKey, presetData] of Object.entries(strategyRules)) {
    const preset = PRESET_KEY_MAP[presetKey.toLowerCase()];
    if (!preset || !presetData || typeof presetData !== 'object') {
      continue;
    }

    const entry = presetData as {
      notificationProfile?: 'swing' | 'intraday' | 'scalp';
      rules?: Partial<Record<RiskMode, StrategyRules>>;
    };

    if (!entry.rules || typeof entry.rules !== 'object') {
      continue;
    }

    const mergedRules: Record<RiskMode, StrategyRules> = { ...result[preset].rules };
    for (const riskMode of ['Conservative', 'Aggressive'] as RiskMode[]) {
      const backendRules = entry.rules[riskMode];
      if (backendRules && typeof backendRules === 'object') {
        mergedRules[riskMode] = {
          ...mergedRules[riskMode],
          ...backendRules,
        };
      }
    }

    result[preset] = {
      notificationProfile: entry.notificationProfile ?? result[preset].notificationProfile,
      rules: mergedRules,
    };
  }

  return result;
}
