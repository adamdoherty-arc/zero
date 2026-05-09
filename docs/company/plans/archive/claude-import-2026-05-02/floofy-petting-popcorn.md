# Fix: Portfolio "Scan Positions" Always Fails

## Context

The "Scan Positions" button in the Stocks & CCs section of the Portfolio page always fails with a 500/504 error. The root cause is a **90-second global request timeout middleware** in `backend/main.py:2073` that kills the request before the scan completes. The scan runs 2 scanners (Overkill + Contrarian) in parallel, each fetching 1-year of daily bars from Alpaca for all 8 held positions (16 Alpaca API calls total through semaphores of 3), then scoring, persisting, and generating alerts. This easily exceeds 90 seconds, especially after hours.

Additionally, the endpoint has **no top-level error handling**, so any pre-scan failure (DB connection, service initialization) produces a raw 500 with no useful error message.

## Changes

### 1. Add scan-positions to timeout exemption list
**File**: `backend/main.py:2087-2100`

Add `"/api/portfolio/scan-positions"` to the `exempt_paths` list in the `request_timeout_middleware`. This endpoint runs 2 scanners that each fetch 1-year bars from Alpaca for ~8 symbols — it legitimately needs 2-3 minutes.

### 2. Add top-level error handling to the endpoint
**File**: `backend/routers/portfolio_intelligence.py:373-465`

Wrap the `scan_positions` function body in a try/except to catch any unhandled exceptions (DB connection failures, service initialization errors, etc.) and return a proper error response instead of a raw 500.

### 3. Add internal timeout with graceful error
**File**: `backend/routers/portfolio_intelligence.py:373-465`

Add an `asyncio.wait_for` around the scanner gather with a 180-second timeout. If it hits the timeout, return a partial response with an error message rather than crashing. This provides a safety net even though the global timeout is now exempt.

## Files to Modify

| File | Change |
|------|--------|
| `backend/main.py` (~line 2098) | Add `"/api/portfolio/scan-positions"` to `exempt_paths` |
| `backend/routers/portfolio_intelligence.py` (~line 373) | Add try/except + internal timeout |

## Verification

1. `docker restart ada-backend` after changes
2. `docker logs ada-backend --tail 20` to confirm clean startup
3. `curl -s -X POST http://localhost:8006/api/portfolio/scan-positions -H "Content-Type: application/json" -d '{}' --max-time 300` — should return JSON with `"status": "complete"` (or a graceful error if Alpaca is slow), not a timeout/500
4. Click "Scan Positions" button on the Portfolio page — should no longer show "Scan failed"
