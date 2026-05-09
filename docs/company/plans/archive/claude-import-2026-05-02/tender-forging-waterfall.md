# Plan: Deduplicate CSP Plays to Best-Per-Symbol

## Context

The "Cash-Secured Put Plays" section in Income Opportunities shows 10 results, all for the same stock (PLTU) with different strike/expiry combos. This happens because the backend endpoint (`/api/portfolio/csp-opportunities`) scores all PUT options globally and returns the top N — if one stock dominates the scoring, it fills every slot.

The fix: after scoring, pick only the **best CSP per symbol**, then return the top N across unique symbols.

## Changes

### 1. Backend: [portfolio.py:4927-4950](backend/routers/portfolio.py#L4927-L4950)

After scoring all opportunities (line 4946), add deduplication logic before the final sort:

```python
# Deduplicate: keep only the best-scoring opportunity per symbol
best_by_symbol: dict[str, dict] = {}
for opp in opportunities:
    sym = opp["symbol"]
    if sym not in best_by_symbol or opp["score"] > best_by_symbol[sym]["score"]:
        best_by_symbol[sym] = opp
opportunities = list(best_by_symbol.values())

# Sort by score descending, take top N
opportunities.sort(key=lambda x: x["score"], reverse=True)
opportunities = opportunities[:limit]
```

This replaces the current lines 4948-4950 which just sort and slice without dedup.

**No other files need changes** — the frontend already renders whatever the API returns.

## Verification

1. `docker restart ada-backend` + check logs for startup errors
2. `curl http://localhost:8006/api/portfolio/csp-opportunities?limit=10` — verify each symbol appears at most once
3. Check the Income Opportunities panel on the Portfolio page at `http://localhost:5420/portfolio`
