# Fix: Premium-Aware Options P&L Across Portfolio

## Context

The system reports options P&L as pure mark-to-market (MTM), which is misleading for premium sellers. When a covered call goes ITM (stock rises past strike), the system shows a "loss" because the option costs more to buy back — but the user collected premium upfront and profits from assignment. This affects the advisor briefing (already fixed), and several frontend components in the Portfolio Hub.

**What's already done** (trade_advisor_service.py — implemented in prior step):
- SQL expanded to pull `position_type`, `total_premium`, `current_value`
- Summary splits short vs long options with premium-aware metrics
- Per-position formatting shows "Premium: $X | Y% Captured" for CC/CSP
- LLM prompt instructs to never call profitable premium sells "losses"

**What still needs alignment**: The frontend OptionsTable and related components show raw MTM P&L without premium context, creating the same misleading "red = loss" display for short options.

## Audit Results

### Already Premium-Aware (no changes needed)
- `StocksWithCCTable.tsx` — shows CC income, pct_captured, combined stock+CC profit
- `IncomeOpportunityPanel.tsx` — shows premium in opportunity context
- `WheelPnLPanel.tsx` — tracks premium_collected per wheel cycle
- `AdvisorBriefingPanel.tsx` — renders LLM briefing (now fixed via prompt)

### Needs Update (shows raw MTM P&L for short options)
| Component | File | Issue | Priority |
|-----------|------|-------|----------|
| **OptionsTable** | `frontend/src/pages/portfolio/OptionsTable.tsx:299-304` | Main options table — red P&L for CCs with no premium context | **HIGH** |
| **ThetaBreakdownPanel** | `frontend/src/pages/portfolio/ThetaBreakdownPanel.tsx:410-412` | Per-position P&L in theta view — red for short options | **MEDIUM** |

### Lower priority (modals/selectors, not primary view)
- `PositionModals.tsx:51-52` — comparison modal shows raw P/L
- `RollSimulatorTab.tsx:330-334` — shows P/L without option type context
- `PositionSelector.tsx:147-188` — inline P/L in picker
- `BatchOperationModal.tsx:61,198-200` — sums P/L without grouping

These lower-priority items are secondary modals and can be done later if desired.

## Files to Modify

### 1. OptionsTable.tsx (HIGH — main user-facing options table)

**File**: [OptionsTable.tsx](frontend/src/pages/portfolio/OptionsTable.tsx)

**Current** (lines 297-304): Shows raw `option.pl` with red/green color:
```tsx
<div className={clsx("font-bold", (option.pl || 0) >= 0 ? 'text-emerald-400' : 'text-red-400')}>
  {m(formatCurrency(option.pl))}
</div>
```

**Change**: For CC/CSP positions, replace raw P&L display with premium-aware view:
- Show `pct_captured` as the primary metric (computed from `total_premium` and `current_value`)
- Show premium collected as secondary info
- Color based on pct_captured (green when > 0, meaning theta is working; red only when negative)
- Keep raw P&L as-is for long options

```tsx
// For short options (CC/CSP): show % captured + premium
const isShort = option.strategy?.toUpperCase() === 'CC' || option.strategy?.toUpperCase() === 'CSP';
const pctCaptured = isShort && option.total_premium
  ? ((option.total_premium - option.current_value) / option.total_premium) * 100
  : null;

{isShort && pctCaptured !== null ? (
  <div className="text-right">
    <div className={clsx("font-bold", pctCaptured >= 0 ? 'text-emerald-400' : 'text-amber-400')}>
      {m(`${pctCaptured >= 0 ? '+' : ''}${Number(pctCaptured).toFixed(0)}% captured`)}
    </div>
    {!hideAmounts && <div className="text-xs text-slate-400">
      {m(`$${formatNumber(option.total_premium, 0)} premium`)}
    </div>}
  </div>
) : (
  // existing P&L display for long options (unchanged)
)}
```

**Key design decisions**:
- Use amber (not red) for negative capture on short options — a CC going ITM is a risk signal, not a catastrophic loss
- Show "% captured" as primary metric since that's what premium sellers track
- Show premium collected as context
- `pctCaptured` is computed client-side from existing `total_premium` and `current_value` fields (no backend change needed)

### 2. ThetaBreakdownPanel.tsx (MEDIUM — theta detail view)

**File**: [ThetaBreakdownPanel.tsx](frontend/src/pages/portfolio/ThetaBreakdownPanel.tsx)

**Current** (lines 410-412): Shows raw `pos.pl` with red/green color.

**Change**: Same pattern as OptionsTable — for short options, show pct_captured instead of raw P&L:
```tsx
const isShort = pos.strategy?.toUpperCase() === 'CC' || pos.strategy?.toUpperCase() === 'CSP';
const pctCap = isShort && pos.total_premium
  ? ((pos.total_premium - pos.current_value) / pos.total_premium) * 100
  : null;
```

For the group total (line 420): Keep summing `pl` since the theta breakdown is about decay tracking, but add a note if all positions in the group are short.

### 3. OptionPosition type (OPTIONAL — add helper)

**File**: [types.ts](frontend/src/pages/portfolio/types.ts)

No type changes needed — `total_premium`, `current_value`, and `strategy` are already on `OptionPosition`.

Optionally add a utility function in the same file or a shared utils:
```tsx
export function getOptionPctCaptured(option: OptionPosition): number | null {
  const isShort = option.strategy?.toUpperCase() === 'CC' || option.strategy?.toUpperCase() === 'CSP';
  if (!isShort || !option.total_premium) return null;
  return ((option.total_premium - option.current_value) / option.total_premium) * 100;
}
```

## What NOT to Change (for now)
- Backend P&L calculation in `portfolio_service.py` (correct for MTM)
- Database schema (all needed columns already exist)
- `positions_sync_service.py` summary cache (functional, not user-facing text)
- WebSocket portfolio stream (consumes same underlying data)
- Lower-priority modals (PositionModals, BatchOperationModal, etc.) — can be aligned later
- `StocksWithCCTable` — already premium-aware

## Verification
1. No backend changes needed — `docker restart` not required
2. Frontend hot-reloads automatically in Docker
3. Navigate to Portfolio Hub → Options tab → verify:
   - CC/CSP positions show "X% captured" + premium amount (not raw red P&L)
   - Long options still show standard P&L with red/green
4. Navigate to Portfolio Hub → Theta Breakdown → verify same pattern
5. Run smoke test: `frontend/src/pages/__tests__/all-pages-smoke.test.tsx`
