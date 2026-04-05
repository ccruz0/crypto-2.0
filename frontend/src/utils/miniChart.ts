// frontend/src/utils/miniChart.ts
type MiniChartInput = {
  prices: number[];   // últimos 25-40 puntos
  ema10?: number[];   // opcional
  ma50?: number[];    // opcional
  ma200?: number[];   // opcional
};

const line = (pts: [number, number][], stroke: string, width = 1.5) =>
  `<path d="M${pts.map(p => p.join(',')).join(' L ')}" fill="none" stroke="${stroke}" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round"/>`;

export function buildMiniChartSVG({ prices, ema10, ma50, ma200 }: MiniChartInput, w = 180, h = 60): string {
  const series = [prices, ema10, ma50, ma200].filter(Boolean) as number[][];
  const flat = series.flat();
  const min = Math.min(...flat);
  const max = Math.max(...flat);
  const n = prices.length;
  const x = (i: number) => (i / (n - 1)) * (w - 8) + 4;
  const y = (v: number) => h - 4 - ((v - min) / (max - min || 1)) * (h - 8);

  const toPts = (arr?: number[]) => (arr ?? []).map((v, i) => [x(i), y(v)] as [number, number]);

  const grid = `
    <rect x="0" y="0" width="${w}" height="${h}" rx="6" ry="6" fill="#0f172a" stroke="#1f2937"/>
    <line x1="0" y1="${h-20}" x2="${w}" y2="${h-20}" stroke="#334155" stroke-dasharray="3 3"/>
  `;

  const priceLine  = line(toPts(prices),  "#9CA3AF", 1.6); // gris
  const emaLine    = ema10 ? line(toPts(ema10), "#3B82F6", 1.6) : "";
  const ma50Line   = ma50  ? line(toPts(ma50),  "#F59E0B", 1.6) : "";
  const ma200Line  = ma200 ? line(toPts(ma200), "#EF4444", 1.6) : "";

  return `
  <svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
    ${grid}
    ${ma200Line}${ma50Line}${emaLine}${priceLine}
  </svg>`;
}

// Función para generar series de datos simulados si no tenemos datos históricos
export function generateMockSeries(currentPrice: number, currentEma10?: number, currentMa50?: number, currentMa200?: number, length = 30): MiniChartInput {
  const prices: number[] = [];
  const ema10: number[] = [];
  const ma50: number[] = [];
  const ma200: number[] = [];

  // Generar variación aleatoria alrededor del precio actual
  for (let i = 0; i < length; i++) {
    const variation = (Math.random() - 0.5) * 0.1; // ±5% variación
    const price = currentPrice * (1 + variation);
    prices.push(price);

    if (currentEma10) {
      const emaVariation = (Math.random() - 0.5) * 0.08;
      ema10.push(currentEma10 * (1 + emaVariation));
    }

    if (currentMa50) {
      const ma50Variation = (Math.random() - 0.5) * 0.06;
      ma50.push(currentMa50 * (1 + ma50Variation));
    }

    if (currentMa200) {
      const ma200Variation = (Math.random() - 0.5) * 0.04;
      ma200.push(currentMa200 * (1 + ma200Variation));
    }
  }

  return {
    prices,
    ema10: currentEma10 ? ema10 : undefined,
    ma50: currentMa50 ? ma50 : undefined,
    ma200: currentMa200 ? ma200 : undefined
  };
}

