# Plan: Make Dollar P&L Prominent for Short Options

## Context

In the Portfolio Options tab and Options Forecast table, short option positions (CC/CSP) currently show **percentage captured** as the primary/bold value, with the premium amount as small secondary text. The user needs **dollar P&L** to be the most prominent number, with percentage as secondary context.

Long option positions already display correctly (dollar P&L bold, percentage secondary). Only short options need fixing.

## Changes

### 1. [OptionsTable.tsx:298-311](frontend/src/pages/portfolio/OptionsTable.tsx#L298-L311) - Main Options Tab

**Current**: Short options show `"+6% captured"` (bold) with `"$621 premium"` (small gray) below.

**Change to**: Show dollar P&L as primary bold value, captured % as secondary below.

```tsx
// Short option (CC/CSP): dollar P&L primary, % captured secondary
return (
  <div className="text-right">
    <div className={clsx("font-bold", (option.pl || 0) >= 0 ? 'text-emerald-400' : 'text-red-400')}>
      {m(formatCurrency(option.pl))}
    </div>
    {!hideAmounts && <div className={clsx("text-xs", pctCaptured >= 0 ? 'text-emerald-400/70' : 'text-amber-400/70')}>
      {m(`${pctCaptured >= 0 ? '+' : ''}${Number(pctCaptured).toFixed(0)}% captured`)}
    </div>}
  </div>
);
```

### 2. [ThetaBreakdownPanel.tsx:410-418](frontend/src/pages/portfolio/ThetaBreakdownPanel.tsx#L410-L418) - Forecast Table P/L Column

**Current**: Shows only `"+6%"` for short options.

**Change to**: Show dollar P&L as primary, with captured % in parentheses.

```tsx
if (pctCap !== null) {
  return (
    <td className={clsx("py-2 px-2 text-right font-mono font-medium",
      Number(pos.pl || 0) >= 0 ? 'text-emerald-400' : 'text-red-400')}>
      <div>{m(formatCurrency(Number(pos.pl || 0)))}</div>
      <div className={clsx("text-[10px]", pctCap >= 0 ? 'text-emerald-400/60' : 'text-amber-400/60')}>
        {m(`${pctCap >= 0 ? '+' : ''}${Number(pctCap).toFixed(0)}%`)}
      </div>
    </td>
  );
}
```

## Files Modified

- [OptionsTable.tsx](frontend/src/pages/portfolio/OptionsTable.tsx) - Lines 298-311
- [ThetaBreakdownPanel.tsx](frontend/src/pages/portfolio/ThetaBreakdownPanel.tsx) - Lines 410-418

## Data Availability

The `option.pl` field (dollar P&L) is already available on `OptionPosition` type ([types.ts:32](frontend/src/pages/portfolio/types.ts#L32)) and already used by long options and the forecast Total row. No backend changes needed.

## Verification

1. Navigate to `http://localhost:5420/portfolio` > Options tab
2. Confirm short option positions (CC/CSP) show dollar amount bold, captured % secondary
3. Scroll to Options Forecast section, expand an expiration group
4. Confirm P/L column shows dollar amounts with small % below
5. Verify Total row still sums correctly (already uses `option.pl`)
