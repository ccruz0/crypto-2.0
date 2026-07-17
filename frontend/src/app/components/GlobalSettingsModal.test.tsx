import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import GlobalSettingsModal from '@/app/components/GlobalSettingsModal';
import { DEFAULT_TRADING_LIMITS } from '@/utils/tradingConfigUtils';

describe('GlobalSettingsModal', () => {
  afterEach(() => {
    cleanup();
  });

  it('accepts whole-dollar maxUsdPerOrder values under HTML step/min constraints', () => {
    render(
      <GlobalSettingsModal
        isOpen
        onClose={vi.fn()}
        tradingLimits={{ ...DEFAULT_TRADING_LIMITS, maxUsdPerOrder: 100 }}
        onSave={vi.fn().mockResolvedValue(undefined)}
      />
    );

    const input = screen.getByLabelText('Max USD per order') as HTMLInputElement;
    expect(input).toHaveAttribute('min', '0.01');
    expect(input).toHaveAttribute('step', '0.01');
    expect(input.value).toBe('100');
    expect(input.checkValidity()).toBe(true);
  });
});
