# Swing Conservative UI Implementation - Next Steps

## ✅ Completed

1. **Backend Implementation** ✅
   - Configuration defaults updated
   - Signal generation logic with new gating rules
   - Migration logic for existing configs
   - Unit tests added
   - Deployment verified

2. **Frontend Types** ✅
   - TypeScript interfaces updated (`frontend/src/types/dashboard.ts`)
   - Default values in `PRESET_CONFIG` updated (`frontend/src/app/page.tsx`)

3. **Verification Script** ✅
   - Created `verify_swing_conservative_deployment.sh`
   - Verifies config files, parameters, and deployment status

## 🚧 Remaining: Frontend UI Form

The Strategy Setup panel UI form needs to be implemented/updated to include controls for the new gating parameters.

### Current State
- `presetsConfig` state exists (line ~1218 in `page.tsx`)
- `selectedConfigPreset` and `selectedConfigRisk` state exist
- `showSignalConfig` state exists (line ~1005) but modal might not be fully implemented
- `saveTradingConfig` function is imported but may not be connected to UI

### Required UI Components

The Strategy Setup form needs to be located/created with sections for:

#### 1. Trend Filters Section
- [ ] Checkbox: `require_price_above_ma200` (default: true)
- [ ] Checkbox: `require_ema10_above_ma50` (default: true)
- [ ] Helper text: "Filters signals to only allow entries when price is above MA200 and EMA10 is above MA50"

#### 2. RSI Confirmation Section
- [ ] Checkbox: `require_rsi_cross_up` (default: true)
- [ ] Number input: `rsi_cross_level` (default: 30, range: 1-100)
- [ ] Helper text: "Requires RSI to cross up above the specified level before allowing entry"

#### 3. Candle Confirmation Section
- [ ] Checkbox: `require_close_above_ema10` (default: true)
- [ ] Number input: `require_rsi_rising_n_candles` (default: 2, range: 0-10)
- [ ] Helper text: "Requires close price above EMA10 and RSI rising for N candles"

#### 4. ATR Stop Loss Section
- [ ] Number input: `atr.period` (default: 14, range: 5-50)
- [ ] Number input: `atr.multiplier_sl` (default: 1.5, range: 0.5-5.0, step: 0.1)
- [ ] Number input: `atr.multiplier_tp` (optional, default: null)
- [ ] Helper text: "ATR configuration for stop loss calculation"

### Implementation Steps

1. **Locate/Find the Strategy Setup Modal/Form**
   - Search for where `showSignalConfig` is used in JSX
   - Check if modal exists but is incomplete
   - Or create new modal component

2. **Add Form Sections**
   - Group controls into collapsible sections
   - Add validation (number ranges, required fields)
   - Add helper text for each control

3. **Connect to State**
   - Bind form inputs to `presetsConfig` state
   - Handle `selectedConfigPreset` and `selectedConfigRisk` changes
   - Update form when preset/risk mode changes

4. **Save Handler**
   - Connect form submit to `saveTradingConfig` API call
   - Update `presetsConfig` state on success
   - Show success/error messages

5. **Testing**
   - Test form rendering
   - Test form submission
   - Test loading saved config
   - Test validation

### Code Location Hints

- State definitions: ~lines 1218-1220 in `page.tsx`
- Form rendering: Search for modal/dialog JSX, or check signals tab
- API function: `saveTradingConfig` from `@/app/api`

### Quick Search Commands

```bash
# Find where showSignalConfig is used in JSX
grep -n "{showSignalConfig" frontend/src/app/page.tsx

# Find modal/dialog components
grep -n "Modal\|Dialog\|modal\|dialog" frontend/src/app/page.tsx

# Find button that opens config
grep -n "Strategy\|Config\|Setup" frontend/src/app/page.tsx -i
```



