# Fix: CoveredCallsTab useState Crash + Backend Unavailable

## Context

The `/scanner` page (UnifiedOptionsHub) shows two separate errors:

1. **Red banner**: "is currently unavailable" / "failures" — backend health check is failing
2. **CoveredCallsTab crash**: `TypeError: Cannot read properties of null (reading 'useState')` — React hooks error when the Covered Calls tab renders

## Root Cause Analysis

### Error 1: Backend Unavailable (red banner)
The top banner indicates the backend health endpoint is returning errors. This is a separate issue from the component crash — likely the backend container needs a restart or has a startup error.

### Error 2: useState is null (CoveredCallsTab)
The stack trace shows:
```
TypeError: Cannot read properties of null (reading 'useState')
    at exports.useState (chunk-PQOTZ4DQ.js)
    at CoveredCallsTab (CoveredCallsTab.tsx:12:51)
```

**The code itself is correct.** I verified:
- `CoveredCallsTab.tsx` properly imports `{ useState }` from `'react'` (line 9)
- Hooks are called at the top level of the component function (not conditionally)
- Other lazy-loaded tabs (`VolSurfaceTab`, `ContrarianTab`, `WheelTab`) use the same pattern and work fine
- No circular dependencies in the import chain
- The barrel file (`scanner/index.ts`) does NOT eagerly export CoveredCallsTab
- All transitive imports (`useMarginCC`, `formatters`, `MarginCCProfitability`, `portfolio/types`) are clean

**This is a Vite dependency pre-bundle cache corruption.** When Vite pre-bundles React into `chunk-PQOTZ4DQ.js`, if the cache gets stale (from HMR, branch switching, or file changes), the chunk can return null for React's exports. The `exports.useState` call then fails because `exports` (the React module) is null.

Evidence: The issue is **isolated to CoveredCallsTab** while identical patterns work in other tabs, which rules out a code bug and points to a Vite module resolution/caching issue.

## Fix

### Step 1: Clear Vite dependency cache and restart frontend
```bash
docker exec ada-frontend rm -rf node_modules/.vite .vite
docker restart ada-frontend
```

### Step 2: Check backend health
```bash
docker logs ada-backend --tail 30
docker restart ada-backend  # if needed
```

### Step 3: Verify both are working
```bash
# Backend health
curl -s http://localhost:8006/api/health | head -c 200

# Frontend loads
curl -s -o /dev/null -w "%{http_code}" http://localhost:5420/scanner
```

## Files Involved (no code changes needed)
- [CoveredCallsTab.tsx](frontend/src/components/scanner/CoveredCallsTab.tsx) — code is correct
- [UnifiedOptionsHub.tsx](frontend/src/pages/UnifiedOptionsHub.tsx) — lazy loading is correct
- [useMarginCC.ts](frontend/src/hooks/useMarginCC.ts) — hooks are correct

## Verification
After clearing the Vite cache and restarting:
1. Navigate to `localhost:5420/scanner`
2. Click the "Covered Calls" tab
3. The component should render without the useState error
4. The red banner should clear once the backend is healthy
