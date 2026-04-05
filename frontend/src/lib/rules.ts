// frontend/src/lib/rules.ts
export type Preset = "Swing" | "Intraday" | "Scalp";
export type Risk = "Conservador" | "Agresivo";

export const RULES: Record<Preset, Record<Risk, { rsi: number; tp: number; sl: number }>> = {
  Swing: {
    Conservador: { rsi: 45, tp: 0.08,  sl: 0.03 },
    Agresivo:    { rsi: 50, tp: 0.15,  sl: 0.06 },
  },
  Intraday: {
    Conservador: { rsi: 40, tp: 0.02,  sl: 0.01 },
    Agresivo:    { rsi: 45, tp: 0.04,  sl: 0.02 },
  },
  Scalp: {
    Conservador: { rsi: 35, tp: 0.003, sl: 0.002 },
    Agresivo:    { rsi: 40, tp: 0.01,  sl: 0.005 },
  },
};

export const getRule = (preset: Preset, risk: Risk) => RULES[preset]?.[risk] || null;

