// frontend/src/utils/presetTooltips.ts
import { generateMockSeries } from "./miniChart";

function box(title: string, rules: string[]) {
  return `${title}\n\n${rules.map(r => `• ${r}`).join('\n')}`;
}

export function buildPresetTooltipHTML(
  preset: "swing" | "intraday" | "scalp"
) {
  if (preset === "swing") {
    return box("Swing Trading",
      [
        "BUY: Precio > MA50 > MA200 y RSI < 60 y Volumen > 1.2×",
        "SELL: Precio < MA50 < MA200 y RSI > 50",
        "Horizonte: 3-10 días"
      ]
    );
  }
  
  if (preset === "intraday") {
    return box("Intradía Trading",
      [
        "BUY: Precio > EMA10 > MA50 y RSI < 55",
        "SELL: Precio < EMA10 < MA50 y RSI > 60",
        "Horizonte: 2-12 horas"
      ]
    );
  }
  
  // Scalp
  return box("Scalp Trading",
    [
      "BUY: RSI < 40 y Precio cruza por encima de EMA10",
      "SELL: RSI > 70 o Precio cae por debajo de EMA10",
      "Horizonte: minutos"
    ]
  );
}

export function buildSignalTooltipHTML(
  signal: string,
  reason: string
) {
  return `Signal: ${signal}\n\n${reason}`;
}

// Función para generar series de datos para tooltips
export function generateSeriesForTooltip(
  currentPrice: number,
  currentEma10?: number,
  currentMa50?: number,
  currentMa200?: number
) {
  return generateMockSeries(currentPrice, currentEma10, currentMa50, currentMa200, 30);
}
