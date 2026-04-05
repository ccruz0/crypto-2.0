export const palette = {
  badge: {
    success: 'palette-badge-success',
    danger: 'palette-badge-danger',
    warning: 'palette-badge-warning',
    neutral: 'palette-badge-neutral',
  },
  text: {
    profitStrong: 'palette-text-profit-strong',
    lossStrong: 'palette-text-loss-strong',
    neutralStrong: 'palette-text-neutral-strong',
    volumePositive: 'palette-text-volume-positive',
    volumeNegative: 'palette-text-volume-negative',
  },
} as const;

export type Palette = typeof palette;
