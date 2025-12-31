# Strategy Config Modal Integration Guide

## Component Created

A new `StrategyConfigModal` component has been created at:
- `frontend/src/app/components/StrategyConfigModal.tsx`

## Features

The modal includes form controls for all Swing Conservative gating parameters:

1. **Basic Parameters**
   - RSI Buy Below / Sell Above
   - Volume Min Ratio
   - Min Price Change %

2. **Trend Filters**
   - Require price above MA200 (checkbox)
   - Require EMA10 above MA50 (checkbox)

3. **RSI Confirmation**
   - Require RSI cross-up (checkbox)
   - RSI cross level (number input)

4. **Candle Confirmation**
   - Require close above EMA10 (checkbox)
   - RSI rising N candles (number input)

5. **ATR Configuration**
   - ATR Period
   - ATR Multiplier (SL)
   - ATR Multiplier (TP) - Optional

6. **Stop Loss / Take Profit**
   - SL Fallback Percentage
   - Risk:Reward Ratio

7. **Moving Averages**
   - EMA10, MA50, MA200 checkboxes

## Integration Steps

To integrate the modal into the main dashboard page (`frontend/src/app/page.tsx`):

### 1. Import the component

```typescript
import StrategyConfigModal from '@/app/components/StrategyConfigModal';
```

### 2. Add handler functions

```typescript
const handleSaveStrategyConfig = useCallback((preset: Preset, riskMode: RiskMode, updatedRules: StrategyRules) => {
  setPresetsConfig(prev => ({
    ...prev,
    [preset]: {
      ...prev[preset],
      rules: {
        ...prev[preset].rules,
        [riskMode]: updatedRules
      }
    }
  }));
  
  // Optionally save to backend
  // Note: You may need to transform presetsConfig to TradingConfig format
}, []);
```

### 3. Add the modal to JSX

In the return statement (wherever the main dashboard content is rendered):

```typescript
<StrategyConfigModal
  isOpen={showSignalConfig}
  onClose={() => setShowSignalConfig(false)}
  preset={selectedConfigPreset}
  riskMode={selectedConfigRisk}
  rules={presetsConfig[selectedConfigPreset]?.rules[selectedConfigRisk] || PRESET_CONFIG[selectedConfigPreset].rules[selectedConfigRisk]}
  onSave={handleSaveStrategyConfig}
/>
```

### 4. Add button to open modal

Add a button somewhere in the UI (e.g., in a header, toolbar, or settings area):

```typescript
<button
  onClick={() => setShowSignalConfig(true)}
  className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
>
  Configure Strategy
</button>
```

## Notes

- The modal uses the existing state variables (`showSignalConfig`, `selectedConfigPreset`, `selectedConfigRisk`, `presetsConfig`)
- The `onSave` callback receives the updated rules and updates the `presetsConfig` state
- Backend saving can be implemented in the `handleSaveStrategyConfig` function by calling `saveTradingConfig` with the appropriate format
- The component handles form validation and error states internally



