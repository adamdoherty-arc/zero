# Plan: Add Current Stock Price Column to Options Forecast

## Context
The Options Forecast table on the Portfolio positions page (weekly view) shows SYMBOL, STRIKE, QTY, COLLATERAL, PREMIUM, P/L — but doesn't show the current stock price. This makes it hard to see at a glance how close the underlying is to the strike price. The data field `underlying_price` is already available on every `OptionPosition` object — just needs a new column.

## File to Modify
- [ThetaBreakdownPanel.tsx](frontend/src/pages/portfolio/ThetaBreakdownPanel.tsx)

## Changes

### 1. Add "Price" column header (line 488, between Symbol and Strike)
```tsx
<th className="text-right py-1.5 px-2">Price</th>
```

### 2. Add price cell in the position row (after the Symbol cell, before Strike cell, ~line 509)
```tsx
<td className="py-1.5 px-2 text-right text-slate-300 font-mono">
  ${Number(pos.underlying_price || 0).toFixed(2)}
</td>
```

### 3. Add empty cell in the footer totals row (line 553, to maintain column alignment)
```tsx
<td className="py-1.5 px-2" />
```

## No Other Changes Needed
- `OptionPosition` type already has `underlying_price?: number` field
- Backend already populates `underlying_price` from Robinhood sync
- Daily view shows a different format (date-based schedule, no per-position rows) — no change needed

## Verification
- Restart backend is NOT needed (frontend-only change)
- Check the Portfolio page → Positions tab → Options Forecast → Weekly view
- Confirm the Price column appears between Symbol and Strike
- Confirm values match the underlying stock prices
