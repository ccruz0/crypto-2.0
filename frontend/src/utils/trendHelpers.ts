// trendHelpers.ts - Helpers para señales de tendencia y tooltips
export function computeTrendSignal(price: number, ma50: number, ma200: number): 'BUY' | 'SELL' | 'NEUTRAL' {
  if (price > ma50 && ma50 > ma200) return 'BUY';
  if (price < ma50 && ma50 < ma200) return 'SELL';
  return 'NEUTRAL';
}

export function buildReasons({ 
  price, 
  ma10w, 
  ema10, 
  ma50, 
  ma200, 
  signal 
}: {
  price: number;
  ma10w: number;
  ema10: number;
  ma50: number;
  ma200: number;
  signal: 'BUY' | 'SELL' | 'NEUTRAL';
}) {
  const round = (x: number) => (typeof x === 'number' ? x.toLocaleString(undefined, {maximumFractionDigits: 2}) : x);
  const side = (p: number, m: number) => (Math.abs((p-m)/m) <= 0.01 ? '≈ (cerca de)' : (p > m ? 'arriba' : 'abajo'));
  
  const signalReason =
    signal === 'BUY'
      ? `Señal BUY: Precio (${round(price)}) > MA50 (${round(ma50)}) > MA200 (${round(ma200)}). Tendencia alcista confirmada. EMA10=${round(ema10)}, MA10w=${round(ma10w)}.`
      : signal === 'SELL'
      ? `Señal SELL: Precio (${round(price)}) < MA50 (${round(ma50)}) < MA200 (${round(ma200)}). Tendencia bajista confirmada. EMA10=${round(ema10)}, MA10w=${round(ma10w)}.`
      : `Señal NEUTRAL: Precio ${price > ma50 ? '>' : '≤'} MA50 y MA50 ${ma50 > ma200 ? '>' : '≤'} MA200. Falta confirmación.`;

  return {
    signalReason,
    ma50Reason: `MA50: ${round(ma50)}. El precio está ${side(price, ma50)} (${round(price)}). Si Precio > MA50 y MA50 > MA200 ⇒ sesgo alcista intermedio.`,
    ma200Reason: `MA200: ${round(ma200)}. Media de largo plazo. Si Precio > MA200 ⇒ sesgo alcista macro; si < MA200 ⇒ sesgo bajista.`,
    ema10Reason: `EMA10: ${round(ema10)}. Momentum reciente (más sensible). Si EMA10 > MA50 ⇒ aceleración; si < MA50 ⇒ pérdida de momentum.`,
    ma10wReason: `MA10w: ${round(ma10w)} (10 semanas). Filtro útil para swings de medio plazo.`
  };
}

export function getPriceClass(price: number, ma50: number): string {
  const diff = Math.abs((price - ma50) / ma50);
  if (diff <= 0.01) return 'price-flat';
  return price > ma50 ? 'price-up' : 'price-down';
}

export function getMAClass(value: number, price: number): string {
  const diff = Math.abs((price - value) / value);
  if (diff <= 0.01) return 'price-flat';
  return price > value ? 'price-up' : 'price-down';
}

export function getRSIClass(rsi: number): string {
  if (rsi < 40) return 'price-up'; // Verde para sobreventa (oportunidad de compra)
  if (rsi > 70) return 'price-down'; // Rojo para sobrecompra (oportunidad de venta)
  return 'price-flat'; // Gris para rango neutral
}

export function getTrendClass(signal: 'BUY' | 'SELL' | 'NEUTRAL'): string {
  switch (signal) {
    case 'BUY': return 'trend-buy';
    case 'SELL': return 'trend-sell';
    case 'NEUTRAL': return 'trend-neutral';
    default: return '';
  }
}

// Reglas específicas por preset
export function computeSignalByPreset(
  preset: string, 
  price: number, 
  ema10: number, 
  ma50: number, 
  ma200: number, 
  rsi: number, 
  volume: number, 
  avgVolume: number
): { signal: 'BUY' | 'SELL' | 'NEUTRAL', reason: string } {
  const volFactor = volume / (avgVolume || 1);
  const round = (x: number) => x.toFixed(1);
  
  switch (preset) {
    case "swing":
      if (price > ma50 && ma50 > ma200 && rsi < 60 && volFactor > 1.2) {
        return {
          signal: "BUY",
          reason: `Swing: condiciones cumplidas. RSI=${round(rsi)}, volumen=${volFactor.toFixed(1)}×, medias alineadas (Price>MA50>MA200).`
        };
      }
      if (price < ma50 && ma50 < ma200 && rsi > 50) {
        return {
          signal: "SELL",
          reason: `Swing: señal bajista detectada. RSI=${round(rsi)}, medias descendentes (Price<MA50<MA200).`
        };
      }
      return {
        signal: "NEUTRAL",
        reason: `Swing: sin alineación completa, esperando confirmación. RSI=${round(rsi)}, volumen=${volFactor.toFixed(1)}×.`
      };

    case "intraday":
      if (price > ema10 && ema10 > ma50 && rsi < 55) {
        return {
          signal: "BUY",
          reason: `Intradía: condiciones cumplidas. RSI=${round(rsi)}, medias alineadas (Price>EMA10>MA50).`
        };
      }
      if (price < ema10 && ema10 < ma50 && rsi > 60) {
        return {
          signal: "SELL",
          reason: `Intradía: señal bajista detectada. RSI=${round(rsi)}, medias descendentes (Price<EMA10<MA50).`
        };
      }
      return {
        signal: "NEUTRAL",
        reason: `Intradía: sin alineación completa, esperando confirmación. RSI=${round(rsi)}.`
      };

    case "scalp":
      if (rsi < 40 && price > ema10) {
        return {
          signal: "BUY",
          reason: `Scalp: condiciones cumplidas. RSI=${round(rsi)} (sobreventa), Price>EMA10.`
        };
      }
      if (rsi > 70 || price < ema10) {
        return {
          signal: "SELL",
          reason: `Scalp: señal bajista detectada. RSI=${round(rsi)} ${rsi > 70 ? '(sobrecompra)' : ''}, Price<EMA10.`
        };
      }
      return {
        signal: "NEUTRAL",
        reason: `Scalp: sin condiciones extremas, esperando rebote. RSI=${round(rsi)}.`
      };

    default:
      return {
        signal: "NEUTRAL",
        reason: `Preset no reconocido: ${preset}.`
      };
  }
}

// Tooltips para presets
export function getPresetTooltip(preset: string): string {
  switch (preset) {
    case "swing":
      return "Basado en MA50/MA200. BUY si Price>MA50>MA200 y RSI<60. Operaciones de varios días (3-10 días).";
    case "intraday":
      return "Basado en EMA10/MA50. BUY si Price>EMA10>MA50 y RSI<55. Operaciones intradía (2-12 horas).";
    case "scalp":
      return "Basado en RSI y EMA10. BUY si RSI<40 y Price>EMA10. Movimientos rápidos (minutos).";
    default:
      return "Preset no reconocido";
  }
}
