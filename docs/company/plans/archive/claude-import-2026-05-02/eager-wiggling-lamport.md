# Plan: Frontend Polish Pass (FE-07)

## Context

After completing the ProjectDetail overhaul (FE-06), a full frontend audit revealed several consistency issues, one missing consolidation, and reusable patterns that are hand-rolled differently in each page. The codebase is ~9/10 quality but these fixes bring it to a consistent, polished standard.

**No broken functionality was found** (the FE-06 dependency bug was the only real one). This sprint is about visual polish, consistency, and one consolidation.

---

## Issue 1: Ideas Page Not in ProjectDetail Tabs

**Problem**: The sidebar shows Overview, Plans, Sprints, Tasks, Ideas under each project. All except Ideas are available as tabs on the ProjectDetail Overview page. Users clicking the "Overview" page have no way to discover or access Ideas without the sidebar.

**Fix**: Add an "Ideas" tab to ProjectDetail.

**Files**:
- [ProjectDetail.tsx](frontend/src/pages/ProjectDetail.tsx) — Add `ideas` to Tab type, add tab button, add `useIdeas` hook import, render an `IdeasTab` component
- **NEW** `frontend/src/components/project/IdeasTab.tsx` — Lightweight ideas list (title, category badge, status dot, priority) with "Create Idea" button that links to the full Ideas page at `/projects/{id}/ideas`. NOT a full duplicate — just a preview list like the sprints/tasks tabs.

**Data**: Use existing `useIdeas(projectId)` hook from [useIdeas.ts](frontend/src/hooks/useIdeas.ts). Also use `useIdeaStats(projectId)` for the tab count badge.

---

## Issue 2: Reusable StatCard Component

**Problem**: Stat cards (icon + label + big number + subtitle) are hand-rolled in 3+ pages:
- [Dashboard.tsx:97-175](frontend/src/pages/Dashboard.tsx#L97-L175) — 4 cards, ~80 LOC
- [ProjectDetail.tsx:172-208](frontend/src/pages/ProjectDetail.tsx#L172-L208) — 5 cards, ~35 LOC
- [LearningDashboard.tsx](frontend/src/pages/LearningDashboard.tsx) — Has a local `StatCard` function

Each uses slightly different structure (some wrap in Link, some have onClick, some have trend icons).

**Fix**: Create shared `StatCard` component, use it in Dashboard, ProjectDetail, and LearningDashboard.

**NEW** `frontend/src/components/ui/StatCard.tsx`:
```tsx
interface StatCardProps {
  icon?: LucideIcon
  label: string
  value: React.ReactNode
  subtitle?: string
  color?: string           // e.g., "text-matrix-green", "text-blue-400"
  onClick?: () => void
  href?: string            // wraps in Link if provided
  active?: boolean         // ring-2 highlight
  activeColor?: string     // ring color class
  trend?: React.ReactNode  // optional trend indicator
  className?: string
}
```

**Files to update**:
- [Dashboard.tsx](frontend/src/pages/Dashboard.tsx) — Replace 4 hand-rolled stat cards with `<StatCard>` (~60 LOC saved)
- [ProjectDetail.tsx](frontend/src/pages/ProjectDetail.tsx) — Replace 5 stat cards (~25 LOC saved)
- [LearningDashboard.tsx](frontend/src/pages/LearningDashboard.tsx) — Replace local `StatCard` function with shared import

---

## Issue 3: Inconsistent Empty States

**Problem**: [EmptyState.tsx](frontend/src/components/EmptyState.tsx) exists as a clean shared component (icon + title + description + action) but is only used in 4 places. At least 6 other places manually render empty states with inconsistent styling.

Locations using manual empty states:
- [Dashboard.tsx:~455](frontend/src/pages/Dashboard.tsx) — "No active sprint" section
- [ProjectDetail.tsx](frontend/src/pages/ProjectDetail.tsx) — Sprints tab "No sprints for this project"
- [ProjectDetail.tsx](frontend/src/pages/ProjectDetail.tsx) — Tasks tab "No standalone tasks"
- [OverviewTab.tsx](frontend/src/components/project/OverviewTab.tsx) — "No architecture summary" (already has a styled Card version, leave as-is)

**Fix**: Replace the 3 clearest manual empty states with `<EmptyState>` component.

**Files to update**:
- [Dashboard.tsx](frontend/src/pages/Dashboard.tsx) — Replace "No active sprint" block
- [ProjectDetail.tsx](frontend/src/pages/ProjectDetail.tsx) — Replace sprints tab empty state, tasks tab empty state

---

## Issue 4: Sprint Cards Missing Progress Bars

**Problem**: The sprints tab in ProjectDetail shows a bare text like "3/5 tasks" for each sprint. The Dashboard shows a nice progress bar with gradient. The sprint cards in ProjectDetail would look much better with a mini progress bar showing completion percentage.

**Fix**: Add a small progress bar to the sprint card rows in ProjectDetail.

**File**: [ProjectDetail.tsx](frontend/src/pages/ProjectDetail.tsx) — In the sprints tab map, after the status badge and task count, add a small `div` progress bar:
```tsx
<div className="w-20 h-1.5 rounded-full bg-slate-800 overflow-hidden">
  <div className="h-full bg-gradient-to-r from-matrix-dark-green to-matrix-green rounded-full"
    style={{ width: `${sprint.total_tasks ? (sprint.completed_tasks / sprint.total_tasks) * 100 : 0}%` }} />
</div>
```

---

## Issue 5: OllamaManager Table Upgrade

**Problem**: [OllamaManager.tsx](frontend/src/pages/OllamaManager.tsx) uses a raw HTML `<table>` for the models list. With 10+ models, there's no search or sort capability.

**Fix**: Replace with `DataTable` component from [DataTable.tsx](frontend/src/components/ui/DataTable.tsx) with `searchable` and `searchKeys={['name']}` for model name search. Keep the existing columns (Name, Size, Modified, Family, Quant, Actions).

**File**: [OllamaManager.tsx](frontend/src/pages/OllamaManager.tsx) — Import DataTable, define columns array, replace `<table>` block.

---

## Summary of Changes

| # | What | Impact | Files |
|---|------|--------|-------|
| 1 | Ideas tab in ProjectDetail | New consolidation | ProjectDetail.tsx + NEW IdeasTab.tsx |
| 2 | Shared StatCard component | Consistency + ~100 LOC saved | NEW StatCard.tsx + Dashboard + ProjectDetail + LearningDashboard |
| 3 | EmptyState consistency | Visual polish | Dashboard.tsx + ProjectDetail.tsx |
| 4 | Sprint progress bars | Visual improvement | ProjectDetail.tsx |
| 5 | OllamaManager DataTable | Search/sort on models | OllamaManager.tsx |

---

## Verification

1. `cd frontend && npm run build` — TypeScript clean
2. `cd frontend && npx vitest run` — All tests pass
3. ProjectDetail: 6 tabs now (overview, sprints, plans, tasks, ideas, dependencies)
4. Ideas tab shows list + count badge, links to full Ideas page
5. Dashboard stat cards use shared StatCard component
6. Sprint cards in ProjectDetail show progress bars
7. OllamaManager models searchable via DataTable
8. Empty states consistent everywhere
