# Refactoring Progress: page.tsx

## Completed ✅

### 1. Logging Utility (`frontend/src/utils/logger.ts`)
- Created centralized logging system
- Replaces console.log/warn/error/debug
- Supports log levels (debug, info, warn, error)
- Includes error suppression for handled errors
- Environment-aware (production vs development)

### 2. Formatting Utilities (`frontend/src/utils/formatting.ts`)
- `addThousandSeparators()` - Number formatting
- `formatNumber()` - Adaptive decimal formatting based on value magnitude
- `formatPLSummaryNumber()` - Fixed decimal for P/L cards
- `formatTimestamp()` - Timestamp formatting with timezone
- `formatDateTime()` - Date/time formatting
- `formatTime()` - Time-only formatting
- `normalizeSymbolKey()` - Symbol key normalization

### 3. Order Transformations (`frontend/src/utils/orderTransformations.ts`)
- `transformOrdersToPositions()` - Converts UnifiedOpenOrder[] to OpenPosition[]
- Handles TP/SL order grouping
- Portfolio asset integration

### 4. Type Definitions (`frontend/src/types/dashboard.ts`)
- `Tab` type
- `Preset` and `RiskMode` types
- `StrategyRules` interface
- `PresetConfig` type
- `ExtendedOpenOrder` interface with proper type guards
- Type guard functions: `hasTriggerType()`, `getTriggerType()`, `getRawOrder()`, `isTriggerOrder()`
- `StrategyDecisionValue` type
- `getReasonPrefix()` helper

### 5. Component Structure Started
- Created `PortfolioTab.tsx` component structure (placeholder)

## In Progress 🔄

### 6. Custom Hooks (To Be Created)
- `usePortfolio` - Portfolio state management
- `useWatchlist` - Watchlist state management
- `useSignals` - Trading signals state
- `useOrders` - Orders state management
- `useTradingConfig` - Trading configuration state

### 7. Tab Components (To Be Created)
- `WatchlistTab.tsx`
- `SignalsTab.tsx`
- `OrdersTab.tsx`
- `ExpectedTakeProfitTab.tsx`
- `ExecutedOrdersTab.tsx`
- `VersionHistoryTab.tsx`
- `MonitoringTab.tsx`

### 8. Main Page Refactoring (In Progress)
- ✅ Updated `page.tsx` imports to use new utilities
- ✅ Removed duplicate function definitions (formatNumber, formatPLSummaryNumber, addThousandSeparators, normalizeSymbolKey, formatTimestamp, formatDateTime, formatTime)
- ✅ Removed duplicate type definitions (ExtendedOpenOrder, Tab, Preset, RiskMode, StrategyRules, ApiError, Loan)
- ✅ Removed duplicate transformOrdersToPositions function
- ✅ Replaced all `logHandledError()` calls with `logger.logHandledError()` (26 instances)
- 🔄 Replace `console.log/warn/error` with `logger` (324 instances - in progress)
- ⏳ Remove `as any` type assertions (10 instances found)
- ⏳ Fix exhaustive-deps warnings

## Next Steps

1. **Update page.tsx imports** - Replace inline functions with utility imports
2. **Replace console statements** - Use logger utility throughout
3. **Fix type safety** - Remove all `as any` assertions using proper type guards
4. **Extract hooks** - Create custom hooks for state management
5. **Create tab components** - Migrate tab JSX to separate components
6. **Update main component** - Simplify DashboardPageContent to use new structure

## Files Created

```
frontend/src/
├── utils/
│   ├── logger.ts ✅
│   ├── formatting.ts ✅
│   └── orderTransformations.ts ✅
├── types/
│   └── dashboard.ts ✅
└── app/
    └── components/
        └── tabs/
            └── PortfolioTab.tsx ✅ (structure created)
```

## Migration Strategy

Given the file size (12,074 lines), the refactoring should be done incrementally:

1. **Phase 1**: Replace utilities (low risk, high impact)
   - Import and use logger, formatting, orderTransformations
   - Remove duplicate function definitions

2. **Phase 2**: Fix type safety (medium risk, high impact)
   - Replace `as any` with proper type guards
   - Use ExtendedOpenOrder type guards

3. **Phase 3**: Extract hooks (medium risk, medium impact)
   - Create custom hooks for major state management
   - Test each hook independently

4. **Phase 4**: Extract components (higher risk, high impact)
   - Create tab components one at a time
   - Migrate JSX incrementally
   - Test after each component extraction

## Notes

- The file is too large to refactor in one pass
- Incremental approach is safer and more testable
- Each phase should be tested before moving to the next
- Type safety improvements should be prioritized



