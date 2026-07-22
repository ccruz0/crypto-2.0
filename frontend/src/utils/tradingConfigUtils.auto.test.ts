import { describe, expect, it } from 'vitest';
import type { PresetConfig } from '@/types/dashboard';
import { isAutoPreset } from '@/types/dashboard';
import { strategyRulesToPresetConfig } from './tradingConfigUtils';

const BASE_PRESET_CONFIG: PresetConfig = {
  Swing: {
    notificationProfile: 'swing',
    rules: {
      Conservative: {
        rsi: { buyBelow: 30, sellAbove: 70 },
        maChecks: { ema10: true, ma50: true, ma200: true },
        sl: {},
        tp: {},
      },
      Aggressive: {
        rsi: { buyBelow: 45, sellAbove: 68 },
        maChecks: { ema10: true, ma50: true, ma200: true },
        sl: {},
        tp: {},
      },
    },
  },
  Intraday: {
    notificationProfile: 'intraday',
    rules: {
      Conservative: {
        rsi: { buyBelow: 45, sellAbove: 70 },
        maChecks: { ema10: true, ma50: true, ma200: false },
        sl: {},
        tp: {},
      },
      Aggressive: {
        rsi: { buyBelow: 50, sellAbove: 65 },
        maChecks: { ema10: true, ma50: true, ma200: false },
        sl: {},
        tp: {},
      },
    },
  },
  Scalp: {
    notificationProfile: 'scalp',
    rules: {
      Conservative: {
        rsi: { buyBelow: 50, sellAbove: 70 },
        maChecks: { ema10: true, ma50: false, ma200: false },
        sl: {},
        tp: {},
      },
      Aggressive: {
        rsi: { buyBelow: 55, sellAbove: 65 },
        maChecks: { ema10: true, ma50: false, ma200: false },
        sl: {},
        tp: {},
      },
    },
  },
  Auto: {
    notificationProfile: 'swing',
    rules: {
      Conservative: {
        rsi: { buyBelow: 30, sellAbove: 70 },
        maChecks: { ema10: true, ma50: true, ma200: true },
        sl: {},
        tp: {},
      },
      Aggressive: {
        rsi: { buyBelow: 30, sellAbove: 70 },
        maChecks: { ema10: true, ma50: true, ma200: true },
        sl: {},
        tp: {},
      },
    },
  },
};

describe('isAutoPreset', () => {
  it('detects Auto / auto', () => {
    expect(isAutoPreset('Auto')).toBe(true);
    expect(isAutoPreset('auto')).toBe(true);
    expect(isAutoPreset('Swing')).toBe(false);
  });
});

describe('strategyRulesToPresetConfig auto', () => {
  it('maps Learned band into Auto Conservative display slot', () => {
    const hydrated = strategyRulesToPresetConfig(
      {
        auto: {
          notificationProfile: 'swing',
          locked: true,
          rules: {
            Learned: {
              rsi: { buyBelow: 28, sellAbove: 72 },
              maChecks: { ema10: true, ma50: true, ma200: true },
              sl: { atrMult: 1.5 },
              tp: { rr: 1.5 },
              volumeMinRatio: 1.25,
            },
          },
        },
      },
      BASE_PRESET_CONFIG
    );
    expect(hydrated.Auto.rules.Conservative.rsi?.buyBelow).toBe(28);
    expect(hydrated.Auto.rules.Conservative.volumeMinRatio).toBe(1.25);
    expect(hydrated.Auto.rules.Aggressive.rsi?.buyBelow).toBe(28);
  });
});
