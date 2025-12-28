# Testing Strategy Configuration UI

## Quick Start

### 1. Start Frontend Development Server

```bash
cd frontend
npm run dev
```

The server should start on `http://localhost:3000` (or next available port)

### 2. Open Dashboard

Navigate to: `http://localhost:3000`

### 3. Test the Strategy Configuration Modal

#### Step 1: Open the Modal
- Look for the **"⚙️ Configure Strategy"** button (should be in the dashboard header)
- Click the button
- Modal should open showing current configuration

#### Step 2: Verify Current Settings
Check that the modal displays the current Swing Conservative defaults:
- **RSI Buy Below**: 30
- **RSI Sell Above**: 70
- **Volume Min Ratio**: 1.0
- **Min Price Change %**: 3.0
- **Trend Filters**:
  - ✅ Require price above MA200 (checked)
  - ✅ Require EMA10 above MA50 (checked)
- **RSI Confirmation**:
  - ✅ Require RSI cross-up (checked)
  - RSI Cross Level: 30
- **Candle Confirmation**:
  - ✅ Require close above EMA10 (checked)
  - RSI Rising N Candles: 2
- **ATR Configuration**:
  - ATR Period: 14
  - ATR Multiplier (SL): 1.5
  - ATR Multiplier (TP): (empty/optional)
- **SL Fallback Percentage**: 3.0
- **Risk:Reward Ratio**: 1.5

#### Step 3: Test Form Interactions

**Test 1: Edit Basic Parameters**
- Change RSI Buy Below from 30 to 25
- Change Volume Min Ratio from 1.0 to 1.5
- Verify inputs accept the changes

**Test 2: Toggle Checkboxes**
- Uncheck "Require price above MA200"
- Check it again
- Verify state changes correctly

**Test 3: Edit Number Inputs**
- Change ATR Period from 14 to 20
- Change ATR Multiplier (SL) from 1.5 to 2.0
- Change RSI Cross Level from 30 to 35
- Verify all inputs update correctly

**Test 4: Test Validation**
- Try entering negative numbers (should be prevented or validated)
- Try entering values outside reasonable ranges
- Verify helper text is visible

#### Step 4: Save Configuration
- Click "Save Configuration" button
- Verify:
  - Success message appears
  - Modal closes automatically after 1.5 seconds
  - No errors in browser console

#### Step 5: Verify Persistence
- Open the modal again
- Verify that your changes are still there
- Note: Currently saves to local state only (backend persistence optional)

#### Step 6: Test Cancel
- Make some changes
- Click "Cancel" button
- Verify:
  - Modal closes
  - Changes are discarded (not saved)
  - Opening modal again shows original values

### 4. Check Browser Console

Open browser DevTools (F12) and check:
- No TypeScript errors
- No runtime errors
- Check Network tab for any failed API calls
- Check Console for any warnings

### 5. Test Edge Cases

**Test 1: Empty/Invalid Inputs**
- Clear a number input
- Try to save
- Verify behavior (should handle gracefully)

**Test 2: Rapid Clicking**
- Click save button multiple times quickly
- Verify no duplicate saves or errors

**Test 3: Modal Backdrop**
- Click outside the modal (on backdrop)
- Verify modal closes (if implemented) or stays open

**Test 4: Keyboard Navigation**
- Press Escape key
- Verify modal closes (if implemented)
- Tab through form fields
- Verify focus works correctly

### 6. Visual Testing

- ✅ Modal appears centered on screen
- ✅ Form sections are clearly separated
- ✅ Helper text is visible and readable
- ✅ Buttons are styled correctly
- ✅ Dark mode works (if applicable)
- ✅ Modal is scrollable if content is long
- ✅ Responsive on different screen sizes

### Expected Results

✅ **All tests pass if:**
- Modal opens/closes correctly
- Form fields update when edited
- Save button persists changes
- Cancel button discards changes
- No console errors
- UI looks correct
- Helper text is helpful

### Troubleshooting

**Issue: Button not visible**
- Check if the placeholder return statement is being used
- Verify button is in the JSX return

**Issue: Modal doesn't open**
- Check browser console for errors
- Verify `showSignalConfig` state is being set
- Check that `StrategyConfigModal` is imported correctly

**Issue: Changes don't persist**
- Check browser console for errors
- Verify `handleSaveStrategyConfig` is being called
- Check that `presetsConfig` state is updating
- Note: Backend persistence is optional and may not be implemented yet

**Issue: Type errors**
- Run `npm run build` to check for TypeScript errors
- Verify all imports are correct
- Check that types match between files

### Next Steps After Testing

1. If all tests pass: ✅ Ready for production or backend persistence
2. If issues found: Fix bugs and retest
3. If backend persistence needed: Implement in `handleSaveStrategyConfig`

