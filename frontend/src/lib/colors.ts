// frontend/src/lib/colors.ts
import { palette } from '@/theme/palette';

export function colorClass(status: 'buy' | 'wait' | 'sell') {
  switch (status) {
    case 'buy':
      return palette.badge.success;
    case 'sell':
      return palette.badge.danger;
    default:
      return palette.badge.neutral;
  }
}
