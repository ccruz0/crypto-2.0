/**
 * Helpers for trading config hydration and persistence.
 */

import type { Preset, PresetConfig, RiskMode, StrategyRules, TradingLimits } from '@/types/dashboard';

const PRESET_KEY_MAP: Record<string, Preset> = {
  swing: 'Swing',
  intraday: 'Intraday',
  scalp: 'Scalp',
  auto: 'Auto',
};

export const DEFAULT_TRADING_LIMITS: TradingLimits = {
  maxOpenOrdersTotal: 10,
  maxOpenOrdersPerCoin: 3,
  maxUsdPerOrder: 100,
  minSecondsBetweenOrders: 600,
  maxOrdersPerSymbolPerDay: 2,
};

function parseLimitNumber(
  raw: unknown,
  fallback: number,
  minValue: number
): number {
  if (typeof raw === 'number' && !Number.isNaN(raw) && raw >= minValue) {
    return raw;
  }
  return fallback;
}

export function parseTradingLimits(raw: unknown): TradingLimits {
  if (!raw || typeof raw !== 'object') {
    return { ...DEFAULT_TRADING_LIMITS };
  }
  const limits = raw as Record<string, unknown>;
  return {
    maxOpenOrdersTotal: parseLimitNumber(
      limits.maxOpenOrdersTotal,
      DEFAULT_TRADING_LIMITS.maxOpenOrdersTotal,
      0
    ),
    maxOpenOrdersPerCoin: parseLimitNumber(
      limits.maxOpenOrdersPerCoin,
      DEFAULT_TRADING_LIMITS.maxOpenOrdersPerCoin,
      1
    ),
    maxUsdPerOrder: parseLimitNumber(
      limits.maxUsdPerOrder,
      DEFAULT_TRADING_LIMITS.maxUsdPerOrder,
      0.01
    ),
    minSecondsBetweenOrders: parseLimitNumber(
      limits.minSecondsBetweenOrders,
      DEFAULT_TRADING_LIMITS.minSecondsBetweenOrders,
      0
    ),
    maxOrdersPerSymbolPerDay: parseLimitNumber(
      limits.maxOrdersPerSymbolPerDay,
      DEFAULT_TRADING_LIMITS.maxOrdersPerSymbolPerDay,
      0
    ),
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
      rules?: Partial<Record<RiskMode | 'Learned', StrategyRules>>;
      locked?: boolean;
      param_version?: number;
    };

    if (!entry.rules || typeof entry.rules !== 'object') {
      continue;
    }

    const mergedRules: Record<RiskMode, StrategyRules> = { ...result[preset].rules };
    if (preset === 'Auto') {
      // Auto uses a single Learned band; mirror into Conservative for UI display.
      const learned =
        entry.rules.Learned ||
        entry.rules.Conservative ||
        mergedRules.Conservative;
      if (learned && typeof learned === 'object') {
        mergedRules.Conservative = {
          ...mergedRules.Conservative,
          ...learned,
        };
        mergedRules.Aggressive = {
          ...mergedRules.Aggressive,
          ...learned,
        };
      }
    } else {
      for (const riskMode of ['Conservative', 'Aggressive'] as RiskMode[]) {
        const backendRules = entry.rules[riskMode];
        if (backendRules && typeof backendRules === 'object') {
          mergedRules[riskMode] = {
            ...mergedRules[riskMode],
            ...backendRules,
          };
        }
      }
    }

    result[preset] = {
      notificationProfile: entry.notificationProfile ?? result[preset].notificationProfile,
      rules: mergedRules,
    };
  }

  return result;
}

export function tradingLimitsToConfigPayload(limits: TradingLimits): Record<string, number> {
  return {
    maxOpenOrdersTotal: limits.maxOpenOrdersTotal,
    maxOpenOrdersPerCoin: limits.maxOpenOrdersPerCoin,
    maxUsdPerOrder: limits.maxUsdPerOrder,
    minSecondsBetweenOrders: limits.minSecondsBetweenOrders,
    maxOrdersPerSymbolPerDay: limits.maxOrdersPerSymbolPerDay,
  };
}
