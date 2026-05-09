# Plan: Daily Theta Income Schedule in Options Forecast

## Context

The user is on the Portfolio page (`/portfolio`) viewing the **Options Forecast (CSPs + CCs)** section inside `ThetaBreakdownPanel`. Today the forecast only groups income positions (cash-secured puts + covered calls) by their **Friday expiration date** and shows the cumulative premium that lands at each weekly close. The user wants to see:

1. **A day-by-day breakdown** of how much theta income they earn each business day — not just what lands on Fridays
2. **Their account total adjusted day-by-day** so they can plan around the daily equity growth from theta decay
3. **Tighter row spacing** because some rows currently have too much padding

The existing `usePortfolioCalculations` hook already computes daily theta as `Σ |greeks.theta| * |quantity|` per option, and `OptionPosition` already carries the `expiration` (YYYY-MM-DD), `dte`, and per-option `greeks.theta`. All the data is in place — this is purely a UI / derived-state addition with no backend changes needed.

## Files to Modify

**Primary (only file requiring real edits):**
- [frontend/src/pages/portfolio/ThetaBreakdownPanel.tsx](frontend/src/pages/portfolio/ThetaBreakdownPanel.tsx) — add a daily-schedule view alongside the existing weekly view, plus padding tightening

**Read-only references (no edits needed):**
- [frontend/src/pages/portfolio/usePortfolioCalculations.ts](frontend/src/pages/portfolio/usePortfolioCalculations.ts) — pattern reference for daily-theta math (lines 42-43, 123, 125-144)
- [frontend/src/pages/portfolio/types.ts](frontend/src/pages/portfolio/types.ts) — `OptionPosition` shape (`greeks.theta`, `expiration`, `quantity`, `strategy`)
- [frontend/src/components/portfolio/PositionsTab.tsx#L884-L887](frontend/src/components/portfolio/PositionsTab.tsx#L884-L887) — call site, no changes (it already passes `options` and `totalEquity`)

## Implementation

### 1. Add view-mode toggle to the Options Forecast header

Inside `ThetaBreakdownPanel.tsx`, add a single piece of state next to the existing `isForecastExpanded`:

```ts
const [forecastView, setForecastView] = useState<'daily' | 'weekly'>('daily');
```

Render two compact pill buttons in the forecast header (next to the "CSPs + CCs" badge): **Daily** | **Weekly**. Default is `daily` because that's what the user is asking for; `weekly` preserves the existing detailed by-Friday view they already rely on. No data is lost — both views are one click apart.

### 2. Compute daily schedule with `useMemo`

Add a second `useMemo` next to the existing `optionsForecast` memo (around [ThetaBreakdownPanel.tsx:91-142](frontend/src/pages/portfolio/ThetaBreakdownPanel.tsx#L91-L142)):

```ts
const dailySchedule = useMemo(() => {
  // Reuse the same income-positions filter from optionsForecast
  const incomePositions = options.filter(opt => {
    const strategy = opt.strategy?.toUpperCase();
    if (strategy === 'CSP' || strategy === 'CC') return true;
    const qty = Number(opt.quantity || 0);
    if (qty < 0 && (opt.option_type?.toLowerCase() === 'put' || opt.option_type?.toLowerCase() === 'call')) return true;
    return false;
  });
  if (incomePositions.length === 0) return { days: [], totalIncome: 0 };

  // Parse each position's expiration to a Date once
  const parsed = incomePositions.map(p => {
    const [y, m, d] = (p.expiration || '').split('-').map(Number);
    const expDate = (y && m && d) ? new Date(y, m - 1, d) : null;
    if (expDate) expDate.setHours(0, 0, 0, 0);
    const dailyTheta = Math.abs(Number(p.greeks?.theta || 0)) * Math.abs(Number(p.quantity || 0));
    return { pos: p, expDate, dailyTheta };
  });

  // Furthest expiration defines the schedule horizon
  const maxExp = parsed.reduce<Date | null>(
    (max, x) => (x.expDate && (!max || x.expDate > max)) ? x.expDate : max, null);
  if (!maxExp) return { days: [], totalIncome: 0 };

  const today = new Date(); today.setHours(0, 0, 0, 0);
  const days: Array<{
    date: Date;
    isWeekend: boolean;
    isExpiration: boolean;       // any position expires today
    expiringCount: number;       // # contracts expiring today
    expiringPremium: number;     // premium from positions expiring today
    activeContracts: number;     // contracts still open at start of day
    dailyIncome: number;         // theta earned today (only on business days)
    cumulativeIncome: number;    // running total
    projectedEquity: number;     // baseEquity + cumulativeIncome
  }> = [];

  const baseEquity = Number(totalEquity || 0);
  let cumulative = 0;
  const cursor = new Date(today);
  while (cursor <= maxExp) {
    const isWeekend = cursor.getDay() === 0 || cursor.getDay() === 6;
    // Positions still active TODAY (expiration on or after today)
    const active = parsed.filter(x => x.expDate && x.expDate >= cursor);
    // Positions expiring TODAY
    const expiringToday = parsed.filter(x =>
      x.expDate && x.expDate.getTime() === cursor.getTime());

    // Theta only accrues on business days (Mon-Fri).
    // Weekend theta is bundled into Monday by market convention,
    // so we skip Sat/Sun and let the trader see the weekly pattern.
    const dailyIncome = isWeekend
      ? 0
      : active.reduce((sum, x) => sum + x.dailyTheta, 0);
    cumulative += dailyIncome;

    days.push({
      date: new Date(cursor),
      isWeekend,
      isExpiration: expiringToday.length > 0,
      expiringCount: expiringToday.reduce(
        (s, x) => s + Math.abs(Number(x.pos.quantity || 0)), 0),
      expiringPremium: expiringToday.reduce(
        (s, x) => s + Math.abs(Number(x.pos.current_value || 0)), 0),
      activeContracts: active.reduce(
        (s, x) => s + Math.abs(Number(x.pos.quantity || 0)), 0),
      dailyIncome,
      cumulativeIncome: cumulative,
      projectedEquity: baseEquity + cumulative,
    });
    cursor.setDate(cursor.getDate() + 1);
  }

  return { days, totalIncome: cumulative };
}, [options, totalEquity]);
```

**Math notes:**
- Uses the same `|theta| * |qty|` convention as the existing `dailyTheta` calc in [usePortfolioCalculations.ts:42-43](frontend/src/pages/portfolio/usePortfolioCalculations.ts#L42-L43) so totals stay consistent.
- Skips Sat/Sun (theta still accrues but markets are closed; bundling into Monday matches how brokerages display it).
- A position is counted as "active" on its expiration day itself (the last day theta decays is expiry day), then drops out the next day.
- Linear theta model — does not try to simulate gamma acceleration. This matches the rest of the panel's simplification.

### 3. Render the daily schedule table (when `forecastView === 'daily'`)

Replace the rendering block at [ThetaBreakdownPanel.tsx:322-484](frontend/src/pages/portfolio/ThetaBreakdownPanel.tsx#L322-L484) with a conditional:

- `forecastView === 'weekly'` → existing by-Friday groups (unchanged)
- `forecastView === 'daily'` → new compact daily table

Daily table columns (compact, mono font, right-aligned numbers):
| Date | Open Contracts | Daily Income | Cumulative | Projected Equity |
|------|----------------|--------------|------------|------------------|
| Mon Apr 7 (today) | 25 | +$X | +$X | $34,450 |
| Tue Apr 8 | 25 | +$X | +$X | $34,500 |
| ... | ... | ... | ... | ... |
| **Fri Apr 10** EXP 8 ($3,355) | 25 | +$X | +$3,355 | $34,964 |
| Mon Apr 13 | 17 | +$X | ... | ... |

Visual treatment:
- Friday rows where `isExpiration === true` get a faint emerald-tinted background plus a small "EXP N" pill showing how many contracts close that day
- "Today" row gets a subtle blue left-border accent
- Weekend rows are hidden by default (or rendered as a thin grey "—— weekend ——" separator with no theta)
- Each row uses `py-1 px-2` (much tighter than current `py-2`/`py-2.5`)
- Cumulative and Projected Equity columns use the same emerald color as the existing "PROJECTED EQUITY AFTER FRI APR 10" footer for visual continuity

### 4. Padding cleanup (addresses the "too much padding" complaint)

Tighten spacing throughout the panel without losing readability:

| Location | Current | New |
|---|---|---|
| Outer container ([line 145](frontend/src/pages/portfolio/ThetaBreakdownPanel.tsx#L145)) | `p-5` | `p-4` |
| Strategy cards ([line 172](frontend/src/pages/portfolio/ThetaBreakdownPanel.tsx#L172)) | `p-4` + `space-y-2` | `p-3` + `space-y-1.5` |
| Strategy grid gap ([line 165](frontend/src/pages/portfolio/ThetaBreakdownPanel.tsx#L165)) | `gap-3 mb-4` | `gap-2 mb-3` |
| Totals row tiles ([line 240-260](frontend/src/pages/portfolio/ThetaBreakdownPanel.tsx#L240-L260)) | `p-3` | `p-2.5` |
| Forecast group header button ([line 343](frontend/src/pages/portfolio/ThetaBreakdownPanel.tsx#L343)) | `px-4 py-2.5` | `px-3 py-2` |
| Position table rows ([lines 388-426](frontend/src/pages/portfolio/ThetaBreakdownPanel.tsx#L388-L426)) | `py-2 px-2` | `py-1.5 px-2` |
| Projected Equity footer ([line 462](frontend/src/pages/portfolio/ThetaBreakdownPanel.tsx#L462)) | `px-4 py-2` | `px-3 py-1.5` |
| Mini stat cards ([lines 290-318](frontend/src/pages/portfolio/ThetaBreakdownPanel.tsx#L290-L318)) | `p-2` | unchanged |

These are uniform `0.5`-step Tailwind reductions — no layout disruption, no font changes, just denser rows. Net effect: ~25-30% less vertical space for the same content.

## Why a toggle (not stacking both views)

- **Space**: Stacking both would *add* rows, the opposite of what the user asked for
- **No data loss**: One click to flip between the realistic daily view (theta-based) and the optimistic weekly view (full-premium-capture-at-expiration)
- **Default = daily**: Matches the user's explicit request; weekly stays one click away for users who already rely on it

## Two different forecast models (worth being clear about)

| View | Model | What it answers |
|---|---|---|
| **Weekly** (existing) | "Full premium capture if held to expiration" — assumes 100% of `current_value` lands on Friday | "What's my equity if everything expires worthless?" |
| **Daily** (new) | Linear theta decay — sums `Σ \|theta\| * \|qty\|` per business day across still-open positions | "How much do I earn from theta each day along the way?" |

These won't reconcile to the same number — daily totals will be slightly *lower* because linear theta underestimates the gamma-accelerated final days. That's expected and acceptable for a planning view. A small inline note ("based on theta decay, business days only") under the Daily table heading documents this.

## Verification

This is a frontend-only change to one file. No backend restart needed.

1. Frontend smoke test against the page that hosts this panel:
   ```
   python .claude/skills/playwright-testing/runner.py smoke http://localhost:5420/portfolio
   ```
   Expect `"status": "success"` and no console errors.

2. Manual visual QA:
   - Navigate to `/portfolio` → scroll to "Theta Decay by Strategy" panel
   - Confirm the toggle (Daily | Weekly) appears in the Options Forecast header and defaults to Daily
   - Daily view shows one row per weekday from today through the furthest expiration
   - Friday rows where contracts expire show the "EXP N" marker and emerald tint
   - The "Projected Equity" column on the final Friday row should approximately equal `totalEquity + sum(weekly group totalPremium)` from the weekly view (linear vs full-capture, so it'll be slightly lower)
   - Switching to Weekly shows the original by-Friday view unchanged
   - Compare row density before/after — confirm panel is visibly tighter

3. Type-check:
   ```
   docker exec ada-frontend pnpm tsc --noEmit
   ```

4. Edge cases to eyeball:
   - Account with zero income positions → no toggle, no daily section (existing `optionsForecast.groups.length > 0` guard already handles this)
   - All positions expire same day → daily table shows ~3-5 rows
   - Position with missing/invalid `greeks.theta` → contributes 0 to daily income (already handled by `Number(...|| 0)`)
   - Position with malformed `expiration` → silently dropped from schedule (the parsed `expDate` will be `null`)

## Out of scope (intentionally)

- No backend changes — all data needed already lives in `OptionPosition`
- No new hooks or files — single-file change keeps blast radius minimal
- No gamma/vol-acceleration modeling — linear theta is consistent with the rest of the panel
- No persistent user preference for the toggle default (could be added later via localStorage if requested)
