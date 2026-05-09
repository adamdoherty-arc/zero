# Plan: Add TradingView Chart Link to AIPickCard

## Context
The Premium Scanner page (`/scanner`) shows AI Top Picks cards via the `AIPickCard` component. Each card displays a stock symbol that links to the internal stock detail page, but has no TradingView chart link. The user wants every card to include a TradingView chart link for quick access to charts.

## Change

**File**: [AIPickCard.tsx](frontend/src/components/AIPickCard.tsx)

Add a TradingView chart icon link next to the existing symbol link in the card header (around line 374). This matches the established pattern used in 20+ other components across the codebase (SignalCard, PositionsTable, EarningsEventCard, etc.).

### Current header structure (lines 367-383):
```
Symbol (link to /stocks/detail/:symbol) + ExternalLink icon
$strike | expiration | DTE
```

### After change:
```
Symbol (link to /stocks/detail/:symbol) + ExternalLink icon + TradingView chart icon
$strike | expiration | DTE
```

### Implementation:
Add a TradingView anchor tag after the existing `</Link>` close tag (after line 379), before the `<p>` tag on line 380:

```tsx
<a
  href={`https://www.tradingview.com/chart/?symbol=${pick.symbol}`}
  target="_blank"
  rel="noopener noreferrer"
  onClick={(e) => e.stopPropagation()}
  className="text-slate-500 hover:text-blue-400 transition-colors"
  title="Open TradingView chart"
>
  <BarChart3 className="w-4 h-4" />
</a>
```

- Uses `BarChart3` icon (already imported on line 23) - a chart icon that visually communicates "chart"
- Uses `/chart/?symbol=` URL pattern (consistent with 15+ other components)
- Minimal footprint - just an icon next to the symbol, not a full button
- `stopPropagation` prevents triggering the card's expand/collapse

No new imports needed - `BarChart3` and `ExternalLink` are already imported.

## Verification
1. Rebuild frontend: `docker restart ada-frontend`
2. Navigate to `localhost:5420/scanner`
3. Verify each AI Top Picks card shows a chart icon next to the symbol
4. Click the icon - should open TradingView chart in a new tab
5. Verify clicking the icon doesn't expand/collapse the card
