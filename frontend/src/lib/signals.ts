// frontend/src/lib/signals.ts
import { Preset, Risk, getRule } from "./rules";

export type Traffic = "buy" | "wait" | "sell";

export function evalRSIStatus({ rsiNow, preset, risk }: {
  rsiNow: number | null | undefined; 
  preset: Preset; 
  risk: Risk;
}): Traffic {
  if (rsiNow == null) return "wait";
  const rule = getRule(preset, risk);
  if (!rule) return "wait";
  if (rsiNow < rule.rsi) return "buy";   // cumple criterio entrada
  if (rsiNow > 70) return "sell";        // sobrecompra
  return "wait";
}

export function evalRSIStatusContextual({ rsiNow, preset, risk, method, price, resistanceUp }: {
  rsiNow: number | null | undefined; 
  preset: Preset; 
  risk: Risk; 
  method: "percent" | "resistance" | "atr"; 
  price?: number | null; 
  resistanceUp?: number | null;
}): Traffic {
  const base = evalRSIStatus({ rsiNow, preset, risk });
  if (base !== "sell") return base;
  if (method === "resistance" && rsiNow != null && resistanceUp != null && price != null) {
    return (rsiNow > 70 && price >= resistanceUp) ? "sell" : "wait";
  }
  return base;
}

export function evalMAStatus({ price, ma200, ma50, ema10, preset }: {
  price: number; 
  ma200?: number | null; 
  ma50?: number | null; 
  ema10?: number | null; 
  preset: Preset;
}): Traffic {
  const above = (p?: number | null) => p != null && price > p;
  const below = (p?: number | null) => p != null && price < p;

  if (preset === "Swing") {
    if (above(ma200) && above(ma50)) return "buy";
    if (below(ma50) && below(ma200)) return "sell";
    return "wait";
  }
  if (preset === "Intraday") {
    if (above(ma50) && above(ema10)) return "buy";
    if (below(ema10)) return "sell";
    return "wait";
  }
  // Scalp
  if (above(ema10)) return "buy";
  if (below(ema10)) return "sell";
  return "wait";
}

