# Analytics-01: Cross-Project Intelligence Dashboard

## Context

Legion has powerful backend learning intelligence that is **completely invisible** in the frontend:
- `GET /grading/compare` — cross-project strengths/weaknesses comparison (implemented, zero UI consumers)
- `GET /grading/projects/{id}/strengths` — per-project strengths vs global averages (implemented, zero UI consumers)
- `GET /grading/models/rankings` — model success rate rankings (implemented, zero UI consumers)
- `get_feedback_loop_health()` — learning system effectiveness measurement (implemented as service method at [learning_aggregator.py:246](backend/app/services/learning_aggregator.py#L246), **no API endpoint**)

The current [Analytics.tsx](frontend/src/pages/Analytics.tsx) is a basic sprint stats display (387 lines) with:
- Summary cards (total/completed/active/success rate) using inline Card, not shared StatCard
- Task status bar chart, sprint completion donut, sprints-by-project list, recent sprints table
- Uses raw `useEffect` + `api.get()` instead of React Query hooks

**Goal**: Elevate Analytics into Legion's cross-project intelligence hub with 4 tabs. Add the one missing API endpoint. Create proper React Query hooks. ~500 lines of new code.

## Changes

### 1. Add feedback-loop-health endpoint
**File**: [grading.py](backend/app/api/endpoints/grading.py)
- Add `GET /grading/feedback-loop-health` endpoint
- Pattern: lazy import `LearningAggregatorService`, fresh `AsyncSessionLocal()` session (same as lines 70-78)
- Optional query params: `project_id: int = None`, `days: int = 30`
- Calls existing `aggregator.get_feedback_loop_health(project_id, days)`

### 2. Add grading query keys
**File**: [queryKeys.ts](frontend/src/lib/queryKeys.ts)
- Add `grading` section after `grades` (line 34):
  ```ts
  grading: {
    compare: ['grading', 'compare'] as const,
    strengths: (projectId: number) => ['grading', 'strengths', projectId] as const,
    modelRankings: (taskType?: string) => ['grading', 'model-rankings', taskType] as const,
    feedbackHealth: (projectId?: number, days?: number) => ['grading', 'feedback-health', projectId, days] as const,
  },
  ```

### 3. Create useAnalytics hooks
**File**: [useAnalytics.ts](frontend/src/hooks/useAnalytics.ts) (NEW)
- Import `useQuery` from `@tanstack/react-query`, `api` from `@/services/api`, `qk` from `@/lib/queryKeys`
- 4 hooks, all using React Query (not raw `useEffect`):

**`useCrossProjectComparison()`** — `GET /grading/compare`
- Returns `{ projects, best_practices, consistency_gaps }`
- `staleTime: 5 * 60_000` (expensive cross-project query)

**`useProjectStrengths(projectId)`** — `GET /grading/projects/{id}/strengths`
- Returns `{ project_name, strengths, weaknesses, task_success_rate, global_avg_success_rate }`
- `enabled: projectId > 0`

**`useGlobalModelRankings(taskType?)`** — `GET /grading/models/rankings`
- Returns ranked list of `{ model, global_success_rate, total_attempts, successful_attempts }`

**`useFeedbackLoopHealth(projectId?, days?)`** — `GET /grading/feedback-loop-health`
- Returns `{ status, learned_selection, default_selection, improvement_delta, per_project }`
- `staleTime: 5 * 60_000`

### 4. Rewrite Analytics.tsx with 4 tabs
**File**: [Analytics.tsx](frontend/src/pages/Analytics.tsx) — full rewrite

**Tab type**: `'overview' | 'comparison' | 'models' | 'learning'`

**Tab 1 — Overview** (keep existing content, convert to React Query):
- Convert raw `useEffect` + `api.get('/sprints/analytics/summary')` to a proper `useQuery`
- Keep: summary cards, task breakdown bars, completion donut, sprints-by-project, recent sprints
- Replace inline Card summary cards with `StatCard` from `@/components/ui/StatCard`

**Tab 2 — Project Comparison** (new, from `useCrossProjectComparison`):
- Comparison table: one row per project with name, grade (colored via `gradeColor`/`gradeBg` from [plan-helpers.ts](frontend/src/lib/plan-helpers.ts)), success rate, task count
- Strengths/weaknesses: green badges (score >= 7), red (score < 5)
- Consistency gaps: dimensions where range > 3 across projects
- Best practices: cards showing transferable patterns

**Tab 3 — Model Rankings** (new, from `useGlobalModelRankings`):
- Rankings table: model name, success rate (colored bar), total attempts, successful attempts
- Task type filter: Select dropdown — values: all, code_generation, debugging, testing, architecture
- Bar colors: green >= 70%, yellow >= 50%, red < 50%

**Tab 4 — Learning Health** (new, from `useFeedbackLoopHealth`):
- Status badge: "healthy" (green), "neutral" (yellow), "no_improvement" (red), "insufficient_data" (gray)
- Learned vs Default: two stat cards side by side with task count + success rate
- Improvement delta: large display with +/- percentage and trend icon
- Per-project breakdown table: learned_rate, default_rate, delta (colored)
- Days filter: Select dropdown (7, 30, 90)

### 5. Reuse existing shared components
- `StatCard` from [StatCard.tsx](frontend/src/components/ui/StatCard.tsx)
- `gradeColor`, `gradeBg` from [plan-helpers.ts](frontend/src/lib/plan-helpers.ts)
- `Badge` from `@/components/ui/badge`
- `Card`, `CardContent`, `CardHeader`, `CardTitle`, `CardDescription` from `@/components/ui/card`
- `Select`, `SelectContent`, `SelectItem`, `SelectTrigger`, `SelectValue` from `@/components/ui/select`
- `EmptyState` from [EmptyState.tsx](frontend/src/components/EmptyState.tsx)
- `getStatusBadgeClass` from [status-helpers.ts](frontend/src/lib/status-helpers.ts)

### 6. Minor fix: aria-label on filter clear button
**File**: [ProjectDetail.tsx:247](frontend/src/pages/ProjectDetail.tsx#L247)
- Add `aria-label="Clear filter"` to the `<button>` wrapping the X icon

## What NOT to touch
- **No migration** — all backend methods work with existing DB schema
- **No backend model changes** — TaskOutcomeDB, ModelSuccessRateDB, PlanGradeDB have needed columns
- **Sidebar** — Analytics already listed, no nav changes needed

## Verification
```bash
# Backend: verify new endpoint
curl -s http://localhost:8005/api/grading/feedback-loop-health | python -m json.tool

# Frontend: type check + build
cd frontend && npm run build

# Frontend: tests
cd frontend && npx vitest run

# Manual: navigate to /analytics, verify all 4 tabs render
# - Overview: sprint stats (existing functionality preserved)
# - Project Comparison: table with grades and strengths
# - Model Rankings: ranked model list with task type filter
# - Learning Health: learned vs default stats with days filter
```
