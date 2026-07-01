import { describe, expect, it } from 'vitest';
import type { PresetConfig } from '@/types/dashboard';
import {
  DEFAULT_TRADING_LIMITS,
  parseTradingLimits,
  strategyRulesToPresetConfig,
} from './tradingConfigUtils';

const BASE_PRESET_CONFIG: PresetConfig = {
  Swing: {
    notificationProfile: 'swing',
    rules: {
      Conservative: { rsi: { buyBelow: 30, sellAbove: 70 }, maChecks: { ema10: true, ma50: true, ma200: true }, sl: {}, tp: {} },
      Aggressive: { rsi: { buyBelow: 45, sellAbove: 68 }, maChecks: { ema10: true, ma50: true, ma200: true }, sl: {}, tp: {} },
    },
  },
  Intraday: {
    notificationProfile: 'intraday',
    rules: {
      Conservative: { rsi: { buyBelow: 45, sellAbove: 70 }, maChecks: { ema10: true, ma50: true, ma200: false }, sl: {}, tp: {} },
      Aggressive: { rsi: { buyBelow: 50, sellAbove: 65 }, maChecks: { ema10: true, ma50: true, ma200: false }, sl: {}, tp: {} },
    },
  },
  Scalp: {
    notificationProfile: 'scalp',
    rules: {
      Conservative: { rsi: { buyBelow: 50, sellAbove: 70 }, maChecks: { ema10: true, ma50: false, ma200: false }, sl: {}, tp: {} },
      Aggressive: { rsi: { buyBelow: 55, sellAbove: 65 }, maChecks: { ema10: true, ma50: false, ma200: false }, sl: {}, tp: {} },
    },
  },
};

describe('parseTradingLimits', () => {
  it('returns defaults for missing or invalid input', () => {
    expect(parseTradingLimits(undefined)).toEqual(DEFAULT_TRADING_LIMITS);
    expect(parseTradingLimits(null)).toEqual(DEFAULT_TRADING_LIMITS);
    expect(parseTradingLimits({})).toEqual(DEFAULT_TRADING_LIMITS);
  });

  it('parses valid limits from config', () => {
    expect(parseTradingLimits({ maxOpenOrdersTotal: 8, maxOpenOrdersPerCoin: 2 })).toEqual({
      maxOpenOrdersTotal: 8,
      maxOpenOrdersPerCoin: 2,
    });
  });
});

describe('strategyRulesToPresetConfig', () => {
  it('preserves defaults when strategy_rules is empty', () => {
    expect(strategyRulesToPresetConfig(undefined, BASE_PRESET_CONFIG)).toBe(BASE_PRESET_CONFIG);
  });

  it('hydrates non-default preset values from backend', () => {
    const hydrated = strategyRulesToPresetConfig(
      {
        intraday: {
          notificationProfile: 'intraday',
          rules: {
            Conservative: {
              rsi: { buyBelow: 42, sellAbove: 72 },
              maChecks: { ema10: true, ma50: true, ma200: false },
              sl: {},
              tp: {},
              volumeMinRatio: 0.75,
            },
          },
        },
      },
      BASE_PRESET_CONFIG
    );

    expect(hydrated.Intraday.rules.Conservative.rsi?.buyBelow).toBe(42);
    expect(hydrated.Intraday.rules.Conservative.volumeMinRatio).toBe(0.75);
    expect(hydrated.Swing.rules.Conservative.rsi?.buyBelow).toBe(30);
  });

  it('does not overwrite other presets when one preset is saved', () => {
    const hydrated = strategyRulesToPresetConfig(
      {
        scalp: {
          notificationProfile: 'scalp',
          rules: {
            Aggressive: {
              rsi: { buyBelow: 60, sellAbove: 64 },
              maChecks: { ema10: true, ma50: false, ma200: false },
              sl: {},
              tp: {},
            },
          },
        },
      },
      BASE_PRESET_CONFIG
    );

    expect(hydrated.Scalp.rules.Aggressive.rsi?.buyBelow).toBe(60);
    expect(hydrated.Swing.rules.Conservative.rsi?.buyBelow).toBe(30);
  });
});
