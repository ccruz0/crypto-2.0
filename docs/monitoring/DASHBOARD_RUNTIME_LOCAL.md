# Dashboard Runtime Local Verification

## Date: 2025-01-12

## Current Runtime Error (Production)

### Error Message
```
ReferenceError: Cannot access 'r$' before initialization
    at https://dashboard.hilovivo.com/_next/static/chunks/0ab76a55c333d2a2.js:117:5060
    at Array.filter (<anonymous>)
    at https://dashboard.hilovivo.com/_next/static/chunks/0ab76a55c333d2a2.js:117:5042
    at Object.ut [as useMemo] (https://dashboard.hilovivo.com/_next/static/chunks/67109db2c1cc3c5b.js:19:70421)
    at r.useMemo (https://dashboard.hilovivo.com/_next/static/chunks/b3586c5fd8b35d78.js:1:9856)
    at F (https://dashboard.hilovivo.com/_next/static/chunks/0ab76a55c333d2a2.js:117:4814)
```

### When It Happens
- Dashboard root page loads initially
- Error occurs during React render/hydration
- Happens when MonitoringPanel component tries to render

### Component Involved
- `frontend/src/app/components/MonitoringPanel.tsx`
- Function `F` in compiled code (likely the main component render)

---

## Root Cause Analysis

### Issue: workflows.map() Still Present
**File**: `frontend/src/app/components/MonitoringPanel.tsx`
**Line**: ~681

**Problem**: Even though we removed IIFEs for other arrays, we're still using `.map()` directly on `workflows`:

```typescript
{workflows.map((workflow) => {
  if (!workflow || !workflow.id) return null;
  return (
    <SimpleWorkflowItem
      key={String(workflow.id)}
      workflow={workflow}
      onRun={handleRunWorkflow}
    />
  );
})}
```

**Why it breaks**: Next.js's compiler (Turbopack) is trying to optimize this `.map()` call by wrapping it in a `useMemo` hook. When it does this, it creates variable references that can be accessed before initialization, causing the `ReferenceError`.

**Solution**: Replace `.map()` with a helper function that returns an array of React nodes, just like we did for errors, alerts, throttle entries, and telegram messages.

---

## Fix Required

Replace `workflows.map()` with a helper function `renderWorkflowRows()` that uses a for loop instead of `.map()`.






