# Options Forecast Enhancement: Add Opportunity Cost Summary Row

## Context

The user is requesting an enhancement to the Options Forecast feature (CSPs + CCs) in the ADA platform. Currently, the forecast shows premiums collected, P/L, and projected equity by expiration date. However, it doesn't provide a clear summary of the total opportunity cost when covered call positions result in shares being called away below current market prices.

**Current Problem**: While users can see individual position P/L, they lack visibility into:
1. Total premiums they will receive across all positions
2. Total opportunity cost from shares being called away below current market prices  
3. Net effect (premiums received vs. upside foregone)

**Example from Screenshot**:
- AXTI: Trading at $92.46, CC strike at $71.00 → if called away, loses $21.46/share upside
- LQDA: Trading at $38.22, CC strike at $38.00 → minimal opportunity cost
- Need aggregate view showing total premiums ($15,419.00) vs total opportunity costs

## Implementation Plan

### Phase 1: Backend Enhancement

**File**: `c:\code\ADA\backend\services\positions_dashboard_service.py` (or related portfolio service)

Add opportunity cost calculation for covered call positions:

```typescript
interface OpportunityCostSummary {
  total_premiums_collected: number;
  total_opportunity_cost: number;  // Sum of (underlying_price - strike) * quantity * 100 for ITM CCs
  net_effect: number;              // total_premiums_collected - total_opportunity_cost
  positions_called_away: number;   // Count of ITM CC positions
  shares_called_away: number;      // Total shares that will be called away
}
```

**Calculation Logic**:
For each covered call position where `underlying_price > strike`:
- `opportunity_cost = (underlying_price - strike) * quantity * 100`
- Sum across all ITM covered calls

### Phase 2: Frontend Data Types

**File**: `c:\code\ADA\frontend\src\pages\portfolio\types.ts`

Add interface for the summary data:
```typescript
export interface OpportunityCostSummary {
  totalPremiumsCollected: number;
  totalOpportunityCost: number;
  netEffect: number;
  positionsCalledAway: number;
  sharesCalledAway: number;
}
```

### Phase 3: Frontend Component Enhancement

**File**: `c:\code\ADA\frontend\src\pages\portfolio\ThetaBreakdownPanel.tsx`

**Location**: After line 637 (after all expiration groups), before the daily view section

**Enhancement**:
1. Calculate opportunity cost summary from existing `options` data
2. Add new summary row section showing:
   - Total Premiums Collected (already calculated as `totalPremium`)
   - Total Opportunity Cost (new calculation)
   - Net Effect (premiums - opportunity cost)
   - Number of positions/shares that will be called away

**Calculation Logic in Frontend**:
```typescript
const opportunityCostSummary = useMemo(() => {
  const ccPositions = options.filter(opt => 
    opt.strategy?.toUpperCase() === 'CC' && 
    (opt.underlying_price || 0) > (opt.strike || 0)
  );
  
  const totalOpportunityCost = ccPositions.reduce((sum, pos) => {
    const underlyingPrice = pos.underlying_price || 0;
    const strike = pos.strike || 0;
    const quantity = Math.abs(pos.quantity || 0);
    return sum + ((underlyingPrice - strike) * quantity * 100);
  }, 0);
  
  const totalPremiumsCollected = incomeGroups.totalPremium;
  
  return {
    totalPremiumsCollected,
    totalOpportunityCost,
    netEffect: totalPremiumsCollected - totalOpportunityCost,
    positionsCalledAway: ccPositions.length,
    sharesCalledAway: ccPositions.reduce((sum, pos) => sum + Math.abs(pos.quantity || 0) * 100, 0)
  };
}, [options, incomeGroups.totalPremium]);
```

**UI Component**:
Add summary section after existing forecast groups:
```tsx
{/* Opportunity Cost Summary */}
{opportunityCostSummary.positionsCalledAway > 0 && (
  <div className="mt-4 bg-amber-500/5 rounded-lg border border-amber-500/20 p-4">
    <div className="flex items-center justify-between mb-2">
      <h4 className="text-sm font-semibold text-amber-400">
        Call Away Impact Summary
      </h4>
      <span className="text-xs text-amber-500/70">
        {opportunityCostSummary.positionsCalledAway} positions, {formatNumber(opportunityCostSummary.sharesCalledAway)} shares
      </span>
    </div>
    
    <div className="grid grid-cols-3 gap-4">
      <div className="text-center">
        <div className="text-xs text-slate-500">Premiums Collected</div>
        <div className="text-lg font-bold text-emerald-400 font-mono">
          +{m(formatCurrency(opportunityCostSummary.totalPremiumsCollected))}
        </div>
      </div>
      
      <div className="text-center">
        <div className="text-xs text-slate-500">Upside Foregone</div>
        <div className="text-lg font-bold text-red-400 font-mono">
          -{m(formatCurrency(opportunityCostSummary.totalOpportunityCost))}
        </div>
      </div>
      
      <div className="text-center">
        <div className="text-xs text-slate-500">Net Effect</div>
        <div className={clsx("text-lg font-bold font-mono", 
          opportunityCostSummary.netEffect >= 0 ? 'text-emerald-400' : 'text-red-400')}>
          {opportunityCostSummary.netEffect >= 0 ? '+' : ''}
          {m(formatCurrency(opportunityCostSummary.netEffect))}
        </div>
      </div>
    </div>
    
    <div className="mt-2 text-xs text-amber-500/70 text-center">
      Based on current market prices vs strike prices for ITM covered calls
    </div>
  </div>
)}
```

### Phase 4: Verification

**Frontend Testing**:
1. Navigate to Portfolio → Options Forecast
2. Verify summary row appears when covered calls are ITM (in-the-money)
3. Verify calculations match manual calculations:
   - For AXTI: (92.46 - 71.00) × 5 × 100 = $10,730 opportunity cost
   - For LQDA: (38.22 - 38.00) × 3 × 100 = $66 opportunity cost
   - Total opportunity cost = $10,796
   - Net effect = $15,419 premiums - $10,796 opportunity cost = +$4,623

**Edge Cases to Test**:
- No ITM covered calls (summary should not appear)
- Mix of ITM and OTM covered calls (only ITM should count)
- Negative quantities (ensure Math.abs is used)

**Browser Test Command**:
```bash
python .claude/skills/playwright-testing/runner.py smoke http://localhost:5420/portfolio
```

### Files to Modify

| File | Purpose | Lines Est. |
|------|---------|-----------|
| `frontend/src/pages/portfolio/types.ts` | Add OpportunityCostSummary interface | +10 |
| `frontend/src/pages/portfolio/ThetaBreakdownPanel.tsx` | Add calculation logic and UI component | +80 |

### Success Criteria

1. ✅ Summary row appears below expiration groups when ITM covered calls exist
2. ✅ Shows total premiums collected vs total opportunity cost vs net effect
3. ✅ Calculations are mathematically correct based on current prices vs strikes
4. ✅ UI styling matches existing forecast aesthetic (amber theme for warnings)
5. ✅ Summary does not appear when no ITM covered calls exist
6. ✅ Browser testing passes without JavaScript errors

### Design Notes

- Uses amber color theme to indicate this is an "impact analysis" rather than pure profit
- Only shows for ITM covered calls (where opportunity cost exists)
- Includes position/share count for additional context
- Calculation happens client-side using existing option position data
- No backend API changes required - uses existing data structure

This enhancement provides users with clear visibility into the trade-off between premium income and potential upside forgone, enabling better strategic planning for their covered call positions.